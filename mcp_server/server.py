"""MCP server for Campus Customs.

Exposes read and write tools over the shop's working database so every agent
(Boss, Inventory, Accounting, Facilities, Customer Service) reads and changes
the same facts instead of guessing or keeping private state. No data is
invented here — every tool only returns or writes what is already modeled in
data/campus_customs_new.db, and every write enforces the shop's own rules
(no negative cash, vendors blocked by an unpaid invoice, etc.) at the tool
level so the rule holds even if a tool is called directly, outside an agent.
"""

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastmcp import FastMCP

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "campus_customs_new.db"

mcp = FastMCP("campus-customs")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _today(conn: sqlite3.Connection) -> date:
    row = conn.execute("SELECT date_today FROM desk").fetchone()
    return date.fromisoformat(row["date_today"])


def _add_month(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1)
    return d.replace(month=d.month + 1)


# ---------------------------------------------------------------------------
# Tickets — the shop's work queue (Boss)
# ---------------------------------------------------------------------------


@mcp.tool()
def get_today() -> dict:
    """Return the shop's "today" (desk.date_today), used for every overdue/due-soon check."""
    conn = _connect()
    today = _today(conn)
    conn.close()
    return {"date_today": today.isoformat()}


@mcp.tool()
def list_open_tickets() -> list[dict]:
    """List every ticket with status='open'. This is the board Boss triages first."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM tickets WHERE status = 'open' ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@mcp.tool()
def list_tickets() -> list[dict]:
    """List every ticket regardless of status. Used by the dashboard to show the whole board,
    not just what's still open — Boss itself uses list_open_tickets instead."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@mcp.tool()
def get_ticket(ticket_id: int) -> dict:
    """Fetch one ticket's full row by id, including its sku/size/qty/lease_id/invoice_id links."""
    conn = _connect()
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    conn.close()
    if row is None:
        return {"ticket_id": ticket_id, "found": False}
    return {**dict(row), "found": True}


@mcp.tool()
def update_ticket(
    ticket_id: int,
    status: Literal["open", "pending_human_approval", "resolved", "blocked"],
    notes: str,
) -> dict:
    """Update a ticket's status and notes. Reserved for Boss — this is the final call on a ticket.

    `notes` should summarize what each specialist found and why this status was chosen, so a
    human reading the ticket later understands the decision without replaying the whole chat.
    """
    conn = _connect()
    existing = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if existing is None:
        conn.close()
        return {"ticket_id": ticket_id, "found": False, "updated": False}
    conn.execute(
        "UPDATE tickets SET status = ?, notes = ? WHERE id = ?",
        (status, notes, ticket_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    conn.close()
    return {**dict(row), "found": True, "updated": True}


# ---------------------------------------------------------------------------
# Inventory (Inventory agent)
# ---------------------------------------------------------------------------


@mcp.tool()
def check_inventory(sku: str, size: str) -> dict:
    """Look up on-hand quantity for one SKU/size in the inventory table.

    Used for ticket 101 (customer order for CC-TEE-WHITE size S): this is
    how the agent confirms there is 0 units on hand before deciding the
    order needs a restock rather than a simple fulfillment.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
        (sku, size),
    ).fetchone()
    conn.close()
    if row is None:
        return {"sku": sku, "size": size, "qty": 0, "name": None, "location": None, "found": False}
    return {**dict(row), "found": True}


@mcp.tool()
def adjust_inventory(sku: str, size: str, delta: int, reason: str) -> dict:
    """Change on-hand qty for one SKU/size by `delta` (negative to fulfill/ship, positive to receive restock).

    Refuses if the resulting quantity would go below 0 — inventory can't go negative any more
    than cash can. Used to fulfill ticket 101 once stock is available, or to record a restock
    delivery arriving from a vendor.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT qty FROM inventory WHERE sku = ? AND size = ?", (sku, size)
    ).fetchone()
    if row is None:
        conn.close()
        return {"sku": sku, "size": size, "found": False, "applied": False, "reason": "no such sku/size"}
    new_qty = row["qty"] + delta
    if new_qty < 0:
        conn.close()
        return {
            "sku": sku,
            "size": size,
            "found": True,
            "applied": False,
            "reason": f"refused: qty would go negative ({row['qty']} + {delta} = {new_qty})",
        }
    conn.execute(
        "UPDATE inventory SET qty = ? WHERE sku = ? AND size = ?", (new_qty, sku, size)
    )
    conn.commit()
    conn.close()
    return {"sku": sku, "size": size, "found": True, "applied": True, "qty": new_qty, "reason": reason}


# ---------------------------------------------------------------------------
# Vendors & invoices (Inventory + Accounting)
# ---------------------------------------------------------------------------


@mcp.tool()
def list_vendors() -> list[dict]:
    """List every vendor with their specialty and lead_days. Used to match a SKU shortfall to the right vendor."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM vendors ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@mcp.tool()
def list_invoices(vendor_id: Optional[int] = None, status: Optional[str] = None) -> list[dict]:
    """List invoices, optionally filtered by vendor_id and/or status.

    Used two ways: Accounting calls it with no filters (or status='open') to watch for overdue
    bills against get_today(); Inventory calls it with a vendor_id before placing a new restock
    order, because a vendor with any open invoice here must be refused new business.
    """
    conn = _connect()
    query = "SELECT * FROM invoices WHERE 1=1"
    params: list = []
    if vendor_id is not None:
        query += " AND vendor_id = ?"
        params.append(vendor_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    rows = conn.execute(query + " ORDER BY id", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@mcp.tool()
def create_restock_order(
    vendor_id: int, sku: str, qty: int, unit_cost: float, description: str
) -> dict:
    """Place a restock order with a vendor by creating a new open invoice for it.

    Refuses if this vendor already has any open invoice — per shop rules, a vendor will not
    take new product orders while they have an unpaid bill outstanding. This is how ticket 103's
    (or 101's) shortfall gets a restock path once Accounting clears the vendor's old invoice.
    Due date defaults to 14 days out (standard trade-credit terms); delivery timing separately
    comes from vendors.lead_days.
    """
    conn = _connect()
    blocking = conn.execute(
        "SELECT * FROM invoices WHERE vendor_id = ? AND status = 'open'", (vendor_id,)
    ).fetchall()
    if blocking:
        conn.close()
        return {
            "vendor_id": vendor_id,
            "created": False,
            "reason": "refused: vendor has an open unpaid invoice and will not ship new product",
            "blocking_invoices": [dict(r) for r in blocking],
        }
    today = _today(conn)
    due_date = (today + timedelta(days=14)).isoformat()
    amount = round(qty * unit_cost, 2)
    cur = conn.execute(
        "INSERT INTO invoices (vendor_id, amount, due_date, status, description) VALUES (?, ?, ?, 'open', ?)",
        (vendor_id, amount, due_date, description),
    )
    conn.commit()
    new_id = cur.lastrowid
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return {"created": True, **dict(row)}


# ---------------------------------------------------------------------------
# Pricing (Accounting, for margin / discount checks)
# ---------------------------------------------------------------------------


@mcp.tool()
def get_pricing(sku: str) -> dict:
    """Look up unit cost and list price for one SKU.

    Used for ticket 103 (bulk hoodie discount request for CC-HOOD-NAVY):
    this is how the agent gets the cost floor (unit_cost) against the
    current list_price so it can tell whether a bulk discount still
    leaves a margin, instead of guessing at a discount percentage.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?",
        (sku,),
    ).fetchone()
    conn.close()
    if row is None:
        return {"sku": sku, "found": False, "unit_cost": None, "list_price": None}
    return {**dict(row), "found": True}


@mcp.tool()
def compute_bulk_quote(sku: str, qty: int, discount_pct: float) -> dict:
    """Compute the numbers for a bulk discount quote: no database write, pure calculation.

    Used for ticket 103: given the requested qty and a candidate discount_pct (e.g. 15 for 15%),
    returns per-unit price after discount, total revenue, total cost, and margin — including
    whether the discounted price would fall below unit_cost — so Accounting can approve, counter,
    or reject the Yale AI Club's bulk-hoodie ask with real numbers instead of a guess.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)
    ).fetchone()
    conn.close()
    if row is None:
        return {"sku": sku, "found": False}
    unit_cost = row["unit_cost"]
    list_price = row["list_price"]
    discounted_unit_price = round(list_price * (1 - discount_pct / 100), 2)
    total_revenue = round(discounted_unit_price * qty, 2)
    total_cost = round(unit_cost * qty, 2)
    margin_dollars = round(total_revenue - total_cost, 2)
    margin_pct = round((margin_dollars / total_revenue) * 100, 2) if total_revenue else 0.0
    return {
        "sku": sku,
        "found": True,
        "qty": qty,
        "discount_pct": discount_pct,
        "unit_cost": unit_cost,
        "list_price": list_price,
        "discounted_unit_price": discounted_unit_price,
        "total_revenue": total_revenue,
        "total_cost": total_cost,
        "margin_dollars": margin_dollars,
        "margin_pct": margin_pct,
        "below_cost": discounted_unit_price < unit_cost,
    }


# ---------------------------------------------------------------------------
# Leases (Facilities)
# ---------------------------------------------------------------------------


@mcp.tool()
def get_lease_info(lease_id: int) -> dict:
    """Look up a lease's rent and due date, plus the shop's current date.

    Used for ticket 102 (rent notice tied to lease_id 1): this is how the
    agent tells whether the Chapel Street lease's next_due is overdue or
    due soon, relative to desk.date_today, and what the rent amount is.
    """
    conn = _connect()
    lease = conn.execute(
        "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
        (lease_id,),
    ).fetchone()
    today = _today(conn)
    conn.close()
    if lease is None:
        return {"lease_id": lease_id, "found": False, "date_today": today.isoformat()}
    return {**dict(lease), "date_today": today.isoformat(), "found": True}


# ---------------------------------------------------------------------------
# Cash & payments — pay_invoice/pay_lease are not in any agent's toolset in
# backend/agents.py (ACCOUNTING_TOOLS deliberately omits them). No agent can
# call either one no matter what it decides; they're only ever called
# directly by the backend's POST /payments/approve route, after a human
# approves.
# ---------------------------------------------------------------------------


@mcp.tool()
def get_cash_balance() -> list[dict]:
    """List every cash account and its current balance. No revenue is modeled — balances only go down."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM cash_accounts").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@mcp.tool()
def pay_invoice(invoice_id: int, account: str, approved_by: str) -> dict:
    """Pay an open vendor invoice out of `account`, after human approval.

    Refuses if the invoice is not open (already paid), or if the account balance is less than
    the invoice amount — no negative balances, ever. On success: inserts a payments row, marks
    the invoice 'paid', and debits the cash account. `approved_by` must name the human who
    approved this — never an agent name.
    """
    conn = _connect()
    invoice = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if invoice is None:
        conn.close()
        return {"invoice_id": invoice_id, "paid": False, "reason": "no such invoice"}
    if invoice["status"] != "open":
        conn.close()
        return {"invoice_id": invoice_id, "paid": False, "reason": f"refused: invoice status is '{invoice['status']}', not open"}
    cash = conn.execute("SELECT * FROM cash_accounts WHERE name = ?", (account,)).fetchone()
    if cash is None:
        conn.close()
        return {"invoice_id": invoice_id, "paid": False, "reason": f"no such cash account '{account}'"}
    if cash["balance"] < invoice["amount"]:
        conn.close()
        return {
            "invoice_id": invoice_id,
            "paid": False,
            "reason": f"refused: insufficient cash (balance {cash['balance']} < amount {invoice['amount']})",
        }
    today = _today(conn)
    conn.execute(
        "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES ('invoice', ?, ?, ?, ?, ?)",
        (invoice_id, invoice["amount"], account, today.isoformat(), approved_by),
    )
    conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (invoice_id,))
    conn.execute(
        "UPDATE cash_accounts SET balance = balance - ?, date = ? WHERE name = ?",
        (invoice["amount"], today.isoformat(), account),
    )
    conn.commit()
    new_balance = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (account,)).fetchone()["balance"]
    conn.close()
    return {"invoice_id": invoice_id, "paid": True, "amount": invoice["amount"], "approved_by": approved_by, "new_balance": new_balance}


@mcp.tool()
def pay_lease(lease_id: int, account: str, approved_by: str) -> dict:
    """Pay a lease's monthly rent out of `account`, after human approval.

    Refuses if the account balance is less than the rent amount — no negative balances. On
    success: inserts a payments row, debits the cash account, and rolls the lease's next_due
    forward by one month. `approved_by` must name the human who approved this — never an agent
    name.
    """
    conn = _connect()
    lease = conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
    if lease is None:
        conn.close()
        return {"lease_id": lease_id, "paid": False, "reason": "no such lease"}
    cash = conn.execute("SELECT * FROM cash_accounts WHERE name = ?", (account,)).fetchone()
    if cash is None:
        conn.close()
        return {"lease_id": lease_id, "paid": False, "reason": f"no such cash account '{account}'"}
    amount = lease["monthly_rent"]
    if cash["balance"] < amount:
        conn.close()
        return {
            "lease_id": lease_id,
            "paid": False,
            "reason": f"refused: insufficient cash (balance {cash['balance']} < amount {amount})",
        }
    today = _today(conn)
    next_due = _add_month(date.fromisoformat(lease["next_due"])).isoformat()
    conn.execute(
        "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES ('rent', ?, ?, ?, ?, ?)",
        (lease_id, amount, account, today.isoformat(), approved_by),
    )
    conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (next_due, lease_id))
    conn.execute(
        "UPDATE cash_accounts SET balance = balance - ?, date = ? WHERE name = ?",
        (amount, today.isoformat(), account),
    )
    conn.commit()
    new_balance = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (account,)).fetchone()["balance"]
    conn.close()
    return {"lease_id": lease_id, "paid": True, "amount": amount, "next_due": next_due, "approved_by": approved_by, "new_balance": new_balance}


if __name__ == "__main__":
    mcp.run()
