export type AgentKey = "boss" | "inventory" | "accounting" | "facilities" | "customer_service";

export interface AgentStyle {
  label: string;
  role: string;
  initials: string;
  tint: string;
  icon: string; // SVG path data, viewBox 0 0 24 24
  thinking: string;
}

export const AGENT_THEME: Record<AgentKey, AgentStyle> = {
  boss: {
    label: "Boss",
    role: "Final call",
    initials: "B",
    tint: "#1b2a4a",
    icon: "M4 19V7l8-4 8 4v12M4 19h16M4 19v-6h4v6M16 19v-6h4v6M11 11h2",
    thinking: "weighing the ticket…",
  },
  inventory: {
    label: "Inventory",
    role: "Stock & vendors",
    initials: "I",
    tint: "#0f6e56",
    icon: "M3 7l9-4 9 4-9 4-9-4zm0 0v10l9 4m0-14v14m9-14v10l-9 4",
    thinking: "counting the shelves…",
  },
  accounting: {
    label: "Accounting",
    role: "Cash & invoices",
    initials: "A",
    tint: "#3b6d11",
    icon: "M12 3v18M7 7h7a3 3 0 0 1 0 6H8a3 3 0 0 0 0 6h8",
    thinking: "balancing the books…",
  },
  facilities: {
    label: "Facilities",
    role: "Lease and rent",
    initials: "F",
    tint: "#a3650c",
    icon: "M4 21V9l8-6 8 6v12M4 21h16M9 21v-6h6v6",
    thinking: "checking the lease…",
  },
  customer_service: {
    label: "Customer Service",
    role: "Drafts the replies",
    initials: "CS",
    tint: "#534ab7",
    icon: "M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
    thinking: "drafting a reply…",
  },
};

export function agentStyle(agent?: string): AgentStyle & { label: string } {
  if (agent && agent in AGENT_THEME) return AGENT_THEME[agent as AgentKey];
  return {
    label: agent === "human" ? "You" : agent === "system" ? "System" : (agent ?? "Unknown"),
    role: "",
    initials: agent ? agent[0].toUpperCase() : "?",
    tint: "#6b6a64",
    icon: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z",
    thinking: "working…",
  };
}

export const AGENT_ORDER: AgentKey[] = ["boss", "inventory", "accounting", "facilities", "customer_service"];

export const TICKET_TYPE_LABEL: Record<string, string> = {
  customer_order: "Customer order",
  rent_notice: "Rent notice",
  price_override: "Price override",
};
