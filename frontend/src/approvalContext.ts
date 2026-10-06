import type { AgentEvent, BossDecision, Ticket } from "./types";

export interface ApprovalContext {
  kind: "invoice" | "lease";
  refId: number;
  payee: string;
  amount: number | null;
  reason: string;
}

/** There's no dedicated backend field for "invoice amount" or "vendor name" on a ticket —
 * both only exist inside the invoices/vendors tables. Rather than add a new backend route,
 * this derives them from data the backend has already returned: the list_invoices /
 * list_vendors / get_lease_info tool results already sitting in this ticket's own event
 * history (GET /events). Every number shown here still comes from the backend — it's just
 * read out of the audit trail instead of a bespoke endpoint. */
export function deriveApprovalContext(
  ticket: Ticket,
  events: AgentEvent[],
  lastDecision: BossDecision | null
): ApprovalContext | null {
  const reason = lastDecision?.decision_summary ?? ticket.notes ?? "";

  if (ticket.invoice_id) {
    let amount: number | null = null;
    let vendorId: number | null = null;
    for (const ev of events) {
      if (ev.event === "tool_result" && ev.tool === "list_invoices" && Array.isArray(ev.result)) {
        const match = (ev.result as Array<Record<string, unknown>>).find((inv) => inv.id === ticket.invoice_id);
        if (match) {
          amount = typeof match.amount === "number" ? match.amount : amount;
          vendorId = typeof match.vendor_id === "number" ? match.vendor_id : vendorId;
        }
      }
    }
    let payee = "Vendor";
    if (vendorId !== null) {
      for (const ev of events) {
        if (ev.event === "tool_result" && ev.tool === "list_vendors" && Array.isArray(ev.result)) {
          const match = (ev.result as Array<Record<string, unknown>>).find((v) => v.id === vendorId);
          if (match && typeof match.name === "string") payee = match.name;
        }
      }
    }
    return { kind: "invoice", refId: ticket.invoice_id, payee, amount, reason };
  }

  if (ticket.lease_id) {
    let amount: number | null = null;
    for (const ev of events) {
      if (ev.event === "tool_result" && ev.tool === "get_lease_info" && ev.result && typeof ev.result === "object") {
        const r = ev.result as Record<string, unknown>;
        if (r.id === ticket.lease_id && typeof r.monthly_rent === "number") amount = r.monthly_rent;
      }
    }
    return { kind: "lease", refId: ticket.lease_id, payee: ticket.requester, amount, reason };
  }

  return null;
}
