import { edgeState, type StageId, type StageState, type StageView } from "../lib/pipeline";
import { Icon, type IconName } from "./icons";

const STAGE_ICON: Record<StageId, IconName> = {
  plan: "plan",
  develop: "code",
  review: "eye",
  tests: "flask",
  approve_run: "shield",
  sandbox: "cube",
  fix: "wrench",
  approve_commit: "shield",
  commit: "commit",
};

const STATE_TEXT: Record<StageState, string> = {
  pending: "queued",
  active: "running",
  waiting: "needs you",
  done: "passed",
  failed: "failed",
  skipped: "skipped",
};

/** The run as a CI-style pipeline: one node per stage, connected left to right. The
 * stage that is working pulses and the connection into it animates. */
export function Pipeline({ stages }: { stages: StageView[] }) {
  return (
    <section className="panel pipeline" aria-label="Pipeline">
      <ol>
        {stages.map((stage, index) => (
          <li key={stage.id} className="stage">
            {index > 0 && <span className={`edge ${edgeState(stages, index)}`} aria-hidden="true" />}
            <div
              className={`stage-node kind-${stage.kind} ${stage.state}`}
              aria-label={`${stage.label}: ${STATE_TEXT[stage.state]}`}
            >
              <span className="stage-icon">
                <Icon name={stage.state === "done" ? "check" : stage.state === "failed" ? "x" : STAGE_ICON[stage.id]} />
              </span>
              {stage.runs > 1 && <span className="stage-runs">×{stage.runs}</span>}
              <span className="stage-label">{stage.label}</span>
              <span className="stage-actor">{stage.actor}</span>
              <span className="stage-state">{STATE_TEXT[stage.state]}</span>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
