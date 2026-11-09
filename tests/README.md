# PayPilot test suite

Offline tests for the whole PayPilot stack — **no OpenAI or PayPal credentials needed**.
Two local "test doubles" impersonate the external services using their real REST contracts:

| File | What it impersonates | Port |
|---|---|---|
| `paypal_mock_server.py` | PayPal Orders v2 REST API (OAuth2, create/get/capture, sandbox approval page, INR rejection, error shapes) | 9098 |
| `openai_mock_server.py` | OpenAI Responses API (`POST /v1/responses`) with rule-based function calling | 9099 |
| `test_catalog_tools.py` | — unit tests for the catalogue tools (no server) | — |
| `run_tests.py` | orchestrator: starts mocks + backend and runs every scenario | — |

The application code is **unchanged** during tests — the runner simply points
`PAYPAL_BASE_URL` and `OPENAI_BASE_URL` at the local mocks via environment variables.

## Run

```bash
cd tests
python run_tests.py
```

(Needs the same Python packages as the backend: `pip install -r ../backend/requirements.txt`.)

Expected result: **60 checks passed, 0 failed.**

## What is covered

**Catalogue unit tests (29)**
- Indian number formatting (`₹12,499`, `₹1,25,000`), ₹ budget parsing
  ("under 60k", "₹25,000", "1.5 lakh"), search (category / budget / keywords),
  comparison (cheapest/rating/spec advantages, budget fit), details lookup by id or name,
  honest error for unknown products.

**Payments, Phase A — INR (default store currency)**
- Checkout attempt in INR is rejected by the (mock) PayPal exactly like the real one, and
  the API returns a clear explanation that mentions the limitation, promises no silent
  conversion, and points to `PAYPAL_CURRENCY=USD`; the failed order is recorded as FAILED
  with a reason.

**Payments, Phase B/C — USD (explicit demo currency)**
- Full flow: create (server-side total 1,12,970 from catalogue prices) → approval redirect
  to `/checkout-success?token=…` → capture → COMPLETED with capture id + payer email →
  order history.
- Duplicate capture is idempotent (`already_completed`).
- Capture before approval → 400; capture after cancel → 409; unknown PayPal order → 404.
- Cart validation: unknown product 404, quantity 0/100 → 422, empty cart → 422,
  client-supplied price field ignored (422), stock limit → 400.

**Payments, Phase D — amount mismatch**
- The mock returns a capture amount of 999.99 while the server expects the real total →
  capture is rejected with 402 "Amount mismatch" and the order is marked FAILED.

**AI agent prompts (7 conversations)**
- "Find the best laptop under ₹60,000" (search tool, only laptops ≤ ₹60,000),
  "Compare the two cheapest smartphones" (chained search → compare tools, 2 cards),
  "Recommend a product for a college student", "Show me alternatives to the Sony
  WH-1000XM5", "Do you have a PlayStation 6 console?" (honest no-match, **zero** fabricated
  product cards), follow-up with conversation history, and "$800" budget converted to INR.

## Using the mocks manually (demo without keys)

You can run the app against the mocks to demo the full experience before your own keys
arrive (the browser checkout even works end-to-end — the mock approval page redirects
back like real PayPal):

```bash
# terminal 1
python paypal_mock_server.py
# terminal 2
python openai_mock_server.py
# terminal 3 (from the backend/ folder)
# PowerShell:
$env:OPENAI_API_KEY="test-key"; $env:OPENAI_BASE_URL="http://127.0.0.1:9099/v1";
$env:PAYPAL_CLIENT_ID="test-client-id"; $env:PAYPAL_CLIENT_SECRET="test-client-secret";
$env:PAYPAL_BASE_URL="http://127.0.0.1:9098"; $env:PAYPAL_CURRENCY="USD";
uvicorn app:app --reload
# bash:
OPENAI_API_KEY=test-key OPENAI_BASE_URL=http://127.0.0.1:9099/v1 \
PAYPAL_CLIENT_ID=test-client-id PAYPAL_CLIENT_SECRET=test-client-secret \
PAYPAL_BASE_URL=http://127.0.0.1:9098 PAYPAL_CURRENCY=USD \
uvicorn app:app --reload
```

Then open http://127.0.0.1:8000, add items, check out — the "PayPal" approval page is the
mock's `/sandbox/approve` endpoint. Swap `PAYPAL_CURRENCY=INR` to see the honest INR
rejection. **Never use these env vars in production** — they are for offline testing only.

## Mock configuration knobs

`paypal_mock_server.py` reads (before start):

| Env var | Effect |
|---|---|
| `MOCK_ALLOW_INR=1` | Accept INR orders (to test the happy path as if PayPal supported it) |
| `MOCK_AMOUNT_FAIL=1` | Return a wrong capture amount (tests verification) |
| `MOCK_CAPTURE_FAIL=1` | Make capture return HTTP 500 (tests failure handling) |

`/sandbox/reset` clears mock state; `/sandbox/state` shows all mock orders.

## Honest scope note

These tests verify PayPilot's own logic — request/response handling, tool execution,
state transitions, verification — against faithful reimplementations of the external REST
contracts. The final mile (your real OpenAI key, your real PayPal Sandbox app and buyer
account) must be tested once with your own credentials following the main README's
"PayPal Sandbox payment" checklist.
