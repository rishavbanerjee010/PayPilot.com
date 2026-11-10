# PayPilot 
An AI-powered shopping assistant built with FastAPI — natural-language product discovery across 100+ items, instant recommendations, and secure PayPal (sandbox) checkout.
# PayPilot 🛒✈️

**An AI-powered shopping assistant with trusted PayPal checkout — ask in plain English, get real products, pay with PayPal.**

🔗 **Live demo:** https://paypilot-com.onrender.com · 📚 **API docs:** https://paypilot-com.onrender.com/docs

PayPilot is a full-stack agentic-commerce demo built for the **PayPal AI Hackathon 2026**. A natural-language shopping agent (OpenAI Responses API + function calling) recommends products from a curated 100-item INR catalogue, and checkout runs the complete **PayPal Orders v2** lifecycle — create → buyer approval → capture → server-side verification — with prices that can never be tampered with from the client.

---

## ✨ Features

### AI shopping agent (agentic commerce)
- **Real function calling** — the agent must call tools before answering anything about products; it never invents prices, specs, or stock. Available tools:
  | Tool | Purpose |
  |---|---|
  | `search_catalogue` | Budget/keyword/category search over the real catalogue ("laptop under 60k") |
  | `compare_products` | 2–3 product side-by-side comparison (price, specs, pros/cons, verdict) |
  | `get_product_details` | Full record lookup by ID or product name |
- **Bounded agent loop** — max 5 tool rounds per request; every tool execution is wrapped so one bad call can never hang or crash the request.
- **Hallucination-proof product cards** — the model ends its answer with a `RECOMMENDED_PRODUCT_IDS:` marker line; the backend parses it, strips it from the reply, and re-hydrates the cards **only from real catalogue records**. Even if the model hallucinates an ID, a fake product can never reach the UI.
- **Conversation memory** — the last 10 messages ride along, so follow-ups like "what about something cheaper?" work.
- **Honest no-match behaviour** — ask for a PlayStation 6 and it says it doesn't exist rather than fabricating a card (covered by tests).
- **Provider-agnostic** — talks to any OpenAI-compatible endpoint; runs on a **free Groq account** (`openai/gpt-oss-120b`) with zero cost.

### Secure checkout (PayPal Orders v2, Sandbox)
- **Server-authoritative pricing** — the frontend sends only `{product_id, quantity}`. The server re-validates every line against the trusted catalogue (stock, duplicates, existence) and recomputes the total. Client-supplied prices are structurally impossible to inject (422 by Pydantic schema).
- **Full order lifecycle** — OAuth2 token with cache, `POST /v2/checkout/orders`, buyer approval via PayPal-hosted page, `GET` status verification, `POST .../capture` with an idempotency key (`PayPal-Request-Id`).
- **Capture verification before success** — success is shown only if PayPal reports `COMPLETED` **and** the captured amount **and** currency exactly match the server-side order record. A tampered or mismatched capture is rejected with HTTP 402 and the order is marked `FAILED`.
- **Idempotent re-capture** — refreshing the success page or double-clicking never charges twice (`already_completed` path).
- **Full audit trail** — every payment event (`ORDER_CREATED`, `BUYER_APPROVED`, `CAPTURE_SUCCEEDED`, `CAPTURE_FAILED`, `CANCELLED`…) is logged per order in SQLite.
- **Honest currency handling** — the store is INR-focused; since PayPal does not support INR, the app surfaces a clear explanation instead of silently converting (see [Currency note](#-currency-note-inr)).

### Storefront
- **Zero-dependency SPA** — vanilla JS/CSS, hash-routed views (`#/home`, `#/explore`, `#/assistant`, `#/cart`, `#/orders`), served by FastAPI itself — one port, one service.
- **Cart with localStorage persistence**, quantity editing, and a client-side compare tray.
- **Order history page** fed by the database (capture ID, payer email, status, failure reasons).
- **PayPal return-route handling** — `/checkout-success` and `/checkout-cancel` are served by an SPA fallback so approval redirects land cleanly.
- **Accessible markup** — ARIA-labelled navigation and controls.

---

## 🏗️ Architecture

```
┌────────────────────────────── Browser (vanilla JS SPA) ──────────────────────────────┐
│  #/explore   #/assistant (chat + product cards)   #/cart   #/orders                  │
└──────────────────────────────────┬───────────────────────────────────────────────────┘
                                   │ fetch /api/...
┌──────────────────────────────────▼───────────────────────────────────────────────────┐
│                        FastAPI backend (single service on Render)                    │
│                                                                                      │
│  /api/agent/chat ──► agent.py ──► OpenAI Responses API ──┐  function calling         │
│                          │  tools: search / compare /    │  (Groq-compatible)       │
│                          ▼        details               │                          │
│                      catalog.py — 100 products, INR ◄───┘                          │
│                                                                                      │
│  /api/payments/*  ──► payments.py ──► PayPal Orders v2 REST (Sandbox)                │
│        │                 create → approve → get → capture → verify_capture           │
│        ▼                                                                             │
│  database.py — SQLite: orders, order items, payment event log                        │
│                                                                                      │
│  Static: serves frontend/ at /  (SPA fallback for PayPal return routes)              │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**Tech stack**

| Layer | Technology |
|---|---|
| Backend | Python 3, FastAPI, Pydantic v2, uvicorn |
| AI | OpenAI Responses API (`client.responses.create`) with function calling · Groq `openai/gpt-oss-120b` (free) |
| Payments | PayPal Orders v2 REST API via `httpx` (no SDK), OAuth2 client-credentials |
| Database | SQLite (`backend/paypilot.db`, path overridable via `PAYPILOT_DB_PATH`) |
| Frontend | Vanilla JS + CSS SPA (no build step), served by FastAPI |
| Tests | Offline suite with mock OpenAI + mock PayPal servers (60 checks) |
| Hosting | Render (free instance) — auto-deploys on push to `main` |

---

## 🔌 API reference

Interactive docs at `/docs` (Swagger UI). Endpoints:

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Config status: currency, AI/PayPal readiness, active model |
| `GET` | `/api/products` | Full catalogue; optional `?q=` / `?category=` server-side filters |
| `GET` | `/api/products/{id}` | One product by ID |
| `POST` | `/api/agent/chat` | `{message, history}` → `{reply, products[], tool_calls[]}` |
| `POST` | `/api/payments/create-order` | `{items:[{product_id, quantity}]}` → PayPal approval URL (total computed **server-side**) |
| `POST` | `/api/payments/capture-order` | Capture + verify (status, amount, currency); idempotent |
| `POST` | `/api/payments/cancel-order` | Cancel an un-captured order |
| `GET` | `/api/orders` | Order history with payment status and events |

---

## 🚀 Run it locally

```bash
git clone https://github.com/rishavbanerjee010/PayPilot.com.git
cd PayPilot.com/backend

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env    # then fill in your keys (see below)
uvicorn app:app --reload
```

Open http://127.0.0.1:8000 — the frontend is served by the same process.

### Environment variables (`backend/.env`)

| Variable | Required | Notes |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | Any OpenAI-compatible key. **Free option:** a Groq key from console.groq.com |
| `OPENAI_MODEL` | ✅ | `openai/gpt-oss-120b` on Groq · `gpt-4o-mini` on OpenAI |
| `OPENAI_BASE_URL` | — | `https://api.groq.com/openai/v1` for Groq; empty for OpenAI |
| `PAYPAL_CLIENT_ID` | ✅ | Sandbox app from developer.paypal.com |
| `PAYPAL_CLIENT_SECRET` | ✅ | Sandbox secret |
| `PAYPAL_BASE_URL` | — | Default: `https://api-m.sandbox.paypal.com` |
| `PAYPAL_CURRENCY` | — | Default `INR` ( PayPal rejects it — set `USD` for a working Sandbox demo) |
| `PAYPILOT_DB_PATH` | — | Custom SQLite location |

> The API key lives **only** in the backend process. Nothing secret is ever shipped to the browser.

## 🧪 Tests (no API keys needed)

The `tests/` folder ships faithful mock servers for both external APIs — the OpenAI Responses API and PayPal Orders v2 — and runs the **real application code** against them:

```bash
cd tests && python run_tests.py     # → 60 checks passed, 0 failed
```

Covered: catalogue tools (29 unit checks), the full USD checkout lifecycle, duplicate-capture idempotency, capture-before-approval (400), cancel-then-capture (409), amount-mismatch rejection (402), client-price injection (422), the INR rejection path, and 7 AI-agent conversations (budget search, chained compare, honest no-match, history follow-ups, $→INR budget conversion).

You can also run the whole app against the mocks to demo without keys — see `tests/README.md`.

## ☁️ Deploy on Render

1. Push this repo to GitHub and connect it on [dashboard.render.com](https://dashboard.render.com) (**New → Web Service**).
2. Settings: **Root directory** `backend` · Build `pip install -r requirements.txt` · Start `uvicorn app:app --host 0.0.0.0 --port $PORT` · Instance **Free**.
3. Add the environment variables from the table above (including `PAYPAL_CURRENCY=USD`).
4. Deploy — every push to `main` auto-redeploys.

## 💱 Currency note (INR)

PayPilot is deliberately India-focused: catalogue, cart, AI answers and the database all use INR (₹, Indian digit grouping like `₹1,25,000`). However **INR is not a supported PayPal REST currency** (PayPal also ended domestic Indian payments on 1 Apr 2021). This project treats that honestly:

- With `PAYPAL_CURRENCY=INR`, checkout fails with a clear explanation of the limitation — **it never silently converts your rupees into another currency**.
- For a working Sandbox demo, set `PAYPAL_CURRENCY=USD`: the store stays in INR and the Sandbox order is created for the same numeric total (Sandbox funds only — no real money, no real conversion).
- A production Indian build would integrate a domestic gateway (Razorpay / Cashfree / PayU); the payments module is isolated in `payments.py` precisely so that swap is easy.

## 🔒 Security notes

- Prices, stock and totals are computed **server-side only**; the client cannot influence amounts.
- Payment success requires **capture verification**: status `COMPLETED` + exact amount + exact currency match against the server's own order record.
- Captures are idempotent (double-submission safe), and failed captures are recorded with reasons rather than hidden.
- Secrets live exclusively in environment variables; `.env` is git-ignored; the browser holds no credentials.
- Known demo-scope limits (no auth): orders list is per-deployment, not per-user; CORS is permissive for development. Both are called out in code comments.

## 🧭 Roadmap ideas

Streaming agent replies (SSE) · voice input · per-user accounts with PayPal Log In · webhooks for asynchronous capture events · a Razorpay adapter behind the same `payments.py` interface.

---

MIT © 2026 [Rishav Banerjee](https://github.com/rishavbanerjee010) — built for the PayPal AI Hackathon 2026.
