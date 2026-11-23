import { AGENT_LABEL, type AgentCard } from "../lib/agents";

const INITIAL = { planner: "P", developer: "D", reviewer: "R", tester: "T" };
const ROLE = {
  planner: "requirement → plan",
  developer: "plan → code",
  reviewer: "static + LLM review",
  tester: "tests · triage · fixes",
};

export function AgentCards({ cards }: { cards: AgentCard[] }) {
  return (
    <div className="agents">
      {cards.map((card) => (
        <article
          key={card.agent}
          className={`agent ${card.agent} ${card.state}`}
          aria-label={AGENT_LABEL[card.agent]}
        >
          <span className="avatar" aria-hidden="true">
            {INITIAL[card.agent]}
          </span>
          <header>
            <h3>{AGENT_LABEL[card.agent]}</h3>
            <span className="agent-state">{card.state}</span>
          </header>
          <p className="agent-rounds">
            {ROLE[card.agent]} · {card.rounds} {card.rounds === 1 ? "step" : "steps"}
          </p>
          <p className={`agent-summary ${card.state === "working" ? "typing" : ""}`}>
            {card.summary || "—"}
          </p>
        </article>
      ))}
    </div>
  );
}
