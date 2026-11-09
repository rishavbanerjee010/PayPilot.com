"""
openai_mock_server.py — a local test double for the OpenAI Responses API.

It implements POST /v1/responses with REAL function-calling behaviour:
  round 1  -> chooses a tool call based on the user's message
  round 2  -> reads the function_call_output (real catalogue data!) and either
              chains a second tool (e.g. compare after search) or writes a
              final answer that cites actual products and ends with the
              RECOMMENDED_PRODUCT_IDS line, exactly like the system prompt asks.

This lets you verify PayPilot's agent loop (agent.py) end-to-end without an
OpenAI key. The application code is unchanged — you only point
OPENAI_BASE_URL at this server.

Run:  python openai_mock_server.py   (listens on http://127.0.0.1:9099)
"""
from __future__ import annotations

import json
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

MOCK_PORT = int(os.environ.get("OPENAI_MOCK_PORT", "9099"))

app = FastAPI(title="OpenAI Responses API mock")


def _response_id():
    return "resp_" + uuid.uuid4().hex[:24]


def _function_call_item(call_id: str, name: str, args: dict) -> dict:
    return {
        "type": "function_call",
        "id": "fc_" + uuid.uuid4().hex[:12],
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(args),
        "status": "completed",
    }


def _message_item(text: str) -> dict:
    return {
        "type": "message",
        "id": "msg_" + uuid.uuid4().hex[:12],
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _wrap(output: list) -> JSONResponse:
    return JSONResponse(
        {
            "id": _response_id(),
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "model": "mock-gpt",
            "output": output,
            "output_text": "\n".join(
                c["text"]
                for item in output
                if item["type"] == "message"
                for c in item["content"]
            ),
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
            "error": None,
            "incomplete_details": None,
            "instructions": None,
            "metadata": {},
            "temperature": 1.0,
            "top_p": 1.0,
            "max_output_tokens": None,
            "previous_response_id": None,
            "reasoning": None,
            "store": True,
            "text": None,
            "truncation": "disabled",
            "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20, "output_tokens_details": None},
        }
    )


def _extract_product_names(products: list) -> list:
    return [p["name"] for p in products]


def _fmt_price(p: dict) -> str:
    return p.get("price_display", f"₹{p.get('price_inr')}")


# ---------------------------------------------------------------------------
# Tool-choice + final-answer logic (a rule-based "mini-LLM")
# ---------------------------------------------------------------------------

def decide_first_tool(user_text: str):
    t = user_text.lower()
    # convert foreign-currency budgets to INR the way the system prompt tells the
    # real model to (approximate, and stated to the user)
    import re

    m = re.search(r"\$\s*(\d[\d,]*(?:\.\d+)?)", user_text)
    query = user_text
    prefix = ""
    if m:
        inr = round(float(m.group(1).replace(",", "")) * 85 / 1000) * 1000
        query = f"{user_text} under {inr} rupees"
        prefix = f"(I read your ${m.group(1)} budget as roughly \u20b9{inr:,}.)\n\n"

    if any(k in t for k in ("compare", " vs ", "difference between", "better:")):
        return "search_catalogue", {"query": query}          # search first, compare next round
    if "alternative" in t or "instead of" in t:
        return "search_catalogue", {"query": query}
    # Named product? -> details tool (a few catalogue names we can detect cheaply)
    known = [
        "macbook", "pixel 8a", "oneplus 12r", "hp pavilion", "xm5", "wh-1000",
        "mx master", "galaxy a35", "redmi note", "tuf", "ideapad", "echo dot",
        "watch se", "flip 6", "keychron", "airdopes", "voyager",
    ]
    if any(k in t for k in known) and not any(k in t for k in ("under", "below", "budget", "recommend", "find", "suggest", "cheap", "alternative")):
        return "get_product_details", {"product_id": user_text.strip()}
    return "search_catalogue", {"query": query}


def pick_compare_pair(products: list) -> list:
    """Two cheapest products from the DOMINANT category of the search results."""
    from collections import Counter

    cats = Counter(p["category"] for p in products)
    best = max(
        cats,
        key=lambda c: (
            cats[c],
            -min(p["price_inr"] for p in products if p["category"] == c),
        ),
    )
    in_cat = sorted((p for p in products if p["category"] == best), key=lambda p: p["price_inr"])
    return in_cat[:2]


def build_final_answer(user_text: str, last_tool: str, result: dict, exclude_ids: set | None = None) -> str:
    exclude_ids = exclude_ids or set()
    t = user_text.lower()
    wants_compare = any(k in t for k in ("compare", " vs ", "difference between", "better:"))

    # Comparison tool result -> comparison summary
    if last_tool == "compare_products" and result.get("products"):
        lines = []
        for p in result["products"]:
            lines.append(
                f"• {p['name']} — {p['price_display']}, rated {p['rating']}/5. "
                f"Advantages: {'; '.join(p['advantages'][:2])}. "
                f"Watch out: {'; '.join(p['disadvantages'][:1])}."
            )
        ids = ", ".join(p["id"] for p in result["products"])
        return (
            "Here's a side-by-side look at the two:\n\n"
            + "\n".join(lines)
            + f"\n\n{result.get('recommendation', '')}"
            + f"\n\nRECOMMENDED_PRODUCT_IDS: {ids}"
        )

    # Details tool result -> product summary
    if last_tool == "get_product_details" and result.get("product"):
        p = result["product"]
        specs = "; ".join(f"{k}: {v}" for k, v in list(p.get("specs", {}).items())[:4])
        return (
            f"{p['name']} ({p['category']}) costs {p['price_display']} and is rated "
            f"{p['rating']}/5 from {p['num_reviews']:,} reviews. Key specs — {specs}. "
            f"{p['short_description']} It's a strong match for {', '.join(p['best_for'])}."
            f"\n\nRECOMMENDED_PRODUCT_IDS: {p['id']}"
        )

    # Search result -> recommendation list (or honest no-match)
    products = [p for p in (result.get("products") or []) if p["id"] not in exclude_ids]
    if not products:
        if result.get("error"):
            return result["error"]
        if exclude_ids:
            return (
                "I searched the catalogue, but I couldn't find a different product in "
                "that category right now — the catalogue is quite focused. Ask me for "
                "another category or budget and I'll find real options."
            )
        return (
            "I searched the PayPilot catalogue and, honestly, nothing matches that request. "
            "I'd rather tell you that than invent a product! Try asking for laptops, smartphones, "
            "audio, accessories, fashion or home items — or give me a ₹ budget and a use case, "
            "and I'll find the closest real matches."
        )
    lines = []
    for p in products[:3]:
        lines.append(f"• {p['name']} — {_fmt_price(p)}, rated {p['rating']}/5. {p['short_description']}")
    ids = ", ".join(p["id"] for p in products[:3])
    if wants_compare:
        return ""
    intro = "Great question! Based on the PayPilot catalogue (all prices in ₹), here's what fits:"
    if exclude_ids:
        intro = "Here are some real alternatives from the same category:"
    return (
        f"{intro}\n\n"
        + "\n".join(lines)
        + "\n\nWant me to compare any two of these, or look at a different budget?"
        + f"\n\nRECOMMENDED_PRODUCT_IDS: {ids}"
    )


# ---------------------------------------------------------------------------
# The Responses API endpoint
# ---------------------------------------------------------------------------

@app.post("/v1/responses")
async def create_response(request: Request):
    body = await request.json()
    input_items = [i for i in (body.get("input") or []) if isinstance(i, dict)]

    user_msgs = [i for i in input_items if i.get("role") == "user"]
    user_text = user_msgs[-1]["content"] if user_msgs else ""

    function_calls = [i for i in input_items if i.get("type") == "function_call"]
    tool_outputs = [i for i in input_items if i.get("type") == "function_call_output"]

    # ---- round 1: no tool outputs yet -> emit a function_call ----
    if not tool_outputs:
        name, args = decide_first_tool(user_text)
        call_id = "call_" + uuid.uuid4().hex[:12]
        return _wrap([_function_call_item(call_id, name, args)])

    # ---- later rounds: use the real tool output ----
    last_call = function_calls[-1]
    last_tool = last_call.get("name", "")
    outputs = []
    for o in tool_outputs:
        try:
            outputs.append(json.loads(o.get("output") or "{}"))
        except json.JSONDecodeError:
            outputs.append({})
    result = outputs[-1]

    t = user_text.lower()
    wants_compare = any(k in t for k in ("compare", " vs ", "difference between", "better:"))
    wants_alt = "alternative" in t or "instead of" in t

    # Chain: comparison request -> compare the two cheapest in the dominant category
    if wants_compare and last_tool == "search_catalogue" and result.get("products"):
        pair = pick_compare_pair(result["products"])
        if len(pair) == 2:
            call_id = "call_" + uuid.uuid4().hex[:12]
            return _wrap([
                _function_call_item(call_id, "compare_products", {"product_ids": [pair[0]["id"], pair[1]["id"]]})
            ])

    # Chain: alternatives request -> after finding the named product, search its
    # category for other options, then answer while excluding the original ids.
    if wants_alt and last_tool == "search_catalogue" and len(outputs) == 1 and result.get("products"):
        category = result["products"][0].get("category", "")
        call_id = "call_" + uuid.uuid4().hex[:12]
        return _wrap([
            _function_call_item(call_id, "search_catalogue", {"query": "", "category": category, "limit": 6})
        ])

    exclude_ids = set()
    if wants_alt and outputs:
        exclude_ids = {p["id"] for o in outputs[:1] for p in (o.get("products") or [])}

    final = build_final_answer(user_text, last_tool, result, exclude_ids)
    if not final:
        final = "I compared the catalogue options above — tell me which one you'd like to explore."
    return _wrap([_message_item(final)])


if __name__ == "__main__":
    import uvicorn

    print(f"OpenAI Responses API mock listening on http://127.0.0.1:{MOCK_PORT}/v1/responses")
    uvicorn.run(app, host="127.0.0.1", port=MOCK_PORT, log_level="warning")
