"""FastAPI backend for the Campus Customs dashboard.

Run from this folder with:
    uvicorn main:app --reload --port 8000

Every route either calls the agent team (backend.agents.run_ticket) or calls an MCP tool
function directly from mcp_server/server.py — the same functions the agents use, just
invoked in-process instead of over stdio. No route re-implements shop logic; this file is
thin plumbing between the database/agents and the dashboard.
"""

from __future__ import annotations

import shutil
import sys
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
    try:
        decision = await run_ticket(ticket_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"agent run failed: {exc!r}") from exc
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
    """Reset the working database back to the original values, for a fresh run."""
    shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    audit.log_event(run_id="system", agent="system", ticket_id=None, depth=0, event="database_reset")
    return {"reset": True}
