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

  // Some tickets have neither invoice_id nor lease_id of their own but still end up blocked on a
  // payment -- e.g. a price-override ticket whose fulfillment shares a vendor with another ticket,
  // and gets blocked by an invoice that OTHER ticket's own restock order created (ticket 103 vs.
  // ticket 101's invoice 502 is exactly this case). The ticket's own invoice_id/lease_id fields have
  // no way to point at that, so fall back to whatever open invoice Inventory's own list_invoices
  // check already surfaced in this ticket's event history.
  // Use only the single freshest list_invoices snapshot, not an accumulation across every call --
  // otherwise a later call showing the same invoice now paid couldn't clear an earlier "open"
  // result, since the loop below only overwrites when it finds something open.
  let latestInvoiceList: Array<Record<string, unknown>> | null = null;
  for (const ev of events) {
    if (ev.event === "tool_result" && ev.tool === "list_invoices" && Array.isArray(ev.result)) {
      latestInvoiceList = ev.result as Array<Record<string, unknown>>;
    }
  }
  let fallbackInvoiceId: number | null = null;
  let fallbackAmount: number | null = null;
  let fallbackVendorId: number | null = null;
  const open = latestInvoiceList?.find((inv) => inv.status === "open");
  if (open && typeof open.id === "number") {
    fallbackInvoiceId = open.id;
    fallbackAmount = typeof open.amount === "number" ? open.amount : null;
    fallbackVendorId = typeof open.vendor_id === "number" ? open.vendor_id : null;
  }
  if (fallbackInvoiceId !== null) {
    let payee = "Vendor";
    if (fallbackVendorId !== null) {
      for (const ev of events) {
        if (ev.event === "tool_result" && ev.tool === "list_vendors" && Array.isArray(ev.result)) {
          const match = (ev.result as Array<Record<string, unknown>>).find((v) => v.id === fallbackVendorId);
          if (match && typeof match.name === "string") payee = match.name;
        }
      }
    }
    return { kind: "invoice", refId: fallbackInvoiceId, payee, amount: fallbackAmount, reason };
  }

  return null;
}
