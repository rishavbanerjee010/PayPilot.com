"""
app.py — PayPilot FastAPI application.

Run from the backend/ directory:
    uvicorn app:app --reload

The app serves:
  - the REST API under /api/...
  - the frontend (frontend/../frontend/index.html) at / with an SPA fallback
    for /checkout-success and /checkout-cancel (PayPal return routes)
  - OpenAPI docs at /docs
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

import agent as agent_module
import catalog
import database as db
import payments
from models import (
    AgentChatRequest,
    AgentChatResponse,
    CancelRequest,
    CaptureRequest,
    CaptureResultResponse,
    CheckoutRequest,
    HealthResponse,
    OrderCreatedResponse,
    OrderOut,
    ProductOut,
)

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"

app = FastAPI(
    title="PayPilot API",
    description="AI-powered shopping assistant — FastAPI + OpenAI + PayPal Sandbox (INR store).",
    version="1.0.0",
)

# Same-origin in normal use; permissive CORS only so the frontend can also be
# opened from a dev server during development. No secrets exist client-side.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ===========================================================================
# Health & catalogue
# ===========================================================================


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="paypilot",
        time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        currency=payments.PAYPAL_CURRENCY,
        openai_configured=bool(agent_module.OPENAI_API_KEY),
        paypal_configured=payments.paypal_configured(),
        model=agent_module.OPENAI_MODEL if agent_module.OPENAI_API_KEY else None,
    )


@app.get("/api/products", response_model=List[ProductOut])
def list_products(
    category: str = Query(default=None, max_length=50),
    q: str = Query(default=None, max_length=120),
) -> List[ProductOut]:
    """Return catalogue products. Optional ?category= and ?q= server-side filters."""
    if category or q:
        result = catalog.search_catalogue(query=q or "", category=category, limit=12)
        items = [catalog.get_product(p["id"]) for p in result["products"]]
    else:
        items = list(catalog.PRODUCTS)
    return [ProductOut(**catalog.product_full(p)) for p in items]


@app.get("/api/products/{product_id}", response_model=ProductOut)
def get_product(product_id: str) -> ProductOut:
    product = catalog.get_product(product_id.strip().upper())
    if not product:
        raise HTTPException(
            status_code=404,
            detail=f"No product with id '{product_id}' exists in the catalogue.",
        )
    return ProductOut(**catalog.product_full(product))


# ===========================================================================
# AI shopping agent
# ===========================================================================


@app.post("/api/agent/chat", response_model=AgentChatResponse)
def agent_chat(payload: AgentChatRequest) -> AgentChatResponse:
    try:
        result = agent_module.run_agent(
            message=payload.message,
            history=[m.model_dump() for m in payload.history],
        )
    except agent_module.AgentNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except agent_module.AgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return AgentChatResponse(
        reply=result["reply"],
        products=[ProductOut(**p) for p in result["products"]],
        tool_calls=result["tool_calls"],
    )


# ===========================================================================
# Payments — PayPal Orders v2 (Sandbox)
# ===========================================================================


@app.post("/api/payments/create-order", response_model=OrderCreatedResponse)
async def create_order(payload: CheckoutRequest, request: Request) -> OrderCreatedResponse:
    """Validate the cart against the trusted catalogue, compute the total on the
    SERVER, create a PayPal order and return the buyer-approval URL.

    The frontend sends only product IDs and quantities — never prices.
    """
    # 1) Validate every line against the trusted catalogue and price it server-side.
    items: List[dict] = []
    seen: set = set()
    total = 0
    for line in payload.items:
        pid = line.product_id.strip().upper()
        product = catalog.get_product(pid)
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown product id '{line.product_id}'. Your cart may be outdated — please refresh.",
            )
        if pid in seen:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate line for product '{product['name']}' — merge quantities in your cart.",
            )
        seen.add(pid)
        if product["stock"] < line.quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Only {product['stock']} unit(s) of '{product['name']}' are in stock "
                    f"(you asked for {line.quantity})."
                ),
            )
        line_total = product["price_inr"] * line.quantity
        total += line_total
        items.append(
            {
                "product_id": pid,
                "product_name": product["name"],
                "unit_price": product["price_inr"],
                "quantity": line.quantity,
                "line_total": line_total,
            }
        )

    if total <= 0:
        raise HTTPException(status_code=400, detail="Cart total must be greater than zero.")

    currency = payments.PAYPAL_CURRENCY
    order_id = f"PP-{uuid.uuid4().hex[:8].upper()}"
    db.create_order(order_id, items, total, currency)

    base = str(request.base_url).rstrip("/")
    try:
        created = await payments.create_order(
            amount=total,
            currency=currency,
            description=f"PayPilot order {order_id} — {len(items)} item(s)",
            return_url=f"{base}/checkout-success",
            cancel_url=f"{base}/checkout-cancel",
        )
    except payments.PayPalError as exc:
        db.mark_order_failed(order_id, exc.detail or exc.user_message)
        db.log_payment_event(order_id, "CREATE_FAILED", exc.detail or exc.user_message)
        raise HTTPException(status_code=exc.status_code, detail=exc.user_message)

    db.attach_paypal_order(order_id, created["paypal_order_id"])
    db.log_payment_event(
        order_id, "ORDER_CREATED", f"PayPal order for {currency} {total}", created["paypal_order_id"]
    )
    return OrderCreatedResponse(
        order_id=order_id,
        paypal_order_id=created["paypal_order_id"],
        approval_url=created["approval_url"],
        total_amount=float(total),
        total_display=f"{catalog.CURRENCY_SYMBOL}{catalog.format_inr(total)}",
        currency=currency,
        status="CREATED",
    )


@app.post("/api/payments/capture-order", response_model=CaptureResultResponse)
async def capture_order(payload: CaptureRequest) -> CaptureResultResponse:
    """Capture an approved PayPal order and VERIFY it before reporting success.

    Success is returned only when PayPal reports capture status COMPLETED with
    an amount and currency that exactly match the server-side order record.
    """
    paypal_order_id = payload.paypal_order_id.strip()
    order = db.get_order_by_paypal_id(paypal_order_id)
    if not order:
        raise HTTPException(
            status_code=404,
            detail=f"No PayPilot order is associated with PayPal order '{paypal_order_id}'.",
        )
    order_id = order["order_id"]
    expected_amount = order["total_amount"]
    expected_currency = order["currency"]

    # Idempotent re-capture (e.g. page refresh after success).
    if order["payment_status"] == "COMPLETED":
        return CaptureResultResponse(
            success=True,
            order=_order_out(order),
            message="This payment was already captured and verified. Nothing was charged twice.",
            already_completed=True,
        )
    if order["payment_status"] in ("CANCELLED", "FAILED"):
        raise HTTPException(
            status_code=409,
            detail=f"This order is {order['payment_status']} and can no longer be captured.",
        )

    try:
        remote = await payments.get_order(paypal_order_id)
    except payments.PayPalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.user_message)

    remote_status = remote.get("status")
    db.log_payment_event(order_id, "REMOTE_STATUS", f"PayPal reports order status: {remote_status}", paypal_order_id)

    if remote_status == "COMPLETED":
        # Someone captured it outside our UI (e.g. duplicate attempt): verify then sync.
        verification = payments.verify_capture(remote, expected_amount, expected_currency)
        if verification["ok"]:
            capture = verification["capture"]
            db.mark_order_completed(
                order_id,
                capture_id=capture.get("id", ""),
                payer_email=remote.get("payer", {}).get("email_address", ""),
            )
            db.log_payment_event(order_id, "CAPTURE_SUCCEEDED", "Synced an externally completed capture", paypal_order_id)
            refreshed = db.get_order_by_internal_id(order_id)
            return CaptureResultResponse(
                success=True,
                order=_order_out(refreshed),
                message="This payment was already captured on PayPal. Details verified and synced.",
                already_completed=True,
            )
        db.mark_order_failed(order_id, verification["reason"])
        db.log_payment_event(order_id, "CAPTURE_FAILED", verification["reason"], paypal_order_id)
        raise HTTPException(status_code=402, detail=f"Payment verification failed: {verification['reason']}")

    if remote_status != "APPROVED":
        raise HTTPException(
            status_code=400,
            detail=(
                f"The buyer has not approved this order yet (PayPal status: '{remote_status}'). "
                "Open the approval URL and approve the payment before capturing."
            ),
        )

    db.mark_order_approved(order_id)
    db.log_payment_event(order_id, "BUYER_APPROVED", "Buyer approved the order on PayPal", paypal_order_id)

    try:
        capture_result = await payments.capture_order(paypal_order_id)
    except payments.PayPalError as exc:
        reason = exc.user_message
        db.mark_order_failed(order_id, reason)
        db.log_payment_event(order_id, "CAPTURE_FAILED", exc.detail or reason, paypal_order_id)
        status_code = 409 if payments.is_already_captured_error(exc) else exc.status_code
        raise HTTPException(status_code=status_code, detail=reason)

    verification = payments.verify_capture(capture_result, expected_amount, expected_currency)
    if not verification["ok"]:
        db.mark_order_failed(order_id, verification["reason"])
        db.log_payment_event(order_id, "CAPTURE_FAILED", verification["reason"], paypal_order_id)
        raise HTTPException(status_code=402, detail=f"Payment verification failed: {verification['reason']}")

    capture = verification["capture"]
    db.mark_order_completed(
        order_id,
        capture_id=capture.get("id", ""),
        payer_email=capture_result.get("payer", {}).get("email_address", ""),
    )
    db.log_payment_event(
        order_id,
        "CAPTURE_SUCCEEDED",
        f"Captured {expected_currency} {capture.get('amount', {}).get('value')} (id {capture.get('id')})",
        paypal_order_id,
    )
    refreshed = db.get_order_by_internal_id(order_id)
    return CaptureResultResponse(
        success=True,
        order=_order_out(refreshed),
        message="Payment captured and verified successfully.",
        already_completed=False,
    )


@app.post("/api/payments/cancel-order")
def cancel_order(payload: CancelRequest) -> dict:
    """Mark an un-captured order as cancelled (buyer backed out on PayPal)."""
    order = db.get_order_by_paypal_id(payload.paypal_order_id.strip())
    if not order:
        raise HTTPException(status_code=404, detail=f"No order found for PayPal id '{payload.paypal_order_id}'.")
    if order["payment_status"] == "COMPLETED":
        return {"ok": False, "message": "This order was already paid — it cannot be cancelled here."}
    db.mark_order_cancelled(order["order_id"])
    db.log_payment_event(order["order_id"], "CANCELLED", "Buyer cancelled on PayPal", order["paypal_order_id"])
    return {"ok": True, "message": "Order cancelled. Your cart is still intact if you want to try again."}


# ===========================================================================
# Orders / transaction history (demo user — no authentication, see README)
# ===========================================================================


def _order_out(order: dict) -> OrderOut:
    return OrderOut(
        order_id=order["order_id"],
        total_amount=order["total_amount"],
        total_display=f"{catalog.CURRENCY_SYMBOL}{catalog.format_inr(order['total_amount'])}",
        currency=order["currency"],
        payment_status=order["payment_status"],
        paypal_order_id=order.get("paypal_order_id"),
        capture_id=order.get("capture_id"),
        payer_email=order.get("payer_email"),
        failure_reason=order.get("failure_reason"),
        created_at=order["created_at"],
        items=order.get("items", []),
    )


@app.get("/api/orders", response_model=List[OrderOut])
def list_orders() -> List[OrderOut]:
    return [_order_out(o) for o in db.list_orders()]


# ===========================================================================
# Static frontend (served by FastAPI so everything runs on one port)
# ===========================================================================

app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/{spa_path:path}", include_in_schema=False)
def spa_fallback(spa_path: str):
    """Serve real static files when they exist; otherwise index.html.

    This backs the PayPal return routes /checkout-success and /checkout-cancel
    while keeping the app a single-page frontend with hash navigation.
    """
    if spa_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    candidate = (FRONTEND_DIR / spa_path).resolve()
    try:
        candidate.relative_to(FRONTEND_DIR.resolve())
    except ValueError:
        return FileResponse(FRONTEND_DIR / "index.html")
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(FRONTEND_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
