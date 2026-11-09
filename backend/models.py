"""
models.py — Pydantic request/response schemas for the PayPilot API.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class CartItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=40)
    quantity: int = Field(ge=1, le=99)


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: List[CartItem] = Field(min_length=1, max_length=50)


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paypal_order_id: str = Field(min_length=1, max_length=64)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paypal_order_id: str = Field(min_length=1, max_length=64)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    history: List[ChatMessage] = Field(default_factory=list, max_length=20)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class ProductOut(BaseModel):
    id: str
    name: str
    category: str
    price_inr: int
    price_display: str
    currency: str
    short_description: str
    description: Optional[str] = None
    specs: Optional[Dict[str, Any]] = None
    key_specs: Optional[Dict[str, Any]] = None
    rating: float
    num_reviews: int
    stock: int
    best_for: List[str]
    featured: Optional[bool] = None
    image: str


class AgentChatResponse(BaseModel):
    reply: str
    products: List[ProductOut] = Field(default_factory=list)
    tool_calls: List[str] = Field(default_factory=list)


class OrderCreatedResponse(BaseModel):
    order_id: str
    paypal_order_id: str
    approval_url: str
    total_amount: float
    total_display: str
    currency: str
    status: str = "CREATED"


class OrderItemOut(BaseModel):
    product_id: str
    product_name: str
    unit_price: float
    quantity: int
    line_total: float


class OrderOut(BaseModel):
    order_id: str
    total_amount: float
    total_display: str
    currency: str
    payment_status: str
    paypal_order_id: Optional[str] = None
    capture_id: Optional[str] = None
    payer_email: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: str
    items: List[OrderItemOut] = Field(default_factory=list)


class CaptureResultResponse(BaseModel):
    success: bool
    order: Optional[OrderOut] = None
    message: str
    already_completed: bool = False


class HealthResponse(BaseModel):
    status: str
    service: str
    time: str
    currency: str
    openai_configured: bool
    paypal_configured: bool
    model: Optional[str] = None
