"""FastAPI backend for the Campus Customs dashboard.

Run from this folder with:
    uvicorn main:app --reload --port 8000

Every route either calls the agent team (backend.agents.run_ticket) or calls an MCP tool
function directly from mcp_server/server.py — the same functions the agents use, just
invoked in-process instead of over stdio. No route re-implements shop logic; this file is
thin plumbing between the database/agents and the dashboard.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
if str(ROOT) not in sys.path:
    # Lets `from backend...` and `from mcp_server...` resolve as real packages even when
    # uvicorn loads this file as the bare top-level module "main" (cwd = backend/).
    sys.path.insert(0, str(ROOT))

from backend import audit
from backend.agents import run_ticket
from mcp_server.server import get_cash_balance, list_tickets, pay_invoice, pay_lease

ORIGINAL_DB = ROOT / "data" / "campus_customs.db"
WORKING_DB = ROOT / "data" / "campus_customs_new.db"

app = FastAPI(title="Campus Customs Backend")

# /reset does a raw OS-level file copy over WORKING_DB with no awareness of SQLite locking --
# today's other race fixes (atomic SQL writes, the audit-log lock) all protect writes *within* one
# sqlite transaction, but none of them stop a reset's file-level overwrite from landing mid-run
# while a ticket's agent team (a separate MCP subprocess) still has that same file open. The
# frontend already disables its own "Reset database" button while a run is in flight, but that's a
# UI-only guard -- a direct API call or a second browser tab bypasses it entirely (something this
# project's own live testing actually did more than once). This counter closes that gap server-side.
_active_runs = 0
_active_runs_lock = threading.Lock()

app.add_middleware(
    CORSMiddleware,
    # The Vite dev server (frontend/) runs on 5173 by default — allow both localhost and
    # 127.0.0.1 forms so the dashboard's browser requests aren't blocked by CORS.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/tickets")
def get_tickets() -> list[dict[str, Any]]:
    """Return the three tickets with each one's status and whether it's resolved."""
    return [{**row, "is_resolved": row["status"] == "resolved"} for row in list_tickets()]


@app.post("/tickets/{ticket_id}/run")
async def run_ticket_route(ticket_id: int) -> dict[str, Any]:
    """Run the agent team on one ticket and return Boss's final decision."""
    global _active_runs
    with _active_runs_lock:
        _active_runs += 1
    try:
        # The 60s timeout in backend/agents.py's OpenAIResponsesModelSettings only bounds calls
        # to the Portkey/model API -- it does nothing for the local MCP tool-call round-trip
        # itself (the stdio request/response to an agent's own subprocess). Observed directly:
        # that round-trip can hang indefinitely with no exception ever raised, which left this
        # route (and the _active_runs counter above, permanently blocking /reset) stuck forever
        # with no way to recover short of killing the process. Wrapping the whole run in a wall-
        # clock timeout guarantees this route always eventually returns, one way or another.
        decision = await asyncio.wait_for(run_ticket(ticket_id), timeout=180)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"agent run timed out after 180s for ticket {ticket_id} -- the shared model/MCP layer can hang with no exception; try again") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"agent run failed: {exc!r}") from exc
    finally:
        with _active_runs_lock:
            _active_runs -= 1
    return decision.model_dump()


@app.get("/events")
def get_events(limit: int = 50, ticket_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Return recent agent events (what each agent said, which tools they used) for the board to refresh."""
    events = audit.read_events()
    if ticket_id is not None:
        events = [e for e in events if e.get("ticket_id") == ticket_id]
    return events[-limit:]


class ApprovePaymentRequest(BaseModel):
    kind: Literal["invoice", "lease"]
    ref_id: int
    approved_by: str
    account: str = "checking"
    ticket_id: Optional[int] = None


@app.post("/payments/approve")
def approve_payment(req: ApprovePaymentRequest) -> dict[str, Any]:
    """Execute a payment after a human clicks approve. Agents only ever prepare a recommendation
    — this is the only route that actually moves cash, and only after this explicit human call."""
    if req.kind == "invoice":
        result = pay_invoice(req.ref_id, req.account, req.approved_by)
    else:
        result = pay_lease(req.ref_id, req.account, req.approved_by)
    audit.log_event(
        run_id="human-approval",
        agent="human",
        ticket_id=req.ticket_id,
        depth=0,
        event="payment_approved",
        kind=req.kind,
        ref_id=req.ref_id,
        approved_by=req.approved_by,
        result=result,
    )
    if not result.get("paid", False):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/cash")
def get_cash() -> list[dict[str, Any]]:
    """Return the current checking balance (and any other cash accounts)."""
    return get_cash_balance()


@app.post("/reset")
def reset_database() -> dict[str, Any]:
    """Reset the working database back to the original values, for a fresh run.

    Refuses while a ticket run is in flight: the copy below is a raw OS-level file overwrite with
    no awareness of SQLite locking, and a ticket's agent team writes to this same file from a
    separate MCP subprocess throughout its run. Landing mid-run could torn-write the file or
    silently discard a commit that was about to land.
    """
    with _active_runs_lock:
        if _active_runs > 0:
            raise HTTPException(status_code=409, detail="refused: a ticket run is in progress, wait for it to finish before resetting")
    shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    audit.log_event(run_id="system", agent="system", ticket_id=None, depth=0, event="database_reset")
    return {"reset": True}
