"""Shared data types for the Campus Customs agent team.

These are the Pydantic models that flow between agents: the shared run
context (deps), and each specialist's structured output. Keeping each
agent's output as a typed model (instead of free text) is what lets Boss
combine findings from several specialists into one final ticket decision
without re-parsing prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai.usage import RunUsage, UsageLimits

TicketType = Literal["customer_order", "rent_notice", "price_override"]
TicketStatus = Literal["open", "pending_human_approval", "resolved", "blocked"]
AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]

# Shared per-ticket-run token budget — every delegated sub-agent call passes the same
# `usage` accumulator and these same `usage_limits`, so the limit is enforced across the
# *whole* delegation tree for one ticket, not reset for each agent. Multi-agent chats burn
# through tokens fast, so this is the hard stop if something loops or rambles.
#
# request_limit was dropped to 15 back when the team was still a full mesh (every agent could
# delegate to every other), to cut off the runaway cross-talk that caused. Now that delegation
# is hub-and-spoke (only Boss delegates, max depth 1 — see _register_boss_delegation in
# agents.py), that specific risk is gone structurally, not just capped. 15 turned out to be too
# tight for legitimate work instead: ticket 103 (shortfall + vendor-blocked + a bulk-discount
# quote, needing Inventory then Accounting then possibly Customer Service, each several tool
# calls) genuinely needs ~20-25 requests and was hitting UsageLimitExceeded mid-run. Raised
# back up with headroom for a full three-specialist ticket.
DEFAULT_USAGE_LIMITS = UsageLimits(request_limit=40, total_tokens_limit=150_000)


@dataclass
class ShopDeps:
    """Run-scoped context threaded through every agent call via PydanticAI's `deps`.

    `depth` / `max_depth` are the delegation-loop guard. Only Boss has `delegate_to_*` tools
    (specialists report back to Boss by returning their output, not by calling anything), so
    depth can now only ever go from 0 (Boss) to 1 (a specialist Boss called) — `max_depth=1` is
    the correct value for that, and is kept as a belt-and-suspenders check rather than removed
    outright. `usage` / `usage_limits` are the token-budget guard (see DEFAULT_USAGE_LIMITS)
    shared between Boss and whichever specialist it's currently delegating to.
    """

    run_id: str
    ticket_id: Optional[int] = None
    depth: int = 0
    max_depth: int = 1
    trace: list[str] = field(default_factory=list)
    usage: RunUsage = field(default_factory=RunUsage)
    usage_limits: UsageLimits = field(default_factory=lambda: DEFAULT_USAGE_LIMITS)


class InventoryAssessment(BaseModel):
    """Inventory agent's structured finding for a ticket touching stock."""

    sku: Optional[str] = None
    size: Optional[str] = None
    qty_on_hand: Optional[int] = None
    requested_qty: Optional[int] = None
    shortfall: int = Field(0, description="requested_qty - qty_on_hand, floored at 0")
    recommended_vendor_id: Optional[int] = None
    vendor_blocked_by_open_invoice: bool = False
    lead_days: Optional[int] = None
    summary: str = Field(..., description="Plain-language finding for Boss and the audit trail.")


class AccountingAssessment(BaseModel):
    """Accounting agent's structured finding for a ticket touching money (invoices, rent, discounts)."""

    subject: str
    amount: Optional[float] = None
    cash_balance_checked: Optional[float] = None
    sufficient_funds: Optional[bool] = None
    margin_pct: Optional[float] = None
    recommendation: Literal["recommend_payment", "recommend_hold", "recommend_reject"]
    requires_human_approval: bool = Field(
        True, description="Always true for anything touching cash_accounts/invoices/payments."
    )
    summary: str


class FacilitiesAssessment(BaseModel):
    """Facilities agent's structured finding for a lease/rent ticket."""

    lease_id: Optional[int] = None
    days_until_due: Optional[int] = None
    urgency: Literal["ok", "due_soon", "overdue"]
    monthly_rent: Optional[float] = None
    summary: str


class CustomerMessageDraft(BaseModel):
    """Customer Service agent's drafted message. Never sent — stays on the ticket/board."""

    ticket_id: int
    to: str
    subject: str
    body: str
    note_to_boss: str = Field(
        ..., description="Anything the draft depends on (e.g. an ETA or discount) that Boss must confirm before closing the ticket."
    )


class BossDecision(BaseModel):
    """Boss's final call on a ticket, after delegating to whichever specialists were needed."""

    ticket_id: int
    delegated_to: list[AgentName] = Field(default_factory=list)
    status: TicketStatus
    decision_summary: str
    next_step: str = Field(..., description="What happens next: e.g. 'awaiting human approval to pay invoice 501'.")
