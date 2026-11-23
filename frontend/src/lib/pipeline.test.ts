import { describe, expect, it } from "vitest";
import { buildPipeline, edgeState, stageFromLog, type StageId } from "./pipeline";

const steps = (...nodes: string[]) => nodes.map((agent) => ({ agent }));
const states = (view: ReturnType<typeof buildPipeline>) =>
  Object.fromEntries(view.map((s) => [s.id, s.state])) as Record<StageId, string>;

describe("buildPipeline", () => {
  it("marks finished stages done and the working one active", () => {
    const view = buildPipeline({
      status: "RUNNING",
      steps: steps("plan", "develop"),
      lastLog: "reviewer: round 1",
    });
    const s = states(view);
    expect(s.plan).toBe("done");
    expect(s.develop).toBe("done");
    expect(s.review).toBe("active");
    expect(s.tests).toBe("pending");
  });

  it("counts loops, e.g. two reviews", () => {
    const view = buildPipeline({
      status: "RUNNING",
      steps: steps("plan", "develop", "review", "revise", "review"),
      lastLog: "tester: writing tests",
    });
    expect(view.find((s) => s.id === "review")?.runs).toBe(2);
    expect(view.find((s) => s.id === "develop")?.runs).toBe(2);
  });

  it("shows a pending approval as a waiting gate", () => {
    const view = buildPipeline({
      status: "PAUSED",
      steps: steps("plan", "develop", "review", "write_tests"),
      pendingKind: "execute",
    });
    expect(states(view).approve_run).toBe("waiting");
  });

  it("puts the fix loop in front when tests are being fixed", () => {
    const view = buildPipeline({
      status: "RUNNING",
      steps: steps("plan", "develop", "review", "write_tests", "approve", "run_tests", "triage"),
      lastLog: "tester: fixing tests, round 1",
    });
    expect(states(view).fix).toBe("active");
    expect(states(view).sandbox).toBe("done");
  });

  it("skips the fix loop when the tests passed the first time", () => {
    const view = buildPipeline({
      status: "SUCCESS",
      steps: steps(
        "plan", "develop", "review", "write_tests", "approve", "run_tests",
        "prepare_commit", "approve_commit", "commit",
      ),
    });
    const s = states(view);
    expect(s.fix).toBe("skipped");
    expect(s.commit).toBe("done");
  });

  it("marks the stage that ended a failed run", () => {
    expect(states(buildPipeline({ status: "FAILED_REVIEW", steps: steps("plan") })).review).toBe(
      "failed",
    );
    expect(states(buildPipeline({ status: "FAILED_TESTS", steps: steps("plan") })).fix).toBe(
      "failed",
    );
    expect(
      states(buildPipeline({ status: "NOT_COMMITTED", steps: steps("plan") })).approve_commit,
    ).toBe("skipped");
  });

  it("an error stops at the stage that was working", () => {
    const view = buildPipeline({
      status: "ERROR",
      steps: steps("plan", "develop"),
      lastLog: "reviewer: round 1",
    });
    expect(states(view).review).toBe("failed");
  });

  it("animates only the connection into the working stage", () => {
    const view = buildPipeline({ status: "RUNNING", steps: steps("plan"), lastLog: "developer: writing files" });
    expect(edgeState(view, 1)).toBe("active");
    expect(edgeState(view, 2)).toBe("pending");
  });
});

it.each([
  ["planner: planning", "plan"],
  ["developer: writing files", "develop"],
  ["developer: revision 1 (2 findings to fix)", "develop"],
  ["developer: fix round 1", "fix"],
  ["executor (e2b): running tests", "sandbox"],
  ["tester: triaging failures", "fix"],
  ["wrote 4 files", undefined],
])("stageFromLog(%s) = %s", (line, stage) => {
  expect(stageFromLog(line)).toBe(stage);
});
