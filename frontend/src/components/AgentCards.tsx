import { AGENT_LABEL, type AgentCard } from "../lib/agents";

const STATE_LABEL = { waiting: "waiting", working: "working", done: "done", failed: "failed" };

export function AgentCards({ cards }: { cards: AgentCard[] }) {
  return (
    <div className="agents">
      {cards.map((card) => (
        <article key={card.agent} className={`agent ${card.state}`} aria-label={AGENT_LABEL[card.agent]}>
          <header>
            <h3>{AGENT_LABEL[card.agent]}</h3>
            <span className={`dot ${card.state}`} aria-hidden="true" />
            <span className="agent-state">{STATE_LABEL[card.state]}</span>
          </header>
          <p className="agent-rounds">
            {card.rounds} {card.rounds === 1 ? "step" : "steps"}
          </p>
          <p className="agent-summary">{card.summary || "—"}</p>
        </article>
      ))}
    </div>
  );
}
