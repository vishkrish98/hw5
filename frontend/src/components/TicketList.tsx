import { TICKET_TYPE_LABEL } from "../agentTheme";
import type { Ticket } from "../types";

const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  running: "Running",
  pending_human_approval: "Needs approval",
  resolved: "Resolved",
  blocked: "Blocked",
};

export function TicketList({
  tickets,
  selectedId,
  runningId,
  onSelect,
}: {
  tickets: Ticket[];
  selectedId: number | null;
  runningId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <>
      {tickets.map((t) => {
        const statusKey = t.id === runningId ? "running" : t.status;
        // Switching away from the ticket a run is in flight for would leave the polling interval
        // (closed over the running ticket's id, not whatever's currently selected) overwriting
        // the newly-selected ticket's events/nameplates with the running ticket's data every
        // ~1.4s. Rather than rework the shared events/running state to be per-ticket, block the
        // one action that can cause it: you can't navigate away until that run finishes.
        const blockedByOtherRun = runningId !== null && runningId !== t.id;
        return (
          <button
            key={t.id}
            className={`ticket-card${t.id === selectedId ? " selected" : ""}`}
            onClick={() => onSelect(t.id)}
            disabled={blockedByOtherRun}
          >
            <div className="ticket-card-top">
              <span className="ticket-id small-caps">No. {t.id}</span>
              <span className={`status-chip ${statusKey}`}>{STATUS_LABEL[statusKey] ?? statusKey}</span>
            </div>
            <p className="subject">{t.subject}</p>
            <p className="requester">
              {TICKET_TYPE_LABEL[t.type] ?? t.type} · {t.requester}
            </p>
          </button>
        );
      })}
    </>
  );
}
