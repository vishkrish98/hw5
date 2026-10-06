import type {
  AgentEvent,
  ApprovePaymentRequest,
  ApprovePaymentResult,
  BossDecision,
  CashAccount,
  Ticket,
} from "./types";

const API_BASE = "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${init?.method ?? "GET"} ${path} failed (${res.status}): ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getTickets: () => request<Ticket[]>("/tickets"),

  runTicket: (ticketId: number) =>
    request<BossDecision>(`/tickets/${ticketId}/run`, { method: "POST" }),

  getEvents: (ticketId?: number, limit = 200) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (ticketId !== undefined) params.set("ticket_id", String(ticketId));
    return request<AgentEvent[]>(`/events?${params.toString()}`);
  },

  approvePayment: (body: ApprovePaymentRequest) =>
    request<ApprovePaymentResult>("/payments/approve", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getCash: () => request<CashAccount[]>("/cash"),

  reset: () => request<{ reset: boolean }>("/reset", { method: "POST" }),
};
