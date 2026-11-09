"""
run_tests.py — PayPilot end-to-end test runner (no external credentials needed).

What it does:
  1. Runs catalogue unit tests (search / compare / details / INR formatting).
  2. Starts the PayPal mock (tests/paypal_mock_server.py) and the OpenAI
     Responses API mock (tests/openai_mock_server.py).
  3. Starts the real PayPilot backend (uvicorn) pointed at those mocks:
       Phase A  PAYPAL_CURRENCY=INR  -> checkout must fail with a CLEAR error
       Phase B  PAYPAL_CURRENCY=USD  -> full create -> approve -> capture flow,
                 plus duplicate capture, unapproved capture, cancel, amount
                 mismatch, and cart validation failures.
  4. Tests the AI agent endpoints with the 5 required prompts through the
     OpenAI mock (real function calls hit the real catalogue).
  5. Prints a PASS/FAIL summary and exits non-zero on any failure.

Usage (from the tests/ directory):
    python run_tests.py
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKEND = os.path.join(ROOT, "backend")
APP_URL = "http://127.0.0.1:8000"
PAYPAL_MOCK = "http://127.0.0.1:9098"
OPENAI_MOCK = "http://127.0.0.1:9099"

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {extra}")
        print(f"  FAIL  {name}  {extra}")


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------


def start_process(cmd: list[str], env_extra: dict, logfile: str) -> subprocess.Popen:
    env = {**os.environ, **env_extra}
    log = open(logfile, "w")
    return subprocess.Popen(cmd, cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT)


def wait_ready(url: str, proc: subprocess.Popen, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.4)
    return False


def stop(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def wait_port_free(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/", timeout=0.8)
            time.sleep(0.4)  # still answering -> not free yet
        except httpx.HTTPError:
            return True
    return False


def kill_port_8000() -> None:
    """Kill any leftover uvicorn app on port 8000 and wait for the port to free up."""
    # Note the [b]racket patterns: they match the target processes but not this
    # bash command line itself (pkill -f would otherwise kill its own shell).
    subprocess.run(
        ["bash", "-c", "pkill -f '[u]vicorn app:app' 2>/dev/null; sleep 1; pkill -9 -f '[u]vicorn app:app' 2>/dev/null; true"],
        capture_output=True,
    )
    if not wait_port_free(8000):
        print("WARNING: port 8000 still busy after killing uvicorn")


def kill_mocks() -> None:
    """Kill any leftover mock servers from earlier/interrupted runs."""
    subprocess.run(
        ["bash", "-c",
         "pkill -f '[p]aypal_mock_server' 2>/dev/null; pkill -f '[o]penai_mock_server' 2>/dev/null; "
         "sleep 1; pkill -9 -f '[p]aypal_mock_server' 2>/dev/null; pkill -9 -f '[o]penai_mock_server' 2>/dev/null; true"],
        capture_output=True,
    )
    ok98 = wait_port_free(9098)
    ok99 = wait_port_free(9099)
    if not (ok98 and ok99):
        print(f"WARNING: mock ports not free (9098 free={ok98}, 9099 free={ok99})")


# ---------------------------------------------------------------------------
# App environment presets
# ---------------------------------------------------------------------------

def app_env(currency: str, db_path: str) -> dict:
    return {
        "OPENAI_API_KEY": "test-key-for-mock",
        "OPENAI_BASE_URL": f"{OPENAI_MOCK}/v1",
        "OPENAI_MODEL": "mock-gpt",
        "PAYPAL_CLIENT_ID": "test-client-id",
        "PAYPAL_CLIENT_SECRET": "test-client-secret",
        "PAYPAL_BASE_URL": PAYPAL_MOCK,
        "PAYPAL_CURRENCY": currency,
        "PAYPILOT_DB_PATH": db_path,
    }


CART = [{"product_id": "PP-006", "quantity": 1}, {"product_id": "PP-010", "quantity": 2}]
CART_TOTAL_INR = 58990 + 26990 * 2  # 112,970


def create_order(client: httpx.Client):
    return client.post(f"{APP_URL}/api/payments/create-order", json={"items": CART})


# ---------------------------------------------------------------------------
# Test phases
# ---------------------------------------------------------------------------


def test_phase_a_inr(client: httpx.Client) -> None:
    """INR (the store default) must be attempted and REJECTED clearly."""
    print("\n--- Phase A: PAYPAL_CURRENCY=INR (store default) ---")
    r = client.get(f"{APP_URL}/api/health")
    check("health ok, currency=INR", r.json()["currency"] == "INR")

    r = create_order(client)
    body = r.json()
    check("create-order fails (HTTP 502)", r.status_code == 502, f"got {r.status_code}: {str(body)[:200]}")
    detail = str(body.get("detail", ""))
    check("error mentions INR not supported", "not a supported PayPal currency" in detail, detail[:160])
    check("error explains no silent conversion", "never silently convert" in detail)
    check("error points to README/USD option", "PAYPAL_CURRENCY=USD" in detail)

    orders = client.get(f"{APP_URL}/api/orders").json()
    check("failed order recorded with status FAILED",
          any(o["payment_status"] == "FAILED" for o in orders), str(orders)[:200])
    check("failed order has failure_reason", any(o.get("failure_reason") for o in orders))

    # AI agent still works while payments are in INR mode.
    test_agent_prompts(client, expect_currency_note=True)


def test_phase_b_usd(client: httpx.Client) -> None:
    print("\n--- Phase B: PAYPAL_CURRENCY=USD (explicit switch, full flow) ---")
    r = client.get(f"{APP_URL}/api/health")
    check("health ok, currency=USD", r.json()["currency"] == "USD")

    # -- happy path: create -> approve -> capture --
    r = create_order(client)
    check("create-order 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    created = r.json()
    check("approval url returned", "/sandbox/approve?token=" in created["approval_url"])
    check("server total = 112970.00 (catalogue prices)", created["total_amount"] == float(CART_TOTAL_INR),
          f"got {created.get('total_amount')}")
    check("currency USD on paypal order", created["currency"] == "USD")
    ppid = created["paypal_order_id"]

    # buyer approval (mock sandbox page) -> redirects back to the app
    r = client.get(created["approval_url"], follow_redirects=False)
    check("approve redirects (302/307)", r.status_code in (302, 307), f"got {r.status_code}")
    loc = r.headers.get("location", "")
    check("redirect goes to /checkout-success with token",
          loc.startswith(f"{APP_URL}/checkout-success") and f"token={ppid}" in loc, loc)

    r = client.post(f"{APP_URL}/api/payments/capture-order", json={"paypal_order_id": ppid})
    check("capture 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
    cap = r.json()
    check("capture success=true", cap.get("success") is True)
    check("order COMPLETED", cap["order"]["payment_status"] == "COMPLETED")
    check("capture id stored", bool(cap["order"]["capture_id"]))
    check("payer email stored", cap["order"]["payer_email"] == "sb-buyer@test.example.com")
    check("total matches server record", cap["order"]["total_amount"] == float(CART_TOTAL_INR))
    check("items preserved", len(cap["order"]["items"]) == 2)

    # duplicate capture must be handled gracefully (idempotent)
    r = client.post(f"{APP_URL}/api/payments/capture-order", json={"paypal_order_id": ppid})
    check("duplicate capture -> 200 already_completed", r.status_code == 200 and r.json()["already_completed"] is True,
          f"got {r.status_code}: {r.text[:200]}")

    orders = client.get(f"{APP_URL}/api/orders").json()
    done = [o for o in orders if o["paypal_order_id"] == ppid]
    check("orders history shows COMPLETED", len(done) == 1 and done[0]["payment_status"] == "COMPLETED")

    # -- capture before approval -> clear 400 --
    r = create_order(client)
    ppid2 = r.json()["paypal_order_id"]
    r = client.post(f"{APP_URL}/api/payments/capture-order", json={"paypal_order_id": ppid2})
    check("capture before approval -> 400 with status info",
          r.status_code == 400 and "not approved" in r.text.lower(), f"got {r.status_code}: {r.text[:200]}")

    # -- buyer cancel flow --
    r = client.post(f"{APP_URL}/api/payments/cancel-order", json={"paypal_order_id": ppid2})
    check("cancel-order ok", r.status_code == 200 and r.json()["ok"] is True)
    orders = client.get(f"{APP_URL}/api/orders").json()
    check("order now CANCELLED in history",
          any(o["paypal_order_id"] == ppid2 and o["payment_status"] == "CANCELLED" for o in orders))
    r = client.post(f"{APP_URL}/api/payments/capture-order", json={"paypal_order_id": ppid2})
    check("capture after cancel -> 409", r.status_code == 409)

    # -- unknown paypal order id --
    r = client.post(f"{APP_URL}/api/payments/capture-order", json={"paypal_order_id": "NOSUCHORDER123"})
    check("unknown paypal order -> 404", r.status_code == 404)


def test_phase_c_validation(client: httpx.Client) -> None:
    print("\n--- Phase C: request validation / error handling ---")
    r = client.post(f"{APP_URL}/api/payments/create-order", json={"items": [{"product_id": "XX-1", "quantity": 1}]})
    check("unknown product -> 404", r.status_code == 404 and "Unknown product" in r.text)
    r = client.post(f"{APP_URL}/api/payments/create-order", json={"items": [{"product_id": "PP-006", "quantity": 0}]})
    check("quantity 0 -> 422", r.status_code == 422)
    r = client.post(f"{APP_URL}/api/payments/create-order", json={"items": [{"product_id": "PP-006", "quantity": 100}]})
    check("quantity 100 -> 422", r.status_code == 422)
    r = client.post(f"{APP_URL}/api/payments/create-order", json={"items": []})
    check("empty cart -> 422", r.status_code == 422)
    r = client.post(f"{APP_URL}/api/payments/create-order",
                    json={"items": [{"product_id": "PP-006", "quantity": 1, "price": 1}]})
    check("client-supplied price ignored (extra fields forbidden)", r.status_code == 422)
    r = client.post(f"{APP_URL}/api/payments/create-order",
                    json={"items": [{"product_id": "PP-006", "quantity": 50}]})
    check("stock limit enforced", r.status_code == 400 and "stock" in r.text.lower(), r.text[:150])
    r = client.post(f"{APP_URL}/api/agent/chat", json={"message": ""})
    check("empty agent message -> 422", r.status_code == 422)
    r = client.get(f"{APP_URL}/api/products/PP-000")
    check("unknown product detail -> 404", r.status_code == 404)


def test_agent_prompts(client: httpx.Client, expect_currency_note: bool = False) -> None:
    print("\n--- AI agent prompts (via OpenAI mock, real function tools) ---")

    def chat(msg, history=None):
        return client.post(f"{APP_URL}/api/agent/chat",
                           json={"message": msg, "history": history or []}, timeout=60)

    # 1. budget search
    r = chat("Find the best laptop under ₹60,000.")
    body = r.json()
    check("1) laptop search: 200", r.status_code == 200, r.text[:200])
    check("1) used search_catalogue", "search_catalogue" in body.get("tool_calls", []))
    check("1) recommends real products", len(body.get("products", [])) >= 1)
    check("1) all products <= ₹60,000 & are laptops",
          all(p["price_inr"] <= 60000 and p["category"] == "Laptops" for p in body.get("products", [])),
          str([(p["name"], p["price_inr"]) for p in body.get("products", [])]))
    check("1) reply mentions a laptop name", "Pavilion" in body["reply"] or "IdeaPad" in body["reply"] or "Aspire" in body["reply"])
    hist1 = [{"role": "user", "content": "Find the best laptop under ₹60,000."},
             {"role": "assistant", "content": body["reply"]}]

    # 2. comparison (chained tool calls)
    r = chat("Compare the two cheapest smartphones.")
    body = r.json()
    check("2) compare: 200", r.status_code == 200, r.text[:200])
    check("2) used search_catalogue then compare_products",
          body.get("tool_calls", []) == ["search_catalogue", "compare_products"], str(body.get("tool_calls")))
    check("2) two product cards", len(body.get("products", [])) == 2)
    check("2) both are smartphones", all(p["category"] == "Smartphones" for p in body["products"]))

    # 3. student recommendation
    r = chat("Recommend a product for a college student.")
    body = r.json()
    check("3) student rec: 200 + products", r.status_code == 200 and len(body.get("products", [])) >= 1)
    check("3) grounded reply mentions ₹", "₹" in body["reply"])

    # 4. alternatives
    r = chat("Show me alternatives to the Sony WH-1000XM5.")
    body = r.json()
    check("4) alternatives: 200 + products", r.status_code == 200 and len(body.get("products", [])) >= 1)
    check("4) suggests other audio gear", any(p["id"] != "PP-010" for p in body["products"]))

    # 5. nonexistent product — must NOT be invented
    r = chat("Do you have a Gucci handbag in stock?")
    body = r.json()
    check("5) nonexistent: 200", r.status_code == 200)
    check("5) honest no-match reply", "nothing matches" in body["reply"].lower() or "couldn't find" in body["reply"].lower(),
          body["reply"][:120])
    check("5) NO product cards fabricated", len(body.get("products", [])) == 0)

    # 6. follow-up with conversation history
    r = chat("what about something cheaper?", history=hist1)
    body = r.json()
    check("6) follow-up accepted with history", r.status_code == 200, r.text[:200])
    check("6) follow-up used tools again", len(body.get("tool_calls", [])) >= 1)

    # 7. foreign-currency budget (converted to INR by the model layer)
    r = chat("Find a laptop under $800.")
    body = r.json()
    check("7) $ budget: 200 + products", r.status_code == 200 and len(body.get("products", [])) >= 1, r.text[:200])
    check("7) $ converted to ~₹68,000 search",
          all(p["price_inr"] <= 68000 and p["category"] == "Laptops" for p in body.get("products", [])),
          str([(p["name"], p["price_inr"]) for p in body.get("products", [])]))


def test_amount_mismatch(client: httpx.Client) -> None:
    """With MOCK_AMOUNT_FAIL=1 the capture returns a wrong amount -> must be rejected."""
    print("\n--- Phase D: amount mismatch verification (mock returns 999.99) ---")
    r = create_order(client)
    created = r.json()
    ppid = created["paypal_order_id"]
    client.get(created["approval_url"], follow_redirects=False)
    r = client.post(f"{APP_URL}/api/payments/capture-order", json={"paypal_order_id": ppid})
    check("mismatched capture -> 402 (payment required, rejected)", r.status_code == 402, f"got {r.status_code}")
    check("mismatch message explains amounts", "Amount mismatch" in r.text, r.text[:200])
    orders = client.get(f"{APP_URL}/api/orders").json()
    check("order marked FAILED after mismatch",
          any(o["paypal_order_id"] == ppid and o["payment_status"] == "FAILED" for o in orders))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    kill_port_8000()
    kill_mocks()

    print("=== 1/5 Catalogue unit tests ===")
    rc = subprocess.run([sys.executable, os.path.join(HERE, "test_catalog_tools.py")], cwd=BACKEND)
    global PASS, FAIL
    if rc.returncode == 0:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append("catalogue unit tests")

    print("\n=== 2/5 Starting mock servers ===")
    paypal_mock = start_process(
        [sys.executable, os.path.join(HERE, "paypal_mock_server.py")], {}, "/tmp/paypal_mock.log"
    )
    openai_mock = start_process(
        [sys.executable, os.path.join(HERE, "openai_mock_server.py")], {}, "/tmp/openai_mock.log"
    )
    if not wait_ready(f"{PAYPAL_MOCK}/sandbox/state", paypal_mock):
        print("FATAL: PayPal mock did not start; see /tmp/paypal_mock.log")
        stop(paypal_mock); stop(openai_mock)
        return 1
    if not wait_ready(f"{OPENAI_MOCK}/docs", openai_mock):
        print("FATAL: OpenAI mock did not start; see /tmp/openai_mock.log")
        stop(paypal_mock); stop(openai_mock)
        return 1
    print("mocks up")

    app = None
    db_a = "/tmp/paypilot_test_a.db"
    db_b = "/tmp/paypilot_test_b.db"
    db_c = "/tmp/paypilot_test_c.db"
    for p in (db_a, db_b, db_c):
        if os.path.exists(p):
            os.remove(p)

    try:
        print("\n=== 3/5 Phase A: backend in INR mode ===")
        app = start_process(
            [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"],
            app_env("INR", db_a), "/tmp/paypilot_app_a.log",
        )
        if not wait_ready(f"{APP_URL}/api/health", app):
            print("FATAL: app (INR) did not start; see /tmp/paypilot_app_a.log")
            return 1
        with httpx.Client(timeout=60) as c:
            test_phase_a_inr(c)
        stop(app); app = None

        print("\n=== 4/5 Phase B/C: backend in USD mode ===")
        app = start_process(
            [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"],
            app_env("USD", db_b), "/tmp/paypilot_app_b.log",
        )
        if not wait_ready(f"{APP_URL}/api/health", app):
            print("FATAL: app (USD) did not start; see /tmp/paypilot_app_b.log")
            return 1
        with httpx.Client(timeout=60) as c:
            test_phase_b_usd(c)
            test_phase_c_validation(c)
        stop(app); app = None

        print("\n=== 5/5 Phase D: amount mismatch (mock restarted with MOCK_AMOUNT_FAIL=1) ===")
        stop(paypal_mock)
        if not wait_port_free(9098):
            print("FATAL: port 9098 did not free up for the amount-fail mock")
            return 1
        paypal_mock = start_process(
            [sys.executable, os.path.join(HERE, "paypal_mock_server.py")],
            {"MOCK_AMOUNT_FAIL": "1"}, "/tmp/paypal_mock2.log",
        )
        if not wait_ready(f"{PAYPAL_MOCK}/sandbox/state", paypal_mock):
            print("FATAL: PayPal mock (amount-fail) did not start")
            return 1
        cfg = httpx.get(f"{PAYPAL_MOCK}/sandbox/config", timeout=5).json()
        if not cfg.get("amount_fail"):
            print(f"FATAL: amount-fail mock did not load its config: {cfg}")
            return 1
        app = start_process(
            [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"],
            app_env("USD", db_c), "/tmp/paypilot_app_c.log",
        )
        if not wait_ready(f"{APP_URL}/api/health", app):
            print("FATAL: app (mismatch phase) did not start")
            return 1
        with httpx.Client(timeout=60) as c:
            test_amount_mismatch(c)
    finally:
        stop(app)
        stop(paypal_mock)
        stop(openai_mock)
        kill_port_8000()

    print(f"\n{'=' * 60}\nRESULT: {PASS} passed, {FAIL} failed")
    if FAILURES:
        print("Failures:")
        for f in FAILURES:
            print(f"  - {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
