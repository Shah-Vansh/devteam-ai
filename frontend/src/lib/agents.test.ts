import { describe, expect, it } from "vitest";
import { agentCards, agentFromLog, formatTokens, isFinished } from "./agents";

describe("agentFromLog", () => {
  it.each([
    ["planner: planning", "planner"],
    ["developer: revision 1 (2 findings to fix)", "developer"],
    ["reviewer: round 2", "reviewer"],
    ["tester: triaging failures", "tester"],
    ["executor (e2b): running tests", "tester"],
    ["wrote 5 files", undefined],
  ])("%s -> %s", (line, agent) => {
    expect(agentFromLog(line)).toBe(agent);
  });
});

describe("agentCards", () => {
  const steps = [
    { agent: "plan", summary: "plan: todo-api, 5 files" },
    { agent: "develop", summary: "wrote 5 files" },
    { agent: "review", summary: "review 1: changes_needed" },
    { agent: "revise", summary: "updated app/main.py" },
  ];

  it("counts steps per agent and marks the one currently working", () => {
    const cards = agentCards(steps, "RUNNING", "reviewer: round 2");
    expect(cards.map((c) => [c.agent, c.state, c.rounds])).toEqual([
      ["planner", "done", 1],
      ["developer", "done", 2],
      ["reviewer", "working", 1],
      ["tester", "waiting", 0],
    ]);
    expect(cards[2]?.summary).toBe("reviewer: round 2");
    expect(cards[1]?.summary).toBe("updated app/main.py");
  });

  it("nobody is working while the run waits for a human", () => {
    const cards = agentCards(steps, "PAUSED", "tester: writing tests");
    expect(cards.some((c) => c.state === "working")).toBe(false);
  });

  it("marks the agent that ended the run as failed", () => {
    expect(agentCards(steps, "FAILED_REVIEW").find((c) => c.agent === "reviewer")?.state).toBe(
      "failed",
    );
    expect(agentCards(steps, "FAILED_TESTS").find((c) => c.agent === "tester")?.state).toBe(
      "failed",
    );
  });

  it("ignores human pauses and the commit step", () => {
    const cards = agentCards([{ agent: "approve_commit", summary: "" }], "SUCCESS");
    expect(cards.every((c) => c.rounds === 0)).toBe(true);
  });
});

it("knows which statuses are final", () => {
  expect(isFinished("SUCCESS")).toBe(true);
  expect(isFinished("PAUSED")).toBe(false);
  expect(isFinished("RUNNING")).toBe(false);
});

it("formats token counts", () => {
  expect(formatTokens(950)).toBe("950");
  expect(formatTokens(12345)).toBe("12.3k");
});
