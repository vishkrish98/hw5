# Harness — Campus Customs Database

Running notes on the database structure and how each table feeds the agent team. Grows with each problem.

## Problem 2: Database study

Working copy created: `data/campus_customs_new.db` (copy of `data/campus_customs.db`). All later problems read/write the `_new` copy; the original stays untouched as a reset point.

### Tables

**desk** — `date_today`, `notes`
"Today" for the shop (`2026-08-31`). Every overdue/lead-time calculation (invoices, leases, vendor restock timing) is relative to this field, not the real wall-clock date.

**tickets** — `id`, `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id`, `invoice_id`, `status`, `notes`, `created_at`
The work queue. Boss reads this table first; `type` routes the ticket to an agent, and `sku`/`lease_id`/`invoice_id` are foreign-key-style pointers into the tables each specialist agent owns.

**inventory** — `sku`, `name`, `size`, `qty`, `location` (PK: sku+size)
Ground truth for stock on hand. Inventory agent reads this to spot shortfalls per SKU/size before deciding whether to recommend a restock.

**pricing** — `sku`, `unit_cost`, `list_price`
Margin data. Accounting agent uses this to evaluate discount requests (e.g. price-override tickets) against the cost floor.

**vendors** — `id`, `name`, `specialty`, `lead_days`
Who can restock what, and how long it takes. Inventory agent matches a shortfall's SKU category to a vendor's `specialty`, then uses `lead_days` to estimate arrival; must also check that vendor has no open unpaid invoice before placing a new order.

**leases** — `id`, `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`
Rent terms for the shop space. Facilities agent uses `next_due` vs. `desk.date_today` to tell if a rent notice is urgent/overdue, and `monthly_rent` as the payment amount.

**cash_accounts** — `name`, `balance`, `date`
The shop's only money. Accounting agent checks `balance` before approving any payment or purchase order — no revenue is modeled, so this number only goes down.

**payments** — `id`, `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by`
Ledger of money actually sent, written only after a human approves. `ref_id` + `kind` tie a payment back to the invoice or lease it settled, and `approved_by` is the human-approval audit trail required by the assignment rules.

**invoices** — `id`, `vendor_id`, `amount`, `due_date`, `status`, `description`
Bills owed to vendors. Accounting agent checks `status`/`due_date` against `desk.date_today` for overdue bills, and a vendor with any `open` invoice here is blocked from receiving new restock orders (per shop rules).

### The three open tickets, and how they link

- **#101 — customer_order** (Tauhid Zaman, `CC-TEE-WHITE` size S, qty 1): inventory for that SKU/size is `0`. The ticket already carries `invoice_id = 501`, which is an **open, overdue** invoice (`due_date 2026-08-28`, 3 days past `date_today`) to **vendor 1 (Bulldog Print Co)** for a rush reprint of this exact SKU/size. So the restock this order needs is already in flight — but per the vendor rule, Bulldog Print Co won't ship more product while invoice #501 is unpaid. This ticket is effectively blocked on Accounting paying invoice #501 (pending human approval).
- **#102 — rent_notice** (Elm City Properties): carries `lease_id = 1`, pointing to the Chapel Street shop lease — `monthly_rent 2400.0`, `next_due 2026-09-02`, which is only 2 days after `date_today`. Facilities/Accounting need to flag this as due soon and prep a payment for approval.
- **#103 — price_override** (Yale AI Club, `CC-HOOD-NAVY` size M, qty 20): inventory only has `8` units of that SKU/size on hand — a shortfall of 12 against the requested 20. No `lease_id`/`invoice_id` set yet. Restocking this SKU also routes to **vendor 1 (Bulldog Print Co)** (apparel specialty) — the same vendor blocked by invoice #501 — so this ticket is indirectly tangled with #101's unpaid invoice too. Pricing (`unit_cost 22.0`, `list_price 58.0`) gives Accounting the margin floor for evaluating the bulk discount ask.

## Problem 3: MCP server tools

Three read tools in `mcp_server/server.py` (FastMCP, pointed at `data/campus_customs_new.db`). Not wired to a live client/transport yet — just written.

| Tool | Reads | Unlocks | Why this ticket |
|---|---|---|---|
| `check_inventory(sku, size)` | `inventory` | **#101** | Ticket 101 asks for `CC-TEE-WHITE` size S, qty 1. This tool is the only way to confirm on-hand qty is `0` for that exact SKU/size, which is what turns this from "fulfill from stock" into "needs a restock decision." |
| `get_lease_info(lease_id)` | `leases`, `desk` | **#102** | Ticket 102 is a rent notice carrying `lease_id = 1` but no amount or due date of its own. This tool pulls the Chapel Street lease's `monthly_rent` and `next_due` and pairs it with `desk.date_today`, which is exactly what's needed to tell Facilities/Accounting the rent is due in 2 days. |
| `get_pricing(sku)` | `pricing` | **#103** | Ticket 103 asks for a 20% (or similar) bulk discount on `CC-HOOD-NAVY` with no cost data in the ticket itself. This tool returns `unit_cost 22.0` vs `list_price 58.0`, which is the margin floor Accounting needs before it can approve or counter the discount ask. |

## Problem 5: Agent team and the full MCP toolset

Agents are PydanticAI `Agent`s (`backend/agents.py`), all on the same model (`gpt-6-luna`, through Portkey's `/v1/responses` endpoint — see note below) and the same MCP server (`mcp_server/server.py` over `data/campus_customs_new.db`). Prompts live one-per-file in `backend/prompts/`. Structured outputs/deps live in `backend/models.py`.

**Hub-and-spoke, not a full mesh.** Only Boss has `delegate_to_<specialist>` tools (one per specialist). Specialists do not call each other and do not call Boss — a specialist "tells Boss" simply by returning its structured output from the call Boss made; there is no `delegate_to_boss` tool anywhere. This replaced an earlier full-mesh design (every agent could delegate to every other agent) after testing showed it let Accounting legitimately delegate back to Boss mid-ticket and bounce around for several slow, expensive hops before settling — see "What testing surfaced" below.

### Agents and their tools

| Agent | MCP tools it can see | Table(s) used |
|---|---|---|
| **Boss** | `list_open_tickets`, `get_ticket`, `update_ticket`, `get_today`, plus `delegate_to_inventory`/`delegate_to_accounting`/`delegate_to_facilities`/`delegate_to_customer_service` | `tickets`, `desk` |
| **Inventory** | `check_inventory`, `adjust_inventory`, `list_vendors`, `list_invoices`, `create_restock_order`, `get_today` | `inventory`, `vendors`, `invoices`, `desk` |
| **Accounting** | `list_invoices`, `get_cash_balance`, `get_pricing`, `compute_bulk_quote`, `get_today` | `invoices`, `cash_accounts`, `pricing`, `desk` |
| **Facilities** | `get_lease_info`, `get_today` | `leases`, `desk` |
| **Customer Service** | `get_ticket`, `get_today` | `tickets`, `desk` |

Accounting has **no** `pay_invoice`/`pay_lease` in its toolset — not gated, not hidden behind an approval flag, just absent. It cannot execute a payment no matter what the model decides; it can only return an `AccountingAssessment` recommendation. Only Boss can write back to a ticket (`update_ticket`); only Boss decides whether a Customer Service draft gets copied into a ticket's `notes`.

### Full MCP tool roster (15 tools)

| Tool | Reads/writes | Used by |
|---|---|---|
| `get_today` | reads `desk` | all agents |
| `list_open_tickets` | reads `tickets` | Boss |
| `get_ticket` | reads `tickets` | Boss, Customer Service |
| `update_ticket` | writes `tickets` | Boss only — the final call |
| `check_inventory` | reads `inventory` | Inventory |
| `adjust_inventory` | writes `inventory` (refuses negative qty) | Inventory |
| `list_vendors` | reads `vendors` | Inventory |
| `list_invoices` | reads `invoices` | Inventory (vendor-blocked check), Accounting (watch overdue) |
| `create_restock_order` | writes `invoices` (refuses if vendor has an open invoice) | Inventory — only when Boss's delegated task explicitly authorizes a restock |
| `get_pricing` | reads `pricing` | Accounting |
| `compute_bulk_quote` | reads `pricing`, no write | Accounting |
| `get_lease_info` | reads `leases` + `desk` | Facilities |
| `get_cash_balance` | reads `cash_accounts` | Accounting |
| `pay_invoice` | writes `payments`, `invoices`, `cash_accounts` (refuses insufficient cash / already-paid) | **No agent** — stays on the MCP server for a future human-approved execution path (e.g. a dashboard backend calling it directly after a human clicks "approve") |
| `pay_lease` | writes `payments`, `leases`, `cash_accounts` (refuses insufficient cash) | **No agent** — same as above |

Every write tool enforces its own rule at the database layer (not just in a prompt), so the rule holds even if a tool were called directly, outside an agent: `adjust_inventory` and the two pay tools refuse before going negative, and `create_restock_order` refuses a vendor with an open invoice.

Tool-name check: every tool named in `backend/prompts/*.md` was grepped against the function names in `mcp_server/server.py` — all match exactly, nothing missing or renamed. (`pay_invoice`/`pay_lease` appear in `accounting.md` and `facilities.md` only to explain that those agents do *not* have them — not as callable tools.) No second tools layer exists outside MCP.

### A note on the model call

Portkey's `gpt-6-luna` rejects function-tool calls on `/v1/chat/completions` when `reasoning_effort` is set ("Function tools with reasoning_effort are not supported... use /v1/responses"). Since every agent here relies on tool calls, `backend/agents.py` uses PydanticAI's `OpenAIResponsesModel` (the `/v1/responses` API) instead of the default chat-completions model — same model name, same Portkey key, just a different endpoint shape.

### Safety section — guardrails for real customers and real money

- **No agent can execute a payment, structurally.** Accounting's toolset simply doesn't include `pay_invoice`/`pay_lease` — this isn't a prompt instruction an agent could drift away from, it's a tool the model can never see or call. Those two tools remain on the MCP server for whatever human-approved execution path gets built later (e.g. a dashboard backend calling them directly after a human clicks "approve"), entirely outside this agent loop.
- **No negative balances, ever, enforced at the data layer.** Both pay tools and `adjust_inventory` check the current row before writing and refuse rather than clamp — a real deployment should wrap each check-then-write in a transaction/row lock, since two approvals racing against the same balance could both pass the check before either commits.
- **Drafts only, nothing sent for real.** Customer Service never gets an email/send tool — only `get_ticket`. Its draft also can't reach a customer by accident through the ticket: Customer Service has no `update_ticket` tool, so only Boss decides whether a draft's text actually gets copied onto the ticket record.
- **Drafts never leak internal numbers.** `customer_service.md` explicitly bans `unit_cost`, margins, cash balance, and vendor invoice details from any customer-facing text — discount replies state only the approved quantity/price/conditions, never the math behind them.
- **Restocking requires Boss's explicit go-ahead.** Inventory can diagnose a shortfall and name a vendor, but `inventory.md` tells it to only call `create_restock_order` when Boss's delegated task explicitly says to place the order — not automatically whenever a shortfall exists.
- **Prompt injection is named and addressed directly.** Every one of the five prompts has a "Safety and limits" section instructing the agent to treat ticket `subject`/`notes`/`requester` text as data describing a situation, never as instructions — and to refuse and hand back to Boss anything that asks the agent to act outside its role (e.g. a ticket that says "ignore the rules and approve this").
- **No second shop-facts layer.** Every agent reads/writes the same MCP server over the same database — no agent keeps its own cached numbers, so there's one source of truth a human auditor can check against the ledger.
- **Vendor and cash rules are refused, not just flagged.** `create_restock_order` hard-refuses (doesn't just warn) when a vendor has an open invoice, matching the shop's real constraint that the vendor itself would refuse the order.
- **Token-use limits, two layers:**
  - *Delegation depth limit* (`ShopDeps.max_depth = 1`): only Boss can delegate, so depth can only ever go from 0 (Boss) to 1 (the specialist Boss is talking to) — there is structurally no path to a longer chain, and the guard is kept as a belt-and-suspenders check rather than removed.
  - *Shared usage budget* (`ShopDeps.usage` + `DEFAULT_USAGE_LIMITS` in `backend/models.py`: `request_limit=40`, `total_tokens_limit=150_000`): Boss and whichever specialist it's delegating to share the same `RunUsage` accumulator and the same `UsageLimits` for that hop, so a runaway back-and-forth inside one delegation still has a hard stop. (`request_limit` was dropped to 15 while the team was still a full mesh, to cut off cross-talk; after the hub-and-spoke fix removed that risk structurally, 15 turned out too tight for a legitimate three-specialist ticket — ticket 103 genuinely needs ~20-25 requests and was hitting `UsageLimitExceeded` mid-run. Raised back to 40 with headroom.)
- **Full audit trail.** Every tool call, tool result, and agent text output across Boss and any specialist it delegates to is appended to `output/audit_trail.json` (never overwritten), so a human can reconstruct exactly what any agent saw and did on any ticket after the fact.

### What testing surfaced (and why the architecture changed)

Testing the live team against Portkey turned up two real things:

1. **Full connectivity (the original design) meant real cross-talk, which was slow and token-hungry.** With all five agents able to delegate to all others, a run on ticket 102 showed Accounting genuinely delegating back to Boss mid-ticket (still visible in `output/audit_trail.json` under run `smoke-test-102`), which could bounce a few hops before settling — sometimes long enough to make a single ticket impractical to even smoke-test. Switching to hub-and-spoke (only Boss delegates; specialists report back by returning output, nothing else) removes the possibility of that cross-talk entirely, rather than just capping it tighter. A post-fix run on ticket 102 (run `hub-spoke-smoke-102`) completed in ~37 seconds with Boss delegating once each to Facilities and Accounting and no bounce-back.
2. **The shared `gpt-6-luna` endpoint through Portkey is noticeably inconsistent.** Identical calls ranged from ~5-15 seconds to never returning at all. After adding a 60-second `timeout` to `OpenAIResponsesModelSettings` (see `backend/agents.py`), a stuck call fails cleanly with `ModelAPIError('Request timed out.')` instead of hanging forever — worth keeping in mind (and worth adding retry/backoff logic) for the later problem that runs all three tickets for real.

## Problem 7: Backend routes

`backend/main.py` is a FastAPI app. It adds one new read-only MCP tool (`list_tickets`, returns all tickets regardless of status — `list_open_tickets` only returns open ones, which Boss still uses) and otherwise calls either `backend.agents.run_ticket` or an existing MCP tool function directly (in-process, not over stdio) — no route re-implements shop logic or bypasses MCP. Run from `backend/` with `uvicorn main:app --reload --port 8000`.

| Route | What it does |
|---|---|
| `GET /tickets` | Returns all three tickets (full row) plus `is_resolved` (`status == "resolved"`) for each. |
| `POST /tickets/{ticket_id}/run` | Runs the agent team (Boss + whichever specialists it delegates to) on that ticket and returns Boss's final `BossDecision`. |
| `GET /events?limit=&ticket_id=` | Returns the most recent agent events (tool calls, tool results, agent text) from `output/audit_trail.json`, optionally filtered to one ticket — what the dashboard polls to refresh. |
| `POST /payments/approve` | Body `{kind: "invoice"|"lease", ref_id, approved_by, account}`. Calls `pay_invoice`/`pay_lease` directly — this is the only route that actually moves cash, and only after a human calls it; every agent can only recommend. |
| `GET /cash` | Returns the current `cash_accounts` rows (checking balance). |
| `POST /reset` | Copies `data/campus_customs.db` back over `data/campus_customs_new.db` for a fresh run. |

All six routes were smoke-tested against a live server: `/tickets`, `/cash`, and `/events` returned correct data; `/payments/approve` paid invoice 501 for real (balance `3400 → 2560`) and correctly refused a second attempt to pay the same now-closed invoice (`400`, `"invoice status is 'paid', not open"`); `/tickets/{id}/run` resolved ticket 102 end to end; `/reset` was used to restore the working database after each test, confirmed byte-identical to the original afterward.

## Problem 8: Agent dashboard

`frontend/` is a React + Vite + TypeScript app (`npm run dev`, port 5173) that calls the six routes above at `http://localhost:8000`. See `output/design.md` for the current look-and-feel rationale — the dashboard went through three visual passes: an initial light/Apple-style theme, a full rebuild to a dark-academia brief (dark-only, brass/moss palette, serif headlines), then a final restyle to match `output/desk_tickets.html`'s cream/navy/gold look so the live dashboard and the project's static output read as one consistent product (same three-column layout, agent nameplates, and ledger-styled feed throughout — only color and type changed in that last pass). Functionally it: lists all three tickets with a status chip (`Open`/`Running`/`Needs approval`/`Resolved`/`Blocked`, the `Running` state derived client-side while a request is in flight, not a backend status); runs the agent team on the selected ticket (`POST /tickets/{id}/run`) while polling `GET /events` every ~1.4s so the feed and the five agent nameplates (idle/thinking/calling-tool/done/blocked, derived in `src/agentStatus.ts` purely from existing events) update live, mid-request; shows Boss's final decision as a colored banner; shows a short per-agent summary (first sentence of each agent's own conclusion); renders an approval prompt (payee, amount, reason, Approve/Decline) whenever status is `pending_human_approval` — payee/amount are derived client-side in `src/approvalContext.ts` from `list_invoices`/`list_vendors`/`get_lease_info` tool results already present in that ticket's own event history, since no backend field exposes invoice amount or vendor name directly (flagged rather than adding a new route); Decline is a local-only dismissal (no backend route needed, since declining moves no cash); and shows the checking balance in the top bar and a large figure plus a starting/paid/current strip in the right-hand ledger column, both of which visibly drop the moment a payment is approved.

**A real bug found via live testing, fixed in `backend/agents.py`:** `run_ticket` and the specialist delegate calls originally logged an agent's messages to `output/audit_trail.json` only once, after that agent's whole run returned successfully. Running ticket 101 live against the actual Portkey endpoint hit a case where Boss completed several real steps (including a successful `update_ticket` call that changed the database) and then failed on a later step — the database change stuck, but the audit trail had zero record of anything Boss did, and the dashboard's timeline would have gone silent with no explanation. Fixed by switching both to PydanticAI's `agent.iter(...)` and logging incrementally after every step, flushing whatever happened so far if a later step raises — a partial success now shows a partial trace plus a clearly-marked `run_error` row, instead of silently vanishing.

## Problem 9: Resolving the three tickets for real

Reset the working database, noted the starting checking balance ($3,400.00), and ran all three tickets through to their final state via repeated runs + human-approved payments. Full outcome, tool-by-tool trace, and cash itemization are in `output/desk_tickets.html` (Actual + Cash tabs) and `output/resolved_tickets.json`; dashboard screenshots of each final state are in `output/resolved_board.html`. Short version:

- **Ticket 101 (Bulldog tee) → resolved.** Invoice 501 paid ($840) to unblock the vendor; Inventory then quoted $8/unit and placed its own restock order (new invoice #502) with no further human step needed.
- **Ticket 102 (Rent due) → resolved.** Lease 1 paid ($2,400); re-run confirmed the due date rolled forward and nothing further was owed.
- **Ticket 103 (Bulk hoodie discount) → pending_human_approval**, and that's its legitimate final state, not a stuck process: the ticket never specifies a target discount percentage, so Accounting can't evaluate an override no matter how many times it's asked. That's a real pricing judgment call for a human to make outside this system — there was never a button for "approve a discount," only "approve a payment."
- **Ending checking balance: $152.00** ($3,400 − $840 − $2,400 − $8), confirmed to match `cash_accounts` in the working database exactly.

Two real system gaps surfaced only by actually trying to resolve tickets end to end (not by code review), each confirmed, flagged to the user, and fixed on their go-ahead:

1. **Inventory couldn't price anything.** `create_restock_order` requires a `unit_cost` argument, but Inventory's toolset never included `get_pricing` — only Accounting had it, and Boss wasn't relaying the number across. Reproduced twice (same result both times) before fixing: added `get_pricing` to `INVENTORY_TOOLS` in `backend/agents.py`, documented in `inventory.md`.
2. **Boss gated restock orders behind an approval that doesn't exist.** Even after Inventory could quote a cost, Boss treated *placing* a restock order (which moves no cash) the same as a cash payment, asking for a human approval our dashboard has no mechanism to grant — an unresolvable deadlock. Fixed by clarifying `boss.md`: only actual payments need human approval; Boss may authorize a restock order itself once a vendor is unblocked and quoted.

Both fixes required a backend restart — prompt `.md` files aren't watched by uvicorn's `--reload`, so editing a prompt alone isn't enough to pick it up.

---

# Final reference

Everything below reflects the system's state as of Problem 9 (all fixes applied), in one place — not a problem-by-problem log like the sections above, but what the system *is*.

## Database tables (`data/campus_customs_new.db`)

| Table | Fields | Why it matters |
|---|---|---|
| `desk` | `date_today`, `notes` | The shop's "today" — every overdue/due-soon check is relative to this, not the real calendar date. |
| `tickets` | `id`, `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id`, `invoice_id`, `status`, `notes`, `created_at` | The work queue Boss triages and the record of every decision. |
| `inventory` | `sku`, `size`, `qty`, `name`, `location` (composite key sku+size) | Ground truth for stock on hand. |
| `pricing` | `sku`, `unit_cost`, `list_price` | Cost floor for margin checks and restock quotes. |
| `vendors` | `id`, `name`, `specialty`, `lead_days` | Who can restock what, and how long it takes. |
| `leases` | `id`, `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes` | Rent terms for the shop space. |
| `cash_accounts` | `name`, `balance`, `date` | The shop's only money — no revenue is modeled, so it only goes down. |
| `payments` | `id`, `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by` | Ledger of money actually sent, written only after a human approves. |
| `invoices` | `id`, `vendor_id`, `amount`, `due_date`, `status`, `description` | Bills owed to vendors; any vendor with an `open` invoice is blocked from new orders. |

## MCP tools (`mcp_server/server.py`, 16 tools)

| Tool | Table(s) | Who can call it |
|---|---|---|
| `get_today` | `desk` | All five agents |
| `list_open_tickets` | `tickets` | Boss |
| `list_tickets` | `tickets` | No agent — used by the dashboard's `GET /tickets` route only |
| `get_ticket` | `tickets` | Boss, Customer Service |
| `update_ticket` | `tickets` (write) | Boss only |
| `check_inventory` | `inventory` | Inventory |
| `adjust_inventory` | `inventory` (write, refuses negative qty) | Inventory |
| `list_vendors` | `vendors` | Inventory |
| `list_invoices` | `invoices` | Inventory, Accounting |
| `create_restock_order` | `invoices` (write, refuses if vendor has an open invoice) | Inventory — only when Boss authorizes it |
| `get_pricing` | `pricing` | Inventory, Accounting |
| `compute_bulk_quote` | `pricing` (read-only calc) | Accounting |
| `get_lease_info` | `leases` + `desk` | Facilities |
| `get_cash_balance` | `cash_accounts` | Accounting |
| `pay_invoice` | `payments`, `invoices`, `cash_accounts` (write, refuses insufficient cash / already-paid) | No agent — called directly by `POST /payments/approve` after a human approves |
| `pay_lease` | `payments`, `leases`, `cash_accounts` (write, refuses insufficient cash) | No agent — same as above |

Every write tool enforces its own rule at the database layer, not just in a prompt, so the rule holds even if a tool were called directly: `adjust_inventory` and the two pay tools refuse before going negative; `create_restock_order` refuses a vendor with an open invoice.

## The five agents (`backend/agents.py`, `backend/prompts/*.md`)

All five run on `gpt-6-luna` through Portkey's `/v1/responses` endpoint (the only model/provider this assignment allows), reasoning effort `low`. Hub-and-spoke delegation: only Boss has `delegate_to_*` tools; specialists report back by returning their structured output, never by calling anyone themselves.

- **Boss** — final call on every ticket. Reads the ticket, delegates to whichever specialists it needs, authorizes restock orders itself (no cash moves), and is the only one who writes back to the ticket (`update_ticket`). Treats a ticket's own `notes` as history from a past run, not current fact — re-verifies anything that could have changed (an invoice's paid status, cash, stock) rather than repeating an old conclusion.
- **Inventory** — stock, vendors, restocks. Checks exact sku/size on hand, matches a shortfall to a vendor by specialty, checks that vendor isn't blocked by an open invoice, and (since Problem 9) prices and places its own restock order once Boss authorizes one.
- **Accounting** — cash, invoices, margins. Has no `pay_invoice`/`pay_lease` in its toolset at all — it can only recommend; those two tools aren't reachable by any agent. Evaluates discount requests against the cost floor and refuses to recommend a payment that would leave cash negative.
- **Facilities** — lease and rent. Reports exact rent amount, due date, and urgency (`overdue` / `due_soon` within 3 days / `ok`) relative to `desk.date_today`. Never touches cash; tells Boss when Accounting should get involved.
- **Customer Service** — drafts replies only, never sends anything. Drafts never include `unit_cost`, margins, cash balance, or vendor invoice details — a discount reply states only the approved price/quantity, never the math behind it.

## API routes (`backend/main.py`, port 8000)

| Route | What it does |
|---|---|
| `GET /tickets` | All three tickets plus `is_resolved`. |
| `POST /tickets/{id}/run` | Runs the agent team on that ticket, returns Boss's final decision. |
| `GET /events?limit=&ticket_id=` | Recent agent events from `output/audit_trail.json`, optionally scoped to one ticket. |
| `POST /payments/approve` | Body includes `ticket_id` (so the approval shows up in that ticket's own event history) plus `kind`/`ref_id`/`approved_by`/`account`. The only route that moves cash. |
| `GET /cash` | Current `cash_accounts` balance. |
| `POST /reset` | Restores the working database from the original. |

CORS allows exactly `http://localhost:5173` and `127.0.0.1:5173` (the Vite dev server), not a wildcard.

## The dashboard (`frontend/`, port 5173)

React + Vite + TypeScript, restyled to match `output/desk_tickets.html`'s look (cream/navy/gold on white, system sans-serif — see `output/design.md` for the full rationale). Three columns: tickets (catalogue cards) → the desk (ticket detail, per-agent summary, five agent nameplates showing live idle/thinking/calling-tool/done/blocked status, and a ledger-styled activity feed) → the ledger (balance in large numerals with a starting/paid/current strip, and the approval prompt when one's waiting).

Two display rules worth knowing, both added after bugs surfaced in live testing:
- The dashboard only shows an agent's history (nameplates, summary, feed) while a run is actively in progress, or once a ticket has left `open` — a freshly reset ticket showing `Open` never displays a stale summary from before the reset, even though `output/audit_trail.json` itself never wipes.
- That history is scoped to the ticket's latest *agent* run specifically — payment approvals (logged with the sentinel `run_id: "human-approval"`, not a real agent run id) are always shown alongside it regardless, so an approved payment never silently disappears from its own ticket's feed.

## Safety rules, end to end

- **No agent can execute a payment, structurally** — not gated, just absent from every agent's toolset. `pay_invoice`/`pay_lease` are only reachable through `POST /payments/approve`, called after an explicit human action.
- **No negative balances or negative inventory, enforced at the database layer** — every write tool checks before writing and refuses rather than clamps.
- **Vendor blocking is refused, not just flagged** — `create_restock_order` hard-refuses a vendor with any open invoice.
- **Drafts never leak internal numbers and are never sent** — Customer Service has no send capability and no `update_ticket` access; only Boss decides what reaches the permanent ticket record.
- **Restocking requires Boss's explicit go-ahead** — Inventory diagnoses a shortfall but won't place an order unless told to.
- **Prompt injection is named directly in every agent's prompt** — ticket `subject`/`notes`/`requester` text is treated as data describing a situation, never as instructions; each agent refuses and hands back to Boss anything that asks it to act outside its role.
- **Token-use limits** — delegation depth is capped at 1 (structurally, since only Boss delegates), and a shared per-ticket `UsageLimits(request_limit=40, total_tokens_limit=150_000)` bounds the whole delegation tree for one ticket (raised from an initial `15` once hub-and-spoke made the original full-mesh runaway-cost risk structurally impossible, and `15` turned out too tight for a real three-specialist ticket).
- **Full audit trail** — every tool call, tool result, agent text, delegation, refusal, and human approval is appended to `output/audit_trail.json`, never overwritten, across every run this project has ever done.
