"""
payments.py — PayPal Sandbox Orders v2 integration (REST API, no SDK).

Flow implemented here (see app.py for orchestration):
  1. create_order()        -> POST /v2/checkout/orders        (amount from SERVER catalogue)
  2. buyer approves        -> the approval URL we return to the frontend
  3. get_order()           -> GET  /v2/checkout/orders/{id}   (verify status == APPROVED)
  4. capture_order()       -> POST /v2/checkout/orders/{id}/capture
  5. verify_capture()      -> amount AND currency must match the server-side expectation

Currency policy (important):
  PayPilot is an India-focused store: the catalogue, cart, AI and database all
  use INR, and PAYPAL_CURRENCY defaults to INR. PayPal's REST API currency list
  (https://developer.paypal.com/api/nvp-soap/currency-codes/) does NOT include
  INR, and PayPal discontinued domestic payments in India on 1 April 2021.
  We therefore attempt the order in the configured currency and, when PayPal
  rejects it, surface a clear explanation. We NEVER silently convert INR to
  another currency. See README.md ("Currency note") for details.
"""

from __future__ import annotations

import base64
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "").strip()
PAYPAL_BASE_URL = os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
PAYPAL_CURRENCY = os.environ.get("PAYPAL_CURRENCY", "INR").strip().upper()

# Money format helpers -------------------------------------------------------


def inr_display(amount: float) -> str:
    from catalog import format_inr

    return f"\u20b9{format_inr(amount)}"


def paypal_amount(amount: float) -> str:
    """Format a rupee amount the way PayPal expects: '59990.00'."""
    return f"{Decimal(str(amount)).quantize(Decimal('0.01'))}"


def paypal_configured() -> bool:
    return bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET)


class PayPalError(Exception):
    """Raised for any PayPal-side failure; .user_message is safe to show users."""

    def __init__(self, user_message: str, status_code: int = 502, detail: Optional[str] = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code
        self.detail = detail or user_message


# ---------------------------------------------------------------------------
# Low-level REST helpers
# ---------------------------------------------------------------------------

_access_token_cache: Dict[str, Any] = {"token": None, "expires_at": 0.0}


async def _get_access_token(client: httpx.AsyncClient) -> str:
    import time

    if _access_token_cache["token"] and time.time() < _access_token_cache["expires_at"] - 60:
        return _access_token_cache["token"]

    if not paypal_configured():
        raise PayPalError(
            "PayPal is not configured. Add PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET to backend/.env "
            "(Sandbox credentials from developer.paypal.com). See README.md → PayPal Sandbox setup.",
            status_code=503,
        )

    auth = base64.b64encode(f"{PAYPAL_CLIENT_ID}:{PAYPAL_CLIENT_SECRET}".encode()).decode()
    try:
        resp = await client.post(
            f"{PAYPAL_BASE_URL}/v1/oauth2/token",
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        raise PayPalError(
            f"Could not reach PayPal ({PAYPAL_BASE_URL}). Check your internet connection and "
            "PAYPAL_BASE_URL in backend/.env.",
            status_code=502,
            detail=str(exc),
        ) from exc

    if resp.status_code != 200:
        raise PayPalError(
            "PayPal rejected the API credentials (OAuth token request failed). Verify "
            "PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET for the Sandbox environment.",
            status_code=502,
            detail=f"HTTP {resp.status_code}: {resp.text[:500]}",
        )

    data = resp.json()
    _access_token_cache["token"] = data["access_token"]
    _access_token_cache["expires_at"] = time.time() + int(data.get("expires_in", 3000))
    return data["access_token"]


def _error_body(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        parts = [f"{data.get('name', 'ERROR')} (HTTP {resp.status_code})"]
        for d in data.get("details", [])[:3]:
            if isinstance(d, dict) and (d.get("issue") or d.get("description")):
                parts.append(f"{d.get('issue', '')}: {d.get('description', '')}".strip(": "))
        if data.get("message") and data["message"] not in parts[0]:
            parts.append(data["message"])
        return " | ".join(p for p in parts if p)
    except Exception:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"


_INR_NOTE = (
    "PayPal does not support the Indian Rupee (INR): INR is not on PayPal's supported "
    "REST API currency list (developer.paypal.com/api/nvp-soap/currency-codes), and PayPal "
    "discontinued domestic payments in India on 1 April 2021. PayPilot will never silently "
    "convert your INR total to another currency. To complete a PayPal Sandbox demo you can "
    "explicitly set PAYPAL_CURRENCY=USD (or another supported currency) in backend/.env: the "
    "catalogue, cart and AI stay in INR, and the PayPal Sandbox order is created for the same "
    "numeric total in that currency (Sandbox funds only — no real money, no real conversion). "
    "For real INR payments, integrate an Indian gateway such as Razorpay, Cashfree or PayU. "
    "See README.md → 'Currency note (INR)'."
)


def _currency_rejection_message(resp: httpx.Response) -> Optional[str]:
    """Detect PayPal's unsupported-currency rejection and explain it clearly."""
    body = resp.text.lower()
    if "currency" in body and any(k in body for k in ("not supported", "unsupported", "invalid", "not a supported")):
        return (
            f"PayPal rejected the order because {PAYPAL_CURRENCY} is not a supported PayPal currency. "
            f"PayPal said: {_error_body(resp)}. {_INR_NOTE}"
        )
    return None


# ---------------------------------------------------------------------------
# Orders v2 operations
# ---------------------------------------------------------------------------

async def create_order(
    amount: float,
    currency: str,
    description: str,
    return_url: str,
    cancel_url: str,
) -> Dict[str, Any]:
    """Create a PayPal order; returns {'paypal_order_id', 'approval_url'}.

    Raises PayPalError with a user-safe message on any failure.
    """
    async with httpx.AsyncClient() as client:
        token = await _get_access_token(client)
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": "paypilot-store",
                    "description": description[:127],
                    "amount": {"currency_code": currency, "value": paypal_amount(amount)},
                }
            ],
            "application_context": {
                "brand_name": "PayPilot",
                "locale": "en-IN",
                "user_action": "CONTINUE",
                "shipping_preference": "NO_SHIPPING",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        try:
            resp = await client.post(
                f"{PAYPAL_BASE_URL}/v2/checkout/orders",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
                timeout=25.0,
            )
        except httpx.HTTPError as exc:
            raise PayPalError(
                f"Network error while creating the PayPal order: {exc}",
                status_code=502,
                detail=str(exc),
            ) from exc

        if resp.status_code not in (200, 201):
            currency_msg = _currency_rejection_message(resp)
            raise PayPalError(
                currency_msg
                or f"PayPal could not create the order. PayPal said: {_error_body(resp)}",
                status_code=502,
                detail=f"create order failed: {resp.text[:800]}",
            )

        data = resp.json()
        approval_url = next(
            (lnk["href"] for lnk in data.get("links", []) if lnk.get("rel") == "approve"), None
        )
        if not approval_url or not data.get("id"):
            raise PayPalError(
                "PayPal's response did not contain an approval link.",
                status_code=502,
                detail=f"unexpected create response: {resp.text[:500]}",
            )
        return {"paypal_order_id": data["id"], "approval_url": approval_url}


async def get_order(paypal_order_id: str) -> Dict[str, Any]:
    """Fetch the order's current state from PayPal."""
    async with httpx.AsyncClient() as client:
        token = await _get_access_token(client)
        try:
            resp = await client.get(
                f"{PAYPAL_BASE_URL}/v2/checkout/orders/{paypal_order_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            raise PayPalError(f"Network error while checking the PayPal order: {exc}") from exc
        if resp.status_code != 200:
            raise PayPalError(
                f"Could not find PayPal order '{paypal_order_id}'. {_error_body(resp)}",
                status_code=404 if resp.status_code == 404 else 502,
                detail=resp.text[:500],
            )
        return resp.json()


async def capture_order(paypal_order_id: str) -> Dict[str, Any]:
    """Capture funds for an APPROVED order; returns the full order JSON."""
    async with httpx.AsyncClient() as client:
        token = await _get_access_token(client)
        try:
            resp = await client.post(
                f"{PAYPAL_BASE_URL}/v2/checkout/orders/{paypal_order_id}/capture",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "PayPal-Request-Id": f"paypilot-capture-{paypal_order_id}",
                },
                json={},
                timeout=25.0,
            )
        except httpx.HTTPError as exc:
            raise PayPalError(f"Network error while capturing the PayPal order: {exc}") from exc

        if resp.status_code not in (200, 201):
            raise PayPalError(
                f"PayPal capture failed. {_error_body(resp)}",
                status_code=502,
                detail=f"capture failed: {resp.text[:800]}",
            )
        return resp.json()


def extract_capture(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull the capture resource out of an order/capture response."""
    try:
        captures: List[Dict[str, Any]] = result["purchase_units"][0]["payments"]["captures"]
        return captures[0] if captures else None
    except (KeyError, IndexError, TypeError):
        return None


def verify_capture(
    result: Dict[str, Any], expected_amount: float, expected_currency: str
) -> Dict[str, Any]:
    """Verify status, amount and currency. Returns {ok, reason, capture}.

    This is the security check that decides whether we show success:
    the payment counts as complete ONLY if the capture status is COMPLETED
    and both amount and currency match the server-side order record.
    """
    if result.get("status") != "COMPLETED":
        return {"ok": False, "reason": f"PayPal order status is '{result.get('status')}', not COMPLETED.", "capture": None}

    capture = extract_capture(result)
    if not capture:
        return {"ok": False, "reason": "PayPal response contained no capture resource.", "capture": None}
    if capture.get("status") != "COMPLETED":
        return {"ok": False, "reason": f"Capture status is '{capture.get('status')}', expected COMPLETED.", "capture": None}

    try:
        got_amount = Decimal(str(capture["amount"]["value"]))
        want_amount = Decimal(str(expected_amount)).quantize(Decimal("0.01"))
    except (KeyError, InvalidOperation) as exc:
        return {"ok": False, "reason": f"Malformed amount in PayPal response ({exc}).", "capture": capture}

    got_currency = str(capture.get("amount", {}).get("currency_code", ""))
    if got_amount != want_amount:
        return {
            "ok": False,
            "reason": (
                f"Amount mismatch: PayPal captured {got_currency} {got_amount}, "
                f"but the server-verified order total is {expected_currency} {want_amount}. "
                "The transaction was rejected."
            ),
            "capture": capture,
        }
    if got_currency != expected_currency:
        return {
            "ok": False,
            "reason": (
                f"Currency mismatch: PayPal captured {got_currency}, expected {expected_currency}. "
                "The transaction was rejected."
            ),
            "capture": capture,
        }
    return {"ok": True, "reason": "", "capture": capture}


def is_already_captured_error(error: PayPalError) -> bool:
    return "ALREADY_CAPTURED" in (error.detail or "").upper() or "ORDER_ALREADY_CAPTURED" in (error.detail or "").upper()
