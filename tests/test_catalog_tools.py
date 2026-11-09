"""
test_catalog_tools.py — unit tests for the catalogue tools (no server needed).

Run from the tests/ directory:  python test_catalog_tools.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import catalog  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {extra}")


print("== format_inr (Indian numbering) ==")
check("999 -> 999", catalog.format_inr(999) == "999")
check("12,499", catalog.format_inr(12499) == "12,499")
check("1,25,000", catalog.format_inr(125000) == "1,25,000")
check("60,000", catalog.format_inr(60000) == "60,000")
check("₹ display", catalog.price_display(catalog.PRODUCT_INDEX["PP-006"]) == "₹58,990")

print("== budget extraction ==")
check("under 60k -> 60000", catalog._extract_budget("laptop under 60k") == 60000)
check("₹25,000 -> 25000", catalog._extract_budget("phones under ₹25,000") == 25000)
check("60000 -> 60000", catalog._extract_budget("budget 60000") == 60000)
check("1.5 lakh -> 150000", catalog._extract_budget("under 1.5 lakh") == 150000)
check("under 60 -> 60000", catalog._extract_budget("laptop under 60") == 60000)

print("== search_catalogue ==")
r = catalog.search_catalogue("laptop for programming under ₹60,000")
check("laptops under 60k: has results", r["count"] >= 2)
check("all are laptops", all(p["category"] == "Laptops" for p in r["products"]), str([p["name"] for p in r["products"]]))
check("all within budget", all(p["price_inr"] <= 60000 for p in r["products"]))
check("HP Pavilion present", any(p["id"] == "PP-006" for p in r["products"]))

r = catalog.search_catalogue("wireless headphones")
check("headphones found", any("XM5" in p["name"] for p in r["products"]) or any("Airdopes" in p["name"] for p in r["products"]))

r = catalog.search_catalogue("", category="Smartphones", limit=10)
check("category filter", r["count"] == 10 and all(p["category"] == "Smartphones" for p in r["products"]))

r = catalog.search_catalogue("something for students")
check("student search finds budget/student items", r["count"] > 0 and all("students" in " ".join(p["best_for"]) or p["price_inr"] < 10000 for p in r["products"]))

r = catalog.search_catalogue("gucci handbag")
check("nonexistent item: no results", r["count"] == 0)

r = catalog.search_catalogue("smartphones under ₹25,000")
check("phones under 25k", r["count"] >= 1 and all(p["price_inr"] <= 25000 for p in r["products"]))

print("== compare_products ==")
c = catalog.compare_products(["PP-001", "PP-003"])
check("compare two phones", c.get("count") == 2)
check("cheapest flagged", any("Lowest price" in a for p in c["products"] for a in p["advantages"]))
check("recommendation present", "recommendation" in c)
c = catalog.compare_products(["PP-005", "PP-006"], budget=60000)
check("budget respected in compare", all("Fits the ₹60,000 budget" in p["advantages"] for p in c["products"]))
c = catalog.compare_products(["PP-999", "made-up thing"])
check("bad refs -> error", "error" in c)

print("== get_product_details ==")
d = catalog.get_product_details("PP-008")
check("details by id", d["product"]["name"] == "Apple MacBook Air M2")
d = catalog.get_product_details("MacBook Air")
check("details by name", d["product"]["id"] == "PP-008")
d = catalog.get_product_details("PP-999")
check("unknown -> honest error", "error" in d and "not available" in d["error"])

print("== resolve ==")
check("bare id PP-1", catalog._resolve_product("PP-1")["id"] == "PP-001")
check("fuzzy name", catalog._resolve_product("sony headphones xm5")["id"] == "PP-010")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
