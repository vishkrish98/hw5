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
function vendorName(events: AgentEvent[], vendorId: number | null): string {
  let payee = "Vendor";
  if (vendorId !== null) {
    for (const ev of events) {
      if (ev.event === "tool_result" && ev.tool === "list_vendors" && Array.isArray(ev.result)) {
        const match = (ev.result as Array<Record<string, unknown>>).find((v) => v.id === vendorId);
        if (match && typeof match.name === "string") payee = match.name;
      }
    }
  }
  return payee;
}

export function deriveApprovalContext(
  ticket: Ticket,
  events: AgentEvent[],
  lastDecision: BossDecision | null
): ApprovalContext | null {
  const reason = lastDecision?.decision_summary ?? ticket.notes ?? "";

  // Use only the single freshest list_invoices snapshot, not an accumulation across every call in
  // this ticket's history -- an invoice's status can change between calls within the same run
  // (e.g. a re-verification after an earlier payment), and only the latest snapshot reflects
  // whether it's still actually open right now.
  let latestInvoiceList: Array<Record<string, unknown>> | null = null;
  for (const ev of events) {
    if (ev.event === "tool_result" && ev.tool === "list_invoices" && Array.isArray(ev.result)) {
      latestInvoiceList = ev.result as Array<Record<string, unknown>>;
    }
  }

  // ticket.invoice_id is a fixed database field that never changes even after that invoice is
  // paid -- so a plain id match here isn't enough. It must still show up as "open" in the freshest
  // snapshot, or a re-run that re-verifies an already-paid invoice would show a stale approval
  // card for money that's already been spent (reproduced live: ticket 101 re-confirmed invoice 501
  // paid, but the card still showed "$840.00 awaiting approval" until this check was added).
  if (ticket.invoice_id && latestInvoiceList) {
    const match = latestInvoiceList.find((inv) => inv.id === ticket.invoice_id && inv.status === "open");
    if (match) {
      const amount = typeof match.amount === "number" ? match.amount : null;
      const vendorId = typeof match.vendor_id === "number" ? match.vendor_id : null;
      return { kind: "invoice", refId: ticket.invoice_id, payee: vendorName(events, vendorId), amount, reason };
    }
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

  // Some tickets have neither invoice_id nor lease_id resolving to anything open, but still end
  // up blocked on a payment -- e.g. a price-override ticket whose fulfillment shares a vendor with
  // another ticket, and gets blocked by an invoice that OTHER ticket's own restock order created
  // (ticket 103 vs. ticket 101's invoice 502 is exactly this case). Fall back to whatever open
  // invoice Inventory's own list_invoices check already surfaced in this ticket's event history.
  const open = latestInvoiceList?.find((inv) => inv.status === "open");
  if (open && typeof open.id === "number") {
    const amount = typeof open.amount === "number" ? open.amount : null;
    const vendorId = typeof open.vendor_id === "number" ? open.vendor_id : null;
    return { kind: "invoice", refId: open.id, payee: vendorName(events, vendorId), amount, reason };
  }

  return null;
}
