"""
paypal_mock_server.py — a local test double for the PayPal Orders v2 REST API.

Why this exists: PayPilot's payment code is written against the REAL PayPal
Sandbox REST contract (OAuth2 token -> create order -> approve link ->
capture, with 4xx error shapes). This mock implements that same contract so
the full create/approve/capture flow — including failure paths — can be tested
offline, before you plug in your own Sandbox credentials.

It is a TEST TOOL only; the application never uses it unless you explicitly
point PAYPAL_BASE_URL at it (the test runner does this).

Run:  python paypal_mock_server.py   (listens on http://127.0.0.1:9098)

Config via environment:
  MOCK_REJECT_INR=1   (default) reject INR orders exactly like real PayPal does
  MOCK_ALLOW_INR=1    accept INR (to test the happy path as if supported)
  MOCK_AMOUNT_FAIL=1  return a capture amount that mismatches (tests verification)
  MOCK_CAPTURE_FAIL=1 make capture return a 500 error
"""
from __future__ import annotations

import base64
import os
import random
import string
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

MOCK_HOST = "127.0.0.1"
MOCK_PORT = int(os.environ.get("PAYPAL_MOCK_PORT", "9098"))
MOCK_BASE = f"http://{MOCK_HOST}:{MOCK_PORT}"

MOCK_CLIENT_ID = os.environ.get("MOCK_PAYPAL_CLIENT_ID", "test-client-id")
MOCK_CLIENT_SECRET = os.environ.get("MOCK_PAYPAL_CLIENT_SECRET", "test-client-secret")

REJECT_INR = os.environ.get("MOCK_ALLOW_INR", "0") != "1"
AMOUNT_FAIL = os.environ.get("MOCK_AMOUNT_FAIL", "0") == "1"
CAPTURE_FAIL = os.environ.get("MOCK_CAPTURE_FAIL", "0") == "1"

# Real PayPal supported-currency list (subset) — INR is genuinely absent.
SUPPORTED_CURRENCIES = {
    "USD", "EUR", "GBP", "AUD", "CAD", "SGD", "JPY", "CHF", "SEK", "DKK",
    "NOK", "NZD", "HKD", "THB", "MYR", "PHP", "TWD", "BRL", "MXN", "ILS",
    "PLN", "CZK", "HUF", "ZAR",
}

app = FastAPI(title="PayPal Mock (Orders v2)")

# paypal_order_id -> order dict
ORDERS: dict = {}


def _rand_id(prefix: str, n: int = 17) -> str:
    return prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def _error(status: int, name: str, message: str, issue: str | None = None, description: str | None = None):
    details = []
    if issue:
        details.append({"issue": issue, "description": description or issue.replace("_", " ").title()})
    return JSONResponse(
        status_code=status,
        content={"name": name, "message": message, "details": details, "links": []},
    )


def _links(order_id: str, return_url: str, cancel_url: str):
    return [
        {"rel": "self", "href": f"{MOCK_BASE}/v2/checkout/orders/{order_id}", "method": "GET"},
        {"rel": "approve", "href": f"{MOCK_BASE}/sandbox/approve?token={order_id}", "method": "GET"},
        {"rel": "capture", "href": f"{MOCK_BASE}/v2/checkout/orders/{order_id}/capture", "method": "POST"},
        {"rel": "return", "href": return_url, "method": "GET"},
        {"rel": "cancel", "href": cancel_url, "method": "GET"},
    ]


def _order_json(o: dict) -> dict:
    return {
        "id": o["id"],
        "status": o["status"],
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": o.get("reference_id", "paypilot-store"),
                "amount": o["amount"],
                "payments": o.get("payments"),
            }
        ],
        "payer": o.get("payer"),
        "create_time": o["created_at"],
        "links": _links(o["id"], o["return_url"], o["cancel_url"]),
    }


# ---------------------------------------------------------------------------
# OAuth2
# ---------------------------------------------------------------------------

@app.post("/v1/oauth2/token")
async def oauth_token(request: Request):
    auth = request.headers.get("authorization", "")
    try:
        b64 = auth.split(" ", 1)[1]
        cid, secret = base64.b64decode(b64).decode().split(":", 1)
    except Exception:
        return _error(401, "INVALID_AUTHORIZATION", "Malformed Basic auth header.")
    if cid != MOCK_CLIENT_ID or secret != MOCK_CLIENT_SECRET:
        return _error(401, "INVALID_CLIENT", "Client Authentication failed.")
    form = await request.form()
    if form.get("grant_type") != "client_credentials":
        return _error(400, "UNSUPPORTED_GRANT_TYPE", "Unsupported grant_type.")
    return {
        "scope": "https://uri.paypal.com/services/payments",
        "access_token": "mock-access-token-" + uuid.uuid4().hex[:12],
        "token_type": "Bearer",
        "app_id": "APP-MOCK",
        "expires_in": 32400,
        "nonce": "mock",
    }


def _check_bearer(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return _error(401, "NOT_AUTHORIZED", "Missing bearer token.")
    return None


# ---------------------------------------------------------------------------
# Orders v2
# ---------------------------------------------------------------------------

@app.post("/v2/checkout/orders")
async def create_order(request: Request):
    err = _check_bearer(request)
    if err:
        return err
    try:
        body = await request.json()
        pu = body["purchase_units"][0]
        amount = pu["amount"]
        value = str(amount["value"])
        currency = str(amount["currency_code"]).upper()
        ctx = body.get("application_context", {})
    except Exception:
        return _error(400, "INVALID_REQUEST", "Request is not well formed.")

    # --- the important bit: real PayPal rejects unsupported currencies ---
    if currency == "INR" and REJECT_INR:
        return _error(
            400,
            "INVALID_REQUEST",
            "Request is not well formed. The currency code is not currently supported.",
            issue="CURRENCY_NOT_SUPPORTED",
            description="The currency code INR is not currently supported for this transaction.",
        )
    if currency not in SUPPORTED_CURRENCIES:
        return _error(
            400,
            "INVALID_REQUEST",
            "Request is not well formed. The currency code is not currently supported.",
            issue="CURRENCY_NOT_SUPPORTED",
            description=f"The currency code {currency} is not currently supported for this transaction.",
        )

    try:
        float(value)
    except ValueError:
        return _error(400, "INVALID_REQUEST", "Amount value is invalid.")

    order_id = _rand_id("PAYPAL-") if random.random() < 0.3 else _rand_id("", 17)
    ORDERS[order_id] = {
        "id": order_id,
        "status": "CREATED",
        "amount": {"currency_code": currency, "value": value},
        "reference_id": pu.get("reference_id", ""),
        "return_url": ctx.get("return_url", "http://127.0.0.1:8000/checkout-success"),
        "cancel_url": ctx.get("cancel_url", "http://127.0.0.1:8000/checkout-cancel"),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "payments": None,
        "payer": None,
    }
    return JSONResponse(status_code=201, content=_order_json(ORDERS[order_id]))


@app.get("/v2/checkout/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    err = _check_bearer(request)
    if err:
        return err
    o = ORDERS.get(order_id)
    if not o:
        return _error(404, "RESOURCE_NOT_FOUND", f"Order with id '{order_id}' not found.")
    return _order_json(o)


@app.post("/v2/checkout/orders/{order_id}/capture")
async def capture(order_id: str, request: Request):
    err = _check_bearer(request)
    if err:
        return err
    o = ORDERS.get(order_id)
    if not o:
        return _error(404, "RESOURCE_NOT_FOUND", f"Order with id '{order_id}' not found.")
    if o["status"] == "COMPLETED":
        return _error(
            422,
            "UNPROCESSABLE_ENTITY",
            "The requested action could not be performed, semantically incorrect, or failed business validation.",
            issue="ORDER_ALREADY_CAPTURED",
            description="Order already captured. If you are seeing this, you might be trying to capture an order twice.",
        )
    if o["status"] != "APPROVED":
        return _error(
            422,
            "UNPROCESSABLE_ENTITY",
            "The requested action could not be performed.",
            issue="ORDER_NOT_APPROVED",
            description="The order is not approved by the buyer.",
        )
    if CAPTURE_FAIL:
        return _error(500, "INTERNAL_SERVER_ERROR", "An internal server error has occurred.")

    capture_value = "999.99" if AMOUNT_FAIL else o["amount"]["value"]
    capture_id = _rand_id("CAP-", 13)
    o["status"] = "COMPLETED"
    o["payments"] = {
        "captures": [
            {
                "id": capture_id,
                "status": "COMPLETED",
                "amount": {"currency_code": o["amount"]["currency_code"], "value": capture_value},
                "final_capture": True,
                "create_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ]
    }
    o["payer"] = {
        "name": {"given_name": "Test", "surname": "Buyer"},
        "email_address": "sb-buyer@test.example.com",
        "payer_id": "MOCKPAYER123",
    }
    return JSONResponse(status_code=201, content=_order_json(o))


# ---------------------------------------------------------------------------
# Sandbox approval page (what the buyer would do on paypal.com)
# ---------------------------------------------------------------------------

@app.get("/sandbox/approve")
async def approve(token: str):
    """Simulates the buyer logging in and clicking 'Pay Now' on PayPal."""
    o = ORDERS.get(token)
    if not o:
        return _error(404, "RESOURCE_NOT_FOUND", f"Order with id '{token}' not found.")
    if o["status"] == "CREATED":
        o["status"] = "APPROVED"
    sep = "&" if "?" in o["return_url"] else "?"
    return RedirectResponse(f"{o['return_url']}{sep}token={o['id']}&PayerID=MOCKPAYER123")


@app.get("/sandbox/reset")
async def reset():
    ORDERS.clear()
    return {"ok": True, "cleared": True}


@app.get("/sandbox/config")
async def config():
    """Lets test runners verify which failure mode this instance runs with."""
    return {
        "reject_inr": REJECT_INR,
        "amount_fail": AMOUNT_FAIL,
        "capture_fail": CAPTURE_FAIL,
        "client_id": MOCK_CLIENT_ID,
    }


@app.get("/sandbox/state")
async def state():
    return {oid: {"status": o["status"], "amount": o["amount"]} for oid, o in ORDERS.items()}


if __name__ == "__main__":
    import uvicorn

    print(f"PayPal mock listening on {MOCK_BASE} (reject_inr={REJECT_INR}, amount_fail={AMOUNT_FAIL}, capture_fail={CAPTURE_FAIL})")
    uvicorn.run(app, host=MOCK_HOST, port=MOCK_PORT, log_level="warning")
