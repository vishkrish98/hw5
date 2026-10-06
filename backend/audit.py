"""Append-only audit trail for the agent team.

output/audit_trail.json holds a single JSON array. Every call to `append_events` reads
whatever is already there (an empty list if the file doesn't exist yet), adds the new
entries, and writes the whole array back — so a new run's events land after every past
run's events instead of wiping the file. Never call `json.dump` directly on this file
anywhere else, or you'll reset history.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart

AUDIT_PATH = Path(__file__).resolve().parent.parent / "output" / "audit_trail.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_events() -> list[dict[str, Any]]:
    """Read the full audit trail (oldest first). Used by the backend's /events route."""
    if not AUDIT_PATH.exists() or AUDIT_PATH.stat().st_size == 0:
        return []
    return json.loads(AUDIT_PATH.read_text())


def append_events(events: list[dict[str, Any]]) -> None:
    """Append one or more audit events to output/audit_trail.json without wiping prior runs."""
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size > 0:
        existing = json.loads(AUDIT_PATH.read_text())
    existing.extend(events)
    AUDIT_PATH.write_text(json.dumps(existing, indent=2, default=str))


def log_agent_messages(
    *,
    run_id: str,
    agent_name: str,
    ticket_id: int | None,
    depth: int,
    new_messages: list[ModelMessage],
) -> None:
    """Turn one agent run's new messages into audit events — one event per tool call,
    tool result, and final text output — and append them.

    This walks `result.new_messages()` after an `agent.run(...)` call rather than streaming
    live, so it captures every step of that run's loop (every tool the model called, what it
    got back, and what it said) in the order it happened.
    """
    events: list[dict[str, Any]] = []
    for message in new_messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    events.append(
                        {
                            "ts": _now(),
                            "run_id": run_id,
                            "agent": agent_name,
                            "ticket_id": ticket_id,
                            "depth": depth,
                            "event": "tool_result",
                            "tool": part.tool_name,
                            "result": part.content,
                        }
                    )
        elif isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    events.append(
                        {
                            "ts": _now(),
                            "run_id": run_id,
                            "agent": agent_name,
                            "ticket_id": ticket_id,
                            "depth": depth,
                            "event": "tool_call",
                            "tool": part.tool_name,
                            "args": part.args_as_dict() if hasattr(part, "args_as_dict") else part.args,
                        }
                    )
                elif isinstance(part, TextPart) and part.content.strip():
                    events.append(
                        {
                            "ts": _now(),
                            "run_id": run_id,
                            "agent": agent_name,
                            "ticket_id": ticket_id,
                            "depth": depth,
                            "event": "agent_text",
                            "text": part.content,
                        }
                    )
    if events:
        append_events(events)


def log_event(**fields: Any) -> None:
    """Append one ad-hoc audit event (e.g. agent_start, delegate, refused) with a timestamp."""
    append_events([{"ts": _now(), **fields}])
