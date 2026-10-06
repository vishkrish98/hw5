import { useEffect, useRef, useState, type ReactNode } from "react";
import { agentStyle } from "../agentTheme";
import type { AgentEvent } from "../types";

function compact(value: unknown, max = 90): string {
  if (value === undefined || value === null) return "";
  const str = typeof value === "string" ? value : JSON.stringify(value);
  return str.length > max ? `${str.slice(0, max - 1)}…` : str;
}

function conclusionText(args: Record<string, unknown> | undefined): string | null {
  if (!args) return null;
  const candidate = args.decision_summary ?? args.summary ?? args.body;
  return typeof candidate === "string" ? candidate : null;
}

function timeAgo(ts: string | undefined): string {
  if (!ts) return "";
  const diffSec = Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000));
  if (diffSec < 5) return "now";
  if (diffSec < 60) return `${diffSec}s`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m`;
  return `${Math.round(diffMin / 60)}h`;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="copy-btn"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function DraftCard({ args }: { args: Record<string, unknown> }) {
  const to = args.to as string | undefined;
  const subject = args.subject as string | undefined;
  const body = (args.body as string | undefined) ?? "";
  return (
    <div className="draft-card">
      <div className="draft-card-head">
        <span>
          Draft to <b>{to}</b>
        </span>
        <CopyButton text={body} />
      </div>
      {subject && <div className="draft-subject">{subject}</div>}
      <div className="draft-body">{body}</div>
      {typeof args.note_to_boss === "string" && args.note_to_boss && (
        <div className="draft-note">Note to Boss: {args.note_to_boss}</div>
      )}
    </div>
  );
}

function entryBody(ev: AgentEvent): { agent: string; body: ReactNode } | null {
  const style = agentStyle(ev.agent);

  switch (ev.event) {
    case "run_start":
      return { agent: "Boss", body: "started working this ticket" };
    case "run_end":
      return { agent: "Boss", body: "finished this ticket" };
    case "database_reset":
      return { agent: "System", body: "database reset to original values" };
    case "delegate":
      return { agent: style.label, body: `asked ${agentStyle(ev.target).label} — ${ev.task as string}` };
    case "run_error":
      return { agent: style.label, body: <span style={{ color: "var(--error)" }}>hit an error — {ev.error as string}</span> };
    case "delegation_refused":
      return { agent: "Boss", body: <span style={{ color: "var(--error)" }}>refused to delegate to {ev.target as string} — {ev.reason as string}</span> };
    case "tool_call":
      if (ev.tool === "final_result") {
        if (ev.agent === "customer_service" && ev.args) {
          return { agent: style.label, body: <DraftCard args={ev.args} /> };
        }
        const text = conclusionText(ev.args);
        return text ? { agent: style.label, body: `concluded — ${text}` } : null;
      }
      return { agent: style.label, body: <span className="feed-chip">{ev.tool}({compact(ev.args, 60)})</span> };
    case "tool_result":
      if (ev.tool === "final_result") return null;
      return { agent: style.label, body: <span className="feed-chip result">→ {compact(ev.result, 80)}</span> };
    case "agent_text":
      return { agent: style.label, body: ev.text as string };
    case "payment_approved": {
      const ok = (ev.result as Record<string, unknown> | undefined)?.paid === true;
      return {
        agent: (ev.approved_by as string) ?? "You",
        body: `${ok ? "approved and paid" : "attempted approval — refused"} ${ev.kind as string} #${ev.ref_id as number}`,
      };
    }
    default:
      return null;
  }
}

export function LedgerFeed({ events, running }: { events: AgentEvent[]; running: boolean }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [events.length]);

  const rows = events.map((ev, i) => ({ ev, entry: entryBody(ev), step: i + 1 })).filter((r) => r.entry);

  if (rows.length === 0 && !running) {
    return <div className="feed-empty">No entries yet — run the team to open the ledger.</div>;
  }

  return (
    <div className="feed" ref={scrollRef}>
      {rows.map(({ ev, entry, step }) => (
        <div className="feed-row" key={step}>
          <span className="feed-step">{String(step).padStart(2, "0")}</span>
          <span className="feed-agent" style={{ color: agentStyle(ev.agent).tint }}>
            {entry!.agent}
          </span>
          <span className="feed-body">{entry!.body}</span>
          <span className="feed-time">{timeAgo(ev.ts)}</span>
        </div>
      ))}
      {running && (
        <div className="feed-row">
          <span className="feed-step">…</span>
          <span className="feed-agent" style={{ color: "var(--accent)" }}>
            —
          </span>
          <span className="feed-body" style={{ fontStyle: "italic", color: "var(--muted)" }}>
            <span className="pulse-dot" style={{ marginRight: 6 }} />
            entry pending…
          </span>
          <span className="feed-time" />
        </div>
      )}
    </div>
  );
}
