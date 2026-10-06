# Campus Customs MCP Server

A FastMCP server that gives every agent (Boss, Inventory, Accounting, Facilities,
Customer Service) a shared, single source of truth over the shop's database — so agents
read and change the same facts instead of guessing, inventing numbers, or keeping private
state. Every write tool enforces the shop's own rules (no negative cash, no restocking a
vendor who has an unpaid invoice) at the tool level, so the rule holds even if a tool is
called directly, outside an agent.

**Database:** `data/campus_customs_new.db` (the working copy — `data/campus_customs.db`
stays untouched as the reset point).

## Tools

**Tickets** (the work queue — Boss)
- `get_today()` — reads `desk`. The shop's "today," used for every overdue/due-soon check.
- `list_open_tickets()` — reads `tickets`. The board Boss triages first.
- `get_ticket(ticket_id)` — reads `tickets`. Full ticket row by id.
- `update_ticket(ticket_id, status, notes)` — writes `tickets`. The final call on a ticket; reserved for Boss.

**Inventory** (Inventory agent)
- `check_inventory(sku, size)` — reads `inventory`. On-hand qty for one SKU/size.
- `adjust_inventory(sku, size, delta, reason)` — writes `inventory`. Refuses if qty would go negative.

**Vendors & invoices** (Inventory + Accounting)
- `list_vendors()` — reads `vendors`. Specialty + lead_days per vendor.
- `list_invoices(vendor_id=None, status=None)` — reads `invoices`. Filterable by vendor and/or status.
- `create_restock_order(vendor_id, sku, qty, unit_cost, description)` — writes `invoices` (new open invoice). Refuses if the vendor already has an open invoice.

**Pricing** (Inventory + Accounting)
- `get_pricing(sku)` — reads `pricing`. Unit cost and list price. Inventory calls this to quote a restock order's cost; Accounting calls it for margin/discount checks.
- `compute_bulk_quote(sku, qty, discount_pct)` — reads `pricing`, no write. Margin math for a bulk-discount ask (Accounting only).

**Leases** (Facilities)
- `get_lease_info(lease_id)` — reads `leases` + `desk`. Rent, due date, and days-until-due.

**Cash** (Accounting)
- `get_cash_balance()` — reads `cash_accounts`.

**Payments** — not exposed to any agent in `backend/agents.py`. Accounting can read the cash balance and invoices to *recommend* a payment, but its toolset simply does not include these two tools, so no agent can execute one. They're called directly by `backend/main.py`'s `POST /payments/approve` route, after a human clicks approve in the dashboard — the only path to either tool.
- `pay_invoice(invoice_id, account, approved_by)` — writes `payments`, `invoices`, `cash_accounts`. Refuses if the invoice isn't open or the balance is insufficient.
- `pay_lease(lease_id, account, approved_by)` — writes `payments`, `leases`, `cash_accounts`. Refuses if the balance is insufficient; rolls `next_due` forward one month on success.

See [output/harness.md](../output/harness.md) for the full tool-to-table-to-agent mapping and the three open tickets each tool unlocks.
