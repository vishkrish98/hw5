export type TicketStatus = "open" | "pending_human_approval" | "resolved" | "blocked";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  sku: string | null;
  size: string | null;
  qty: number | null;
  lease_id: number | null;
  invoice_id: number | null;
  status: TicketStatus;
  notes: string;
  created_at: string;
  is_resolved: boolean;
}

export type AgentName = "boss" | "inventory" | "accounting" | "facilities" | "customer_service" | "human" | "system";

export interface AgentEvent {
  ts: string;
  run_id?: string;
  agent?: AgentName;
  ticket_id?: number | null;
  depth?: number;
  event: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: unknown;
  target?: string;
  task?: string;
  text?: string;
  [key: string]: unknown;
}

export interface BossDecision {
  ticket_id: number;
  delegated_to: string[];
  status: TicketStatus;
  decision_summary: string;
  next_step: string;
}

export interface CashAccount {
  name: string;
  balance: number;
  date: string;
}

export interface ApprovePaymentRequest {
  kind: "invoice" | "lease";
  ref_id: number;
  approved_by: string;
  account?: string;
  ticket_id?: number;
}

export interface ApprovePaymentResult {
  paid: boolean;
  reason?: string;
  amount?: number;
  new_balance?: number;
  [key: string]: unknown;
}
