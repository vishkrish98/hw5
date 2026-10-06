import { AGENT_ORDER, AGENT_THEME } from "../agentTheme";
import { deriveAgentStatuses } from "../agentStatus";
import type { AgentEvent } from "../types";

export function AgentNameplates({ events, running }: { events: AgentEvent[]; running: boolean }) {
  const statuses = deriveAgentStatuses(events, running);

  return (
    <div className="nameplates">
      {AGENT_ORDER.map((key) => {
        const style = AGENT_THEME[key];
        const status = statuses[key];
        return (
          <div key={key} className={`nameplate ${status.state}`}>
            <div className="nameplate-head">
              <div className="nameplate-icon" style={{ background: `${style.tint}26`, color: style.tint }}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <path d={style.icon} />
                </svg>
              </div>
              <div>
                <div className="nameplate-name">{style.label}</div>
                <div className="nameplate-role">{style.role}</div>
              </div>
            </div>
            <div className="nameplate-status">
              {status.state === "idle" && "waiting"}
              {status.state === "thinking" && (
                <>
                  <span className="pulse-dot" /> {style.thinking}
                </>
              )}
              {status.state === "calling" && <span className="tool-pill">{status.tool}</span>}
              {status.state === "done" && "done"}
              {status.state === "blocked" && "blocked"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
