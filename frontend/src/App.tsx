import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ApprovalPrompt } from "./components/ApprovalPrompt";
import { AgentNameplates } from "./components/AgentNameplates";
import { LedgerFeed } from "./components/LedgerFeed";
import { BalanceLedger, type ApprovedPayment } from "./components/BalanceLedger";
import { CashPill } from "./components/CashPill";
import { TicketList } from "./components/TicketList";
import { AGENT_THEME, TICKET_TYPE_LABEL } from "./agentTheme";
import { deriveApprovalContext } from "./approvalContext";
import type { AgentEvent, BossDecision, Ticket } from "./types";

const STATUS_COPY: Record<string, string> = {
  resolved: "Resolved",
  pending_human_approval: "Pending human approval",
  blocked: "Blocked",
  open: "Open",
};

function shorten(text: string, max = 110): string {
  const firstSentence = text.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? text;
  const base = firstSentence.length <= max ? firstSentence : text;
  return base.length > max ? `${base.slice(0, max - 1).trimEnd()}…` : base;
}

/** output/audit_trail.json never wipes (by design — it's the permanent record), so GET
 * /events?ticket_id=X returns every run this ticket has ever had, including ones from before a
 * database reset. For the live dashboard, showing the union of all of that alongside a ticket
 * that just went back to "Open" reads as if the agents already worked it. Scope the *display*
 * (nameplates, feed, summaries, approval context) to only the most recent run_id — the full
 * history still lives untouched in the file for anyone who wants to audit it. */
function latestRunOnly(events: AgentEvent[]): AgentEvent[] {
  if (events.length === 0) return events;
  // payment_approved events are logged with run_id "human-approval" (see backend/main.py) —
  // they don't belong to any agent run_ticket() call, so they must never be the thing that
  // decides "the latest run," or a human approval happening after a run completes would mask
  // the entire agent trace it belongs to. Find the latest *agent* run instead, then always keep
  // payment_approved events alongside it — a human approval is always current context.
  const agentEvents = events.filter((e) => e.event !== "payment_approved");
  if (agentEvents.length === 0) return events;
  const lastRunId = agentEvents[agentEvents.length - 1].run_id;
  return events.filter((e) => e.run_id === lastRunId || e.event === "payment_approved");
}

function agentSummaries(events: AgentEvent[]): { agent: string; text: string }[] {
  const byAgent = new Map<string, string>();
  for (const ev of events) {
    if (ev.event === "tool_call" && ev.tool === "final_result" && ev.agent && ev.args) {
      const text = (ev.args.decision_summary ?? ev.args.summary ?? ev.args.body) as string | undefined;
      if (typeof text === "string") byAgent.set(ev.agent, shorten(text));
    }
  }
  return Array.from(byAgent.entries()).map(([agent, text]) => ({ agent, text }));
}

type LoadState = "loading" | "ready" | "error";

function App() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [cash, setCash] = useState<number | null>(null);
  const [startingBalance, setStartingBalance] = useState<number | null>(null);
  const [payments, setPayments] = useState<ApprovedPayment[]>([]);
  const [running, setRunning] = useState(false);
  const [runningId, setRunningId] = useState<number | null>(null);
  const [lastDecision, setLastDecision] = useState<BossDecision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const pollRef = useRef<number | null>(null);
  const confirmTimerRef = useRef<number | null>(null);

  const refreshTickets = useCallback(async () => {
    const data = await api.getTickets();
    setTickets(data);
    return data;
  }, []);

  const refreshCash = useCallback(async () => {
    const accounts = await api.getCash();
    const checking = accounts.find((a) => a.name === "checking") ?? accounts[0];
    const bal = checking ? checking.balance : null;
    setCash(bal);
    setStartingBalance((prev) => (prev === null ? bal : prev));
  }, []);

  const refreshEvents = useCallback(async (ticketId: number) => {
    const data = await api.getEvents(ticketId);
    setEvents(data);
  }, []);

  const loadAll = useCallback(async () => {
    setLoadState("loading");
    try {
      const data = await refreshTickets();
      await refreshCash();
      setLoadState("ready");
      if (data.length > 0) setSelectedId((id) => id ?? data[0].id);
    } catch {
      setLoadState("error");
    }
  }, [refreshTickets, refreshCash]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (selectedId === null) return;
    setLastDecision(null);
    refreshEvents(selectedId);
  }, [selectedId, refreshEvents]);

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      if (confirmTimerRef.current) window.clearTimeout(confirmTimerRef.current);
    };
  }, []);

  const selectedTicket = tickets.find((t) => t.id === selectedId) ?? null;

  async function handleRun() {
    if (selectedId === null) return;
    setRunning(true);
    setRunningId(selectedId);
    setError(null);
    setLastDecision(null);

    pollRef.current = window.setInterval(() => {
      refreshEvents(selectedId);
    }, 1400);

    try {
      const decision = await api.runTicket(selectedId);
      setLastDecision(decision);
      await Promise.all([refreshTickets(), refreshEvents(selectedId), refreshCash()]);
    } catch (err) {
      const raw = err instanceof Error ? err.message : "Agent run failed";
      const friendly = raw.match(/:\s*([^:]+?)\)?$/)?.[1]?.trim();
      setError(friendly || "The agent run didn't complete — the shared model endpoint can be flaky. Try again.");
      await Promise.all([refreshTickets(), refreshEvents(selectedId), refreshCash()]);
    } finally {
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      setRunning(false);
      setRunningId(null);
    }
  }

  function handleApproved(paid: ApprovedPayment) {
    setPayments((prev) => [...prev, paid]);
    if (selectedId !== null) {
      refreshTickets();
      refreshEvents(selectedId);
      refreshCash();
    }
  }

  function handleResetClick() {
    if (!confirmingReset) {
      setConfirmingReset(true);
      confirmTimerRef.current = window.setTimeout(() => setConfirmingReset(false), 4000);
      return;
    }
    if (confirmTimerRef.current) window.clearTimeout(confirmTimerRef.current);
    setConfirmingReset(false);
    (async () => {
      await api.reset();
      setStartingBalance(null);
      setPayments([]);
      await refreshTickets();
      await refreshCash();
      if (selectedId !== null) await refreshEvents(selectedId);
      setLastDecision(null);
      setError(null);
    })();
  }

  if (loadState === "loading") {
    return (
      <div className="app">
        <div className="state-message" style={{ minHeight: "100vh" }}>
          Opening the desk…
        </div>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div className="app">
        <div className="state-message" style={{ minHeight: "100vh" }}>
          <p>Couldn't reach the backend at http://localhost:8000.</p>
          <button className="retry-btn" onClick={loadAll}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  // "Open" means nothing in the current database reflects any processing (whether because this
  // ticket was never run, or because a reset since the last run wiped out what it found) — so
  // don't show stale history from a previous attempt as if it still applies. Only show it while
  // actively running, or once the ticket has actually moved to a worked-on status.
  const showHistory = running || (selectedTicket ? selectedTicket.status !== "open" : false);
  const displayEvents = showHistory ? latestRunOnly(events) : [];

  const approvalContext =
    selectedTicket && selectedTicket.status === "pending_human_approval"
      ? deriveApprovalContext(selectedTicket, displayEvents, lastDecision)
      : null;

  const summaries = agentSummaries(displayEvents);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="mark small-caps">Campus Customs</span>
          <span className="tagline">The desk, after hours</span>
        </div>
        <div className="topbar-right">
          <CashPill balance={cash} />
          <button className={`ghost-btn${confirmingReset ? " confirm" : ""}`} onClick={handleResetClick}>
            {confirmingReset ? "Click again to confirm" : "Reset database"}
          </button>
        </div>
      </header>

      <div className="hero">
        <h1>Your shop, run by the desk.</h1>
        <p>
          Pick a ticket and send the team to work it — Boss, Inventory, Accounting, Facilities, and Customer
          Service, each reasoning out loud as the ledger fills in.
        </p>
        {selectedTicket && (
          <button className="hero-btn" onClick={handleRun} disabled={running}>
            {running ? "Agents working…" : "Run a ticket"}
          </button>
        )}
      </div>

      <div className="layout">
        <div className="col-tickets">
          <div className="panel-title small-caps">Tickets</div>
          <TicketList tickets={tickets} selectedId={selectedId} runningId={runningId} onSelect={setSelectedId} />
        </div>

        <div className="col-desk">
          {!selectedTicket ? (
            <div className="panel panel-empty">Select a ticket to get started.</div>
          ) : (
            <>
              <div className="panel">
                <div className="detail-header">
                  <div className="detail-heading">
                    {selectedTicket.status === "resolved" && <span className="resolved-stamp">Resolved</span>}
                    <h2>
                      No. {selectedTicket.id} · {selectedTicket.subject}
                    </h2>
                    <p className="detail-meta">
                      <span>
                        <b>Type</b> {TICKET_TYPE_LABEL[selectedTicket.type] ?? selectedTicket.type}
                      </span>
                      <span>
                        <b>Requester</b> {selectedTicket.requester}
                      </span>
                      {selectedTicket.sku && (
                        <span>
                          <b>SKU</b> {selectedTicket.sku} {selectedTicket.size} × {selectedTicket.qty}
                        </span>
                      )}
                      {selectedTicket.lease_id && (
                        <span>
                          <b>Lease</b> #{selectedTicket.lease_id}
                        </span>
                      )}
                      {selectedTicket.invoice_id && (
                        <span>
                          <b>Invoice</b> #{selectedTicket.invoice_id}
                        </span>
                      )}
                    </p>
                  </div>
                  <button
                    className={`run-btn${running ? " running" : ""}`}
                    onClick={handleRun}
                    disabled={running}
                  >
                    {running
                      ? "Agents working…"
                      : selectedTicket.status === "open"
                        ? "Run agent team"
                        : "Re-run agent team"}
                  </button>
                </div>

                {error && <div className="error-banner">{error}</div>}

                {(lastDecision ?? selectedTicket.status !== "open") && (
                  <div className={`decision-banner ${selectedTicket.status}`}>
                    {lastDecision?.decision_summary ?? selectedTicket.notes ?? STATUS_COPY[selectedTicket.status]}
                    {lastDecision?.next_step && <span className="next-step">{lastDecision.next_step}</span>}
                  </div>
                )}

                {summaries.length > 0 && (
                  <div className="section-divider">
                    <div className="panel-title small-caps" style={{ marginBottom: 8 }}>
                      Per-agent summary
                    </div>
                    {summaries.map(({ agent, text }) => (
                      <p key={agent} style={{ fontSize: 13, margin: "0 0 8px", color: "var(--text)" }}>
                        <b style={{ color: AGENT_THEME[agent as keyof typeof AGENT_THEME]?.tint ?? "var(--muted)" }}>
                          {AGENT_THEME[agent as keyof typeof AGENT_THEME]?.label ?? agent}
                        </b>{" "}
                        — {text}
                      </p>
                    ))}
                  </div>
                )}

                <div className="section-divider">
                  <div className="panel-title small-caps">The desk</div>
                  <AgentNameplates events={displayEvents} running={running} />
                </div>
              </div>

              <div className="panel">
                <div className="panel-title small-caps">The ledger-book</div>
                <LedgerFeed events={displayEvents} running={running} />
              </div>
            </>
          )}
        </div>

        <div className="col-ledger">
          <div className="panel">
            <BalanceLedger balance={cash} startingBalance={startingBalance} payments={payments} />
          </div>

          {approvalContext && selectedTicket && (
            <ApprovalPrompt context={approvalContext} ticketId={selectedTicket.id} onApproved={handleApproved} />
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
