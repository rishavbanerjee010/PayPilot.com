"""
agent.py — PayPilot AI shopping agent.

Implementation notes:
- Uses the OpenAI **Responses API** (client.responses.create) with function
  calling. The API key lives ONLY in this backend process.
- Three real tools backed by the trusted catalogue (catalog.py):
    search_catalogue, compare_products, get_product_details
- The agent loop is bounded (MAX_TOOL_ROUNDS) and every tool execution is
  wrapped in try/except, so one bad tool call can never hang the request.
- Product cards in chat: the model is instructed to end its final answer
  with a line `RECOMMENDED_PRODUCT_IDS: PP-001, PP-002`. We parse that line,
  strip it from the displayed text and hydrate the IDs against the REAL
  catalogue — so even if the model hallucinated an ID, users can only ever
  see genuine catalogue products with genuine prices.
- If no OPENAI_API_KEY is configured, chat returns HTTP 503 with a clear
  message (we never fake AI replies on the server or in the browser).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

import catalog

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip() or None

MAX_TOOL_ROUNDS = 5
MAX_HISTORY_MESSAGES = 10

SYSTEM_PROMPT = f"""You are PayPilot, the friendly AI shopping assistant inside the PayPilot demo store (an India-focused e-commerce demo).

Core rules:
1. All prices are in Indian Rupees (INR, symbol \u20b9). Budgets like "under \u20b960,000", "under 60k" or "within 50k" always mean INR. If the user quotes a budget in a foreign currency (e.g. "under $800"), convert it approximately to INR (roughly \u20b980-90 per US dollar), tell the user you converted it, and search with the INR value.
2. You MUST use your tools (search_catalogue, compare_products, get_product_details) before answering anything about products, prices, specs, stock or availability. NEVER invent or guess a product, price, specification, rating or availability. If the tools return nothing, say so honestly and — only if the tools suggest real alternatives — mention those.
3. When the user asks for recommendations, search the catalogue with their budget and needs, then explain WHY each product fits (price, specs, use case).Recommend ONLY products that genuinely match the user's stated need — never pad the list to make it look fuller. If a tool result does not really fit (e.g. formal shoes when they asked for running shoes, or a wired mouse when they asked for wireless), leave it out of the answer entirely. If only one product truly fits, recommend just that one; if none truly fit, say so honestly instead of stretching. NEVER claim an unsuitable product suits the purpose (e.g. never present formal shoes as usable for running, and never invent qualities a product does not have). Mention prices with the \u20b9 symbol and Indian number formatting (e.g. \u20b921,499).
4. When the user asks to compare products, call compare_products and present a concise comparison: prices, key spec differences, advantages, disadvantages, best use cases, and an overall recommendation.
5. Use the conversation history for follow-up questions ("what about something cheaper?", "compare it with the MacBook").
6. You are a shopping assistant ONLY. You cannot place orders, reserve items, or see payment/order status. Never claim that a purchase or payment has succeeded or will succeed — checkout and payments are handled by the app itself.
7. If asked something unrelated to shopping, briefly redirect to shopping help.

Product cards (important for the UI):
- When your final answer recommends or compares specific products, end your final message with a LAST line in exactly this format:
RECOMMENDED_PRODUCT_IDS: PP-001, PP-014
- Use only real product IDs that appeared in your tool results. If you are not recommending any product, omit the line entirely.
- Never put the IDs anywhere else in the message; the app hides this line from the user.

Style: warm, concise, structured. Use short paragraphs or tight bullet lists. Reply in the user's language (default English)."""

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI Responses API "function" tool format)
# ---------------------------------------------------------------------------

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_catalogue",
        "description": (
            "Search the real PayPilot product catalogue (prices in INR). Use this for any "
            "recommendation, budget question ('laptop under 60000'), category browse, or "
            "keyword search. Returns only products that actually exist, with real prices."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text shopping query, e.g. 'laptop for programming under 60000' or 'wireless headphones'. Include budget words like 'under 25k'.",
                },
                "category": {
                    "type": "string",
                    "enum": catalog.CATEGORIES,
                    "description": "Optional category filter.",
                },
                "min_price": {"type": "number", "description": "Optional minimum price in INR."},
                "max_price": {"type": "number", "description": "Optional maximum price in INR (also inferred from 'under ...' in the query)."},
                "limit": {"type": "number", "description": "Max products to return, 1-12. Default 6."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "compare_products",
        "description": (
            "Compare 2-3 products from the catalogue side by side (real prices, specs, "
            "advantages, disadvantages, best use cases, recommendation). Pass product IDs "
            "or exact product names. Optionally pass the user's budget in INR."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 3,
                    "description": "Product IDs (e.g. PP-001) or exact product names to compare.",
                },
                "budget": {"type": "number", "description": "Optional budget in INR to judge value against."},
            },
            "required": ["product_ids"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_product_details",
        "description": (
            "Get the full, real record of ONE product (description, all specs, price, stock, "
            "rating). Use when the user asks about a specific product or mentions one by name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "Product ID (e.g. PP-006) or exact product name.",
                },
            },
            "required": ["product_id"],
            "additionalProperties": False,
        },
    },
]

# ---------------------------------------------------------------------------
# Safe tool execution
# ---------------------------------------------------------------------------


def _safe_search(args: Dict[str, Any]) -> Dict[str, Any]:
    return catalog.search_catalogue(
        query=args.get("query"),
        category=args.get("category"),
        min_price=args.get("min_price"),
        max_price=args.get("max_price"),
        limit=args.get("limit", 6),
    )


def _safe_compare(args: Dict[str, Any]) -> Dict[str, Any]:
    ids = args.get("product_ids") or []
    if not isinstance(ids, list) or len(ids) < 2:
        return {"error": "compare_products requires a list of at least 2 product IDs or names."}
    return catalog.compare_products(ids, budget=args.get("budget"))


def _safe_details(args: Dict[str, Any]) -> Dict[str, Any]:
    ref = args.get("product_id") or ""
    if not str(ref).strip():
        return {"error": "get_product_details requires a product_id or product name."}
    return catalog.get_product_details(str(ref))


TOOL_IMPLEMENTATIONS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "search_catalogue": _safe_search,
    "compare_products": _safe_compare,
    "get_product_details": _safe_details,
}


class AgentNotConfigured(Exception):
    """Raised when no OPENAI_API_KEY is present (HTTP 503 upstream)."""


class AgentError(Exception):
    """Any other agent failure (HTTP 502 upstream)."""


# ---------------------------------------------------------------------------
# Responses API loop
# ---------------------------------------------------------------------------

def _client():
    from openai import OpenAI

    if not OPENAI_API_KEY:
        raise AgentNotConfigured(
            "The AI assistant is not configured on this server. Add OPENAI_API_KEY (and optionally "
            "OPENAI_MODEL) to backend/.env and restart uvicorn. See README.md → OpenAI setup."
        )
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL, timeout=60.0, max_retries=1)


def _parse_marker_line(text: str) -> tuple[str, List[str]]:
    """Split 'RECOMMENDED_PRODUCT_IDS: ...' out of the final answer."""
    ids: List[str] = []
    if not text:
        return (text or "", ids)
    lines = text.rstrip().splitlines()
    if lines and lines[-1].strip().upper().startswith("RECOMMENDED_PRODUCT_IDS:"):
        raw = lines[-1].split(":", 1)[1]
        for tok in raw.replace(";", ",").split(","):
            tok = tok.strip().upper()
            if tok and tok not in ids:
                ids.append(tok)
        lines = lines[:-1]
    return "\n".join(lines).strip(), ids


def run_agent(message: str, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Run the shopping agent. Returns {reply, products, tool_calls}.

    Raises AgentNotConfigured (503) or AgentError (502).
    """
    client = _client()

    # Build the input: prior conversation (text only) + current user message.
    input_items: List[Dict[str, Any]] = []
    for msg in (history or [])[-MAX_HISTORY_MESSAGES:]:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            input_items.append({"role": role, "content": content})
    input_items.append({"role": "user", "content": message.strip()})

    tool_calls_used: List[str] = []

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            response = client.responses.create(
                model=OPENAI_MODEL,
                instructions=SYSTEM_PROMPT,
                input=input_items,
                tools=TOOLS,
                max_output_tokens=1200,
            )

            function_calls = [
                item for item in (response.output or []) if getattr(item, "type", None) == "function_call"
            ]

            if not function_calls:
                final_text = (response.output_text or "").strip()
                if not final_text:
                    # Model produced nothing usable (rare); give an honest fallback.
                    final_text = (
                        "I couldn't generate a proper answer just now. Could you rephrase your question? "
                        "You can also browse the catalogue in the Explore tab."
                    )
                clean_reply, recommended_ids = _parse_marker_line(final_text)
                products = [
                    catalog.product_full(catalog.get_product(pid))
                    for pid in recommended_ids
                    if catalog.get_product(pid)  # only REAL catalogue products reach the UI
                ]
                return {"reply": clean_reply, "products": products, "tool_calls": tool_calls_used}

            # Execute every requested tool and feed the results back.
            for fc in function_calls:
                name = getattr(fc, "name", "")
                if name not in TOOL_IMPLEMENTATIONS:
                    result: Dict[str, Any] = {
                        "error": f"Unknown tool '{name}'. Available tools: {', '.join(TOOL_IMPLEMENTATIONS)}."
                    }
                else:
                    try:
                        args = json.loads(getattr(fc, "arguments", "") or "{}")
                        if not isinstance(args, dict):
                            raise ValueError("arguments must be a JSON object")
                        result = TOOL_IMPLEMENTATIONS[name](args)
                    except Exception as exc:  # never let a tool crash the loop
                        result = {"error": f"Tool '{name}' failed: {exc}"}
                tool_calls_used.append(name)
                # Echo the function_call item + its output back as conversation state.
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": getattr(fc, "call_id", ""),
                        "name": name,
                        "arguments": getattr(fc, "arguments", "") or "{}",
                    }
                )
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": getattr(fc, "call_id", ""),
                        "output": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        # Loop budget exhausted without a final answer.
        clean_reply, recommended_ids = _parse_marker_line(
            "I did a lot of digging in the catalogue but ran out of steps before finishing. "
            "Could you narrow the question down a little?"
        )
        return {"reply": clean_reply, "products": [], "tool_calls": tool_calls_used}

    except AgentNotConfigured:
        raise
    except Exception as exc:  # openai.APIError, timeouts, etc.
        raise AgentError(
            f"The AI service could not be reached or returned an error: {exc}. "
            "Check OPENAI_API_KEY / OPENAI_MODEL in backend/.env and your internet connection."
        ) from exc
