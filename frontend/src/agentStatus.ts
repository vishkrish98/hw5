import type { AgentKey } from "./agentTheme";
import type { AgentEvent } from "./types";

export type AgentState = "idle" | "thinking" | "calling" | "done" | "blocked";

export interface AgentStatus {
  state: AgentState;
  tool?: string;
}

/** Derive each agent's current status purely from this ticket's own event history — no
 * extra backend call, just reading what GET /events already returned. A tool_call that
 * hasn't been followed by its tool_result yet (because we log incrementally, step by step)
 * genuinely means that call is in flight right now, which is what makes "calling tool" a
 * live, truthful indicator rather than a guess. */
export function deriveAgentStatuses(events: AgentEvent[], running: boolean): Record<AgentKey, AgentStatus> {
  const result: Record<AgentKey, AgentStatus> = {
    boss: { state: "idle" },
    inventory: { state: "idle" },
    accounting: { state: "idle" },
    facilities: { state: "idle" },
    customer_service: { state: "idle" },
  };

  const keys = Object.keys(result) as AgentKey[];
  const touched = new Set<AgentKey>();

  for (const ev of events) {
    const agent = ev.agent as AgentKey | undefined;

    if (ev.event === "delegate" && ev.target && keys.includes(ev.target as AgentKey)) {
      const target = ev.target as AgentKey;
      touched.add(target);
      result[target] = { state: "thinking" };
    }

    if (!agent || !keys.includes(agent)) continue;
    touched.add(agent);

    switch (ev.event) {
      case "run_start":
        result[agent] = { state: "thinking" };
        break;
      case "tool_call":
        result[agent] = ev.tool === "final_result" ? { state: "done" } : { state: "calling", tool: ev.tool };
        break;
      case "tool_result":
        if (ev.tool !== "final_result") result[agent] = { state: "thinking" };
        break;
      case "run_error":
        result[agent] = { state: "blocked" };
        break;
      case "run_end":
        if (result[agent].state !== "blocked") result[agent] = { state: "done" };
        break;
      default:
        break;
    }
  }

  // If the whole run ended and an agent was touched but never reached a clean "done"/"blocked"
  // (e.g. the ticket run errored before this agent's own conclusion was logged), call it blocked.
  if (!running) {
    for (const key of keys) {
      if (touched.has(key) && result[key].state !== "done" && result[key].state !== "blocked") {
        result[key] = { state: "blocked" };
      }
    }
  }

  return result;
}
