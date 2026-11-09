"""
database.py — SQLite persistence for PayPilot orders and payment transactions.

Design notes:
- The product catalogue lives in catalog.py (trusted, version-controlled);
  SQLite stores orders, order items and the payment event log.
- Money is stored as REAL rupees (catalogue prices are whole rupees, so
  float precision is never an issue for this demo scale).
- There is NO user authentication: a single demo user ("demo_user") owns
  every order. This is documented in the README.
- Payment status values: CREATED, APPROVED, COMPLETED, FAILED, CANCELLED.
- No secrets (PayPal/OpenAI keys) are ever written to this database.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get("PAYPILOT_DB_PATH", os.path.join(os.path.dirname(__file__), "paypilot.db"))

DEMO_USER = "demo_user"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id         TEXT UNIQUE NOT NULL,          -- internal id, e.g. PP-8F3K9A2B
    user_id          TEXT NOT NULL DEFAULT 'demo_user',
    total_amount     REAL NOT NULL,                 -- server-calculated, rupees
    currency         TEXT NOT NULL DEFAULT 'INR',
    paypal_order_id  TEXT UNIQUE,
    payment_status   TEXT NOT NULL DEFAULT 'CREATED',
    capture_id       TEXT,
    payer_email      TEXT,
    failure_reason   TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     TEXT NOT NULL REFERENCES orders(order_id),
    product_id   TEXT NOT NULL,
    product_name TEXT NOT NULL,
    unit_price   REAL NOT NULL,
    quantity     INTEGER NOT NULL,
    line_total   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        TEXT NOT NULL,
    paypal_order_id TEXT,
    event           TEXT NOT NULL,   -- ORDER_CREATED / CREATE_FAILED / CAPTURE_SUCCEEDED / ...
    detail          TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_txn_order ON payment_transactions(order_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def create_order(order_id: str, items: List[Dict[str, Any]], total: float, currency: str) -> None:
    now = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO orders (order_id, user_id, total_amount, currency, payment_status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'CREATED', ?, ?)",
            (order_id, DEMO_USER, total, currency, now, now),
        )
        conn.executemany(
            "INSERT INTO order_items (order_id, product_id, product_name, unit_price, quantity, line_total)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    order_id,
                    it["product_id"],
                    it["product_name"],
                    it["unit_price"],
                    it["quantity"],
                    it["line_total"],
                )
                for it in items
            ],
        )


def get_order_by_internal_id(order_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return _order_with_items(conn, row)


def get_order_by_paypal_id(paypal_order_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE paypal_order_id = ?", (paypal_order_id,)
        ).fetchone()
        return _order_with_items(conn, row)


def _order_with_items(conn: sqlite3.Connection, row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    order = dict(row)
    items = conn.execute(
        "SELECT product_id, product_name, unit_price, quantity, line_total FROM order_items"
        " WHERE order_id = ? ORDER BY id",
        (row["order_id"],),
    ).fetchall()
    order["items"] = [dict(i) for i in items]
    return order


def list_orders(user_id: str = DEMO_USER, limit: int = 50) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        result = []
        for row in rows:
            order = dict(row)
            items = conn.execute(
                "SELECT product_id, product_name, unit_price, quantity, line_total FROM order_items"
                " WHERE order_id = ? ORDER BY id",
                (row["order_id"],),
            ).fetchall()
            order["items"] = [dict(i) for i in items]
            result.append(order)
        return result


# ---------------------------------------------------------------------------
# Status updates
# ---------------------------------------------------------------------------

def attach_paypal_order(order_id: str, paypal_order_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET paypal_order_id = ?, payment_status = 'CREATED', updated_at = ?"
            " WHERE order_id = ?",
            (paypal_order_id, _now(), order_id),
        )


def mark_order_failed(order_id: str, reason: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET payment_status = 'FAILED', failure_reason = ?, updated_at = ?"
            " WHERE order_id = ? AND payment_status NOT IN ('COMPLETED')",
            (reason[:500], _now(), order_id),
        )


def mark_order_cancelled(order_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET payment_status = 'CANCELLED', updated_at = ?"
            " WHERE order_id = ? AND payment_status IN ('CREATED', 'APPROVED')",
            (_now(), order_id),
        )


def mark_order_completed(order_id: str, capture_id: str, payer_email: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET payment_status = 'COMPLETED', capture_id = ?, payer_email = ?,"
            " failure_reason = NULL, updated_at = ? WHERE order_id = ?",
            (capture_id, payer_email, _now(), order_id),
        )


def mark_order_approved(order_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET payment_status = 'APPROVED', updated_at = ?"
            " WHERE order_id = ? AND payment_status = 'CREATED'",
            (_now(), order_id),
        )


# ---------------------------------------------------------------------------
# Payment event log
# ---------------------------------------------------------------------------

def log_payment_event(order_id: str, event: str, detail: str = "", paypal_order_id: Optional[str] = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO payment_transactions (order_id, paypal_order_id, event, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (order_id, paypal_order_id, event, (detail or "")[:1000], _now()),
        )
