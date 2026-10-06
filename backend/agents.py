"""The Campus Customs agent team: Boss, Inventory, Accounting, Facilities, Customer Service.

Every agent is a PydanticAI `Agent` using the same model (gpt-6-luna through Portkey — the only
model this assignment allows) and the same underlying MCP toolset (mcp_server/server.py talking
to data/campus_customs_new.db). No agent has its own private copy of shop facts or a second
tools layer — they all read and write through MCP.

Hub-and-spoke, not a full mesh: only Boss gets `delegate_to_<specialist>` tools. Specialists do
not call each other and do not call Boss — a specialist "tells Boss" simply by returning its
structured output, which is what Boss's delegate call receives. This used to be a full mesh
(every agent could delegate to every other agent), but that let specialists legitimately
delegate back to Boss mid-ticket and bounce around for several slow, token-expensive hops before
settling — see output/harness.md for what that looked like in testing. Boss-only delegation keeps
the same roles and the same tools, just with one place making handoff decisions.

Accounting has no access to pay_invoice/pay_lease at all — it only prepares a recommendation.
Those two tools stay on the MCP server for whatever human-approved execution path (e.g. a
dashboard backend calling them directly after a human clicks "approve") gets wired in a later
problem; no agent in this file can reach them.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import replace
from pathlib import Path

from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from . import audit
from .models import (
    AccountingAssessment,
    BossDecision,
    CustomerMessageDraft,
    FacilitiesAssessment,
    InventoryAssessment,
    ShopDeps,
)

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SERVER_SCRIPT = ROOT / "mcp_server" / "server.py"

# Only model/provider allowed for this assignment: gpt-6-luna, through Portkey.
MODEL_NAME = "gpt-6-luna"


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env()

_provider = OpenAIProvider(base_url="https://api.portkey.ai/v1", api_key=os.environ["PORTKEY_API_KEY"])
# Portkey's gpt-6-luna doesn't support function tools + reasoning_effort on /v1/chat/completions
# (it 400s), so we use the /v1/responses API instead, which Portkey also proxies for this model.
# Reasoning effort is turned down from the default ("medium") to "low": this is a reasoning
# model, and a single tool-calling hop at medium effort burned ~90k reasoning tokens in testing
# — low effort is still enough for "look up a fact and report it" style agent work at a fraction
# of the token cost, which matters a lot with five agents in the loop.
MODEL = OpenAIResponsesModel(
    MODEL_NAME,
    provider=_provider,
    # `timeout` matters here: this shared Portkey-hosted model was observed to be wildly
    # inconsistent in testing — most calls finish in 5-15s, but some hang far past a minute
    # with no error (likely provider-side queuing/congestion on a shared endpoint). Without a
    # timeout, a single slow call makes the whole agent loop look hung with no way to tell
    # "still working" from "never coming back." A hard timeout turns that into a clear,
    # catchable error instead.
    settings=OpenAIResponsesModelSettings(openai_reasoning_effort="low", openai_text_verbosity="low", timeout=60),
)


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


# ---------------------------------------------------------------------------
# MCP toolset: each agent gets its own connection to our server (see note
# below), filtered down to the tools its shop role actually needs.
# ---------------------------------------------------------------------------

# Per-agent tool scoping. Agents only *see* the tools their shop role actually needs —
# this isn't a security boundary (every tool still enforces its own rules at the MCP layer
# regardless of who calls it), it's so each agent's reasoning stays in its own lane instead
# of e.g. Facilities deciding to go touch inventory numbers. Note ACCOUNTING_TOOLS has no
# pay_invoice/pay_lease — Accounting prepares payment recommendations only; it cannot execute
# one no matter what the model decides to do.
BOSS_TOOLS = {"list_open_tickets", "get_ticket", "update_ticket", "get_today"}
INVENTORY_TOOLS = {"check_inventory", "adjust_inventory", "list_vendors", "list_invoices", "create_restock_order", "get_pricing", "get_today"}
ACCOUNTING_TOOLS = {"list_invoices", "get_cash_balance", "get_pricing", "compute_bulk_quote", "get_today"}
FACILITIES_TOOLS = {"get_lease_info", "get_today"}
CUSTOMER_SERVICE_TOOLS = {"get_ticket", "get_today"}


def _toolset_for(names: set[str]):
    # Each agent gets its OWN MCPToolset (its own stdio connection to mcp_server/server.py),
    # not a shared instance. Boss's delegate call pauses mid-tool-call while it awaits a
    # specialist's whole run — if they shared one underlying MCP client/connection, the outer
    # run holding that connection "open" would deadlock against the inner run trying to open
    # it too (this actually happened in testing before the toolsets were split out). Separate
    # connections to the same database file are safe here because calls are sequential
    # (await-by-await), never truly concurrent writes.
    base = MCPToolset(str(SERVER_SCRIPT))
    return base.filtered(lambda ctx, tool_def, _names=names: tool_def.name in _names)


# ---------------------------------------------------------------------------
# The five agents
# ---------------------------------------------------------------------------

boss_agent = Agent(
    MODEL,
    deps_type=ShopDeps,
    output_type=BossDecision,
    system_prompt=_load_prompt("boss"),
    toolsets=[_toolset_for(BOSS_TOOLS)],
)

inventory_agent = Agent(
    MODEL,
    deps_type=ShopDeps,
    output_type=InventoryAssessment,
    system_prompt=_load_prompt("inventory"),
    toolsets=[_toolset_for(INVENTORY_TOOLS)],
)

accounting_agent = Agent(
    MODEL,
    deps_type=ShopDeps,
    output_type=AccountingAssessment,
    system_prompt=_load_prompt("accounting"),
    toolsets=[_toolset_for(ACCOUNTING_TOOLS)],
)

facilities_agent = Agent(
    MODEL,
    deps_type=ShopDeps,
    output_type=FacilitiesAssessment,
    system_prompt=_load_prompt("facilities"),
    toolsets=[_toolset_for(FACILITIES_TOOLS)],
)

customer_service_agent = Agent(
    MODEL,
    deps_type=ShopDeps,
    output_type=CustomerMessageDraft,
    system_prompt=_load_prompt("customer_service"),
    toolsets=[_toolset_for(CUSTOMER_SERVICE_TOOLS)],
)

SPECIALISTS: dict[str, Agent] = {
    "inventory": inventory_agent,
    "accounting": accounting_agent,
    "facilities": facilities_agent,
    "customer_service": customer_service_agent,
}


# ---------------------------------------------------------------------------
# Boss-only delegation: Boss gets one delegate_to_<specialist> tool per
# specialist. Specialists have no delegate tools at all — they report back to
# Boss simply by returning their structured output from the call Boss made.
# The depth guard is mostly a belt-and-suspenders leftover from when the mesh
# was fully connected: with specialists unable to delegate further, depth can
# now only ever reach 1.
# ---------------------------------------------------------------------------


def _make_delegate_tool(to_name: str, to_agent: Agent):
    async def delegate(ctx: RunContext[ShopDeps], task: str) -> str:
        deps = ctx.deps
        if deps.depth >= deps.max_depth:
            audit.log_event(
                run_id=deps.run_id,
                agent="boss",
                ticket_id=deps.ticket_id,
                depth=deps.depth,
                event="delegation_refused",
                target=to_name,
                task=task,
                reason=f"max delegation depth ({deps.max_depth}) reached",
            )
            return f"[delegation refused: max depth {deps.max_depth} reached — resolve with what you already have]"

        sub_deps = replace(deps, depth=deps.depth + 1, trace=[*deps.trace, f"boss->{to_name}"])
        audit.log_event(
            run_id=deps.run_id,
            agent="boss",
            ticket_id=deps.ticket_id,
            depth=deps.depth,
            event="delegate",
            target=to_name,
            task=task,
        )

        # Logged incrementally (not just once at the end) for the same reason as Boss's own
        # run in run_ticket(): a specialist can complete several real tool calls and then fail
        # on a later step against the flaky shared endpoint, and we don't want to lose the
        # record of what it already did.
        logged = 0

        def _flush(agent_run) -> None:
            nonlocal logged
            messages = agent_run.all_messages()
            new = messages[logged:]
            if new:
                audit.log_agent_messages(
                    run_id=sub_deps.run_id,
                    agent_name=to_name,
                    ticket_id=sub_deps.ticket_id,
                    depth=sub_deps.depth,
                    new_messages=new,
                )
                logged = len(messages)

        agent_run = None
        try:
            async with to_agent.iter(
                task, deps=sub_deps, usage=deps.usage, usage_limits=deps.usage_limits
            ) as agent_run:
                async for _ in agent_run:
                    _flush(agent_run)
        except Exception as exc:
            # agent_run can still be None here if the failure happened while `.iter()` was
            # setting up (e.g. the MCP subprocess failed to start), before it ever yielded a
            # run to bind — don't let a bare NameError on `_flush(agent_run)` mask that.
            if agent_run is not None:
                _flush(agent_run)
            audit.log_event(
                run_id=sub_deps.run_id,
                agent=to_name,
                ticket_id=sub_deps.ticket_id,
                depth=sub_deps.depth,
                event="run_error",
                error=str(exc),
            )
            return f"[{to_name} failed: {exc}]"

        output = agent_run.result.output
        summary = getattr(output, "summary", None) or getattr(output, "decision_summary", None) or str(output)
        return f"[{to_name} reports]: {summary}"

    delegate.__doc__ = (
        f"Ask {to_name} a specific question and get back their finding — this is how {to_name} "
        f"reports to you. Use this for one clear ask in their domain, not to hand off the whole "
        f"ticket."
    )
    return delegate


def _register_boss_delegation() -> None:
    for to_name, to_agent in SPECIALISTS.items():
        boss_agent.tool(
            _make_delegate_tool(to_name, to_agent),
            name=f"delegate_to_{to_name}",
        )


_register_boss_delegation()


# ---------------------------------------------------------------------------
# Entry point: run one ticket through Boss
# ---------------------------------------------------------------------------


async def run_ticket(ticket_id: int, run_id: str | None = None) -> BossDecision:
    """Run one ticket through Boss end to end, logging every step to output/audit_trail.json.

    Boss's own messages are logged incrementally as the run proceeds (not just once at the
    end): the shared `gpt-6-luna` endpoint is flaky enough in practice that Boss can complete
    several real tool calls (including `update_ticket`, which already commits to the database)
    and then fail on a later step — logging only on a fully successful `return` would silently
    lose the record of everything Boss actually did in that case, even though the database
    change already happened.
    """
    run_id = run_id or f"ticket-{ticket_id}-{uuid.uuid4().hex[:8]}"
    deps = ShopDeps(run_id=run_id, ticket_id=ticket_id)
    audit.log_event(run_id=run_id, agent="boss", ticket_id=ticket_id, depth=0, event="run_start")
    prompt = (
        f"Work ticket {ticket_id}. Start by calling get_ticket to see its details, then "
        f"delegate to whichever specialists you need, and finish by calling update_ticket "
        f"with your final decision."
    )

    logged = 0

    def _flush(agent_run) -> None:
        nonlocal logged
        messages = agent_run.all_messages()
        new = messages[logged:]
        if new:
            audit.log_agent_messages(
                run_id=run_id, agent_name="boss", ticket_id=ticket_id, depth=0, new_messages=new
            )
            logged = len(messages)

    agent_run = None
    try:
        async with boss_agent.iter(
            prompt, deps=deps, usage=deps.usage, usage_limits=deps.usage_limits
        ) as agent_run:
            async for _ in agent_run:
                _flush(agent_run)
    except Exception as exc:
        # agent_run can still be None here if the failure happened while `.iter()` was setting
        # up (e.g. the MCP subprocess failed to start), before it ever yielded a run to bind.
        if agent_run is not None:
            _flush(agent_run)
        audit.log_event(
            run_id=run_id, agent="boss", ticket_id=ticket_id, depth=0, event="run_error", error=str(exc)
        )
        audit.log_event(run_id=run_id, agent="boss", ticket_id=ticket_id, depth=0, event="run_end")
        raise

    audit.log_event(run_id=run_id, agent="boss", ticket_id=ticket_id, depth=0, event="run_end")
    return agent_run.result.output
