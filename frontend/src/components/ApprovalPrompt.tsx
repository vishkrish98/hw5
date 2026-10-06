import { useState } from "react";
import { api } from "../api";
import type { ApprovalContext } from "../approvalContext";

function money(n: number | null): string {
  return n === null ? "—" : `$${n.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
}

export function ApprovalPrompt({
  context,
  ticketId,
  onApproved,
}: {
  context: ApprovalContext;
  ticketId: number;
  onApproved: (paid: { kind: "invoice" | "lease"; refId: number; amount: number }) => void;
}) {
  const [approvedBy, setApprovedBy] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<{ ok: boolean; message: string } | null>(null);
  const [declined, setDeclined] = useState(false);
  const [done, setDone] = useState(false);

  if (declined) {
    return (
      <div className="approval-card">
        <h3>Declined</h3>
        <p className="declined-note">
          No cash moved. This ticket stays as is — approve later or re-run the team if the situation changes.
        </p>
      </div>
    );
  }

  if (done) {
    return (
      <div className="approval-card">
        <h3>Approved</h3>
        <div className="approved-confirm">✓ {outcome?.message}</div>
      </div>
    );
  }

  async function submit() {
    if (!approvedBy.trim()) {
      setOutcome({ ok: false, message: "Enter who's approving this." });
      return;
    }
    setBusy(true);
    setOutcome(null);
    try {
      const res = await api.approvePayment({
        kind: context.kind,
        ref_id: context.refId,
        approved_by: approvedBy.trim(),
        account: "checking",
        ticket_id: ticketId,
      });
      setOutcome({ ok: true, message: `Paid ${money(res.amount ?? null)} — new balance ${money(res.new_balance ?? null)}` });
      setDone(true);
      if (res.amount !== undefined) {
        onApproved({ kind: context.kind, refId: context.refId, amount: res.amount });
      }
    } catch (err) {
      const raw = err instanceof Error ? err.message : "Approval failed";
      const match = raw.match(/"reason":"([^"]+)"/);
      setOutcome({ ok: false, message: match ? match[1] : raw });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="approval-card">
      <h3>Awaiting your approval</h3>

      <div className="approval-line">
        <span>Payee</span>
        <span>{context.payee}</span>
      </div>
      <div className="approval-line">
        <span>Amount</span>
        <span className="approval-amount tabular">{money(context.amount)}</span>
      </div>

      {context.reason && <p className="approval-reason">{context.reason}</p>}

      <div className="field">
        <label>Approved by</label>
        <input
          value={approvedBy}
          onChange={(e) => setApprovedBy(e.target.value)}
          placeholder="Your name"
          autoFocus
        />
      </div>

      <div className="approval-actions">
        <button className="approve-btn" onClick={submit} disabled={busy}>
          {busy ? "Approving…" : "Approve"}
        </button>
        <button className="decline-btn" onClick={() => setDeclined(true)} disabled={busy}>
          Decline
        </button>
      </div>

      {outcome && !outcome.ok && <div className="approval-result fail">{outcome.message}</div>}
    </div>
  );
}
