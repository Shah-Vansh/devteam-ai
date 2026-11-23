import { afterEach, describe, expect, it, vi } from "vitest";
import type { api as clientApi } from "../api/client";
import type { Decision } from "../api/types";
import { DEMO_PROJECT_ID, DEMO_RUN_ID, DemoReplay, demoReplay, isDemo, withDemo } from "./demo";
import recording from "./recording.json";

/** A replay with a hand-cranked clock: `tick()` delivers the next event. */
function manualReplay(events = recording.events) {
  const queue: (() => void)[] = [];
  const replay = new DemoReplay(events, (fn) => {
    queue.push(fn);
    return 0 as unknown as ReturnType<typeof setTimeout>;
  });
  const tick = () => queue.shift()?.();
  return { replay, tick, queue };
}

describe("DemoReplay", () => {
  it("delivers events in order and pauses at each approval until approved", () => {
    const { replay, tick } = manualReplay();
    const seen: string[] = [];
    replay.subscribe((e) => seen.push(e.type));
    while (!replay.waiting) tick();
    expect(seen.at(-1)).toBe("approval_required");
    tick(); // nothing scheduled while waiting
    expect(seen.at(-1)).toBe("approval_required");

    replay.approve();
    while (!replay.waiting) tick();
    replay.approve();
    while (!replay.finished) tick();
    expect(seen).toEqual(recording.events.map((e) => e.type));
    expect(seen.filter((t) => t === "approval_required")).toHaveLength(2);
  });

  it("gives late subscribers the history, stamps events with the replay time, and restarts", () => {
    const { replay, tick } = manualReplay();
    replay.subscribe(() => {});
    tick();
    tick();
    const late: string[] = [];
    const reset = vi.fn();
    replay.subscribe((e) => late.push(String(e.data.at)), reset);
    expect(late).toHaveLength(2);
    expect(Date.parse(late[0]!)).toBeGreaterThan(Date.now() - 5000); // not the recorded time

    replay.restart();
    expect(reset).toHaveBeenCalledOnce();
    expect(replay.delivered).toHaveLength(0);
  });
});

describe("withDemo", () => {
  afterEach(() => {
    demoReplay.restart();
    vi.useRealTimers();
  });

  const real = {
    getRun: vi.fn(),
    report: vi.fn(),
    getProject: vi.fn(),
    files: vi.fn(),
    fileContent: vi.fn(),
    reviews: vi.fn(),
    tests: vi.fn(),
    git: vi.fn(),
    decide: vi.fn(),
    cancelRun: vi.fn(),
    startRun: vi.fn(),
    preview: vi.fn(),
    health: vi.fn(),
  };
  const api = withDemo(real as unknown as typeof clientApi);

  it("answers the demo run from the recording and passes other runs on", async () => {
    expect(isDemo(DEMO_RUN_ID) && isDemo(DEMO_PROJECT_ID) && !isDemo("run-1")).toBe(true);
    const run = await api.getRun(DEMO_RUN_ID);
    expect(run.id).toBe(DEMO_RUN_ID);
    expect(["RUNNING", "PAUSED"]).toContain(run.status);
    expect(run.commit_sha).toBeNull(); // not committed until the replay finishes
    expect((await api.getProject(DEMO_PROJECT_ID)).requirement).toBe(recording.project.requirement);

    await api.getRun("run-1");
    await api.health();
    expect(real.getRun).toHaveBeenCalledWith("run-1");
    expect(real.health).toHaveBeenCalled();
  });

  it("follows the replay: files after Develop, a pending approval, the commit at the end", async () => {
    vi.useFakeTimers();
    const advance = async () => {
      await vi.advanceTimersByTimeAsync(2000);
    };
    demoReplay.restart();
    expect(await pending(api.files(DEMO_RUN_ID))).toEqual([]);

    while (!demoReplay.waiting) await advance();
    const paused = await pending(api.getRun(DEMO_RUN_ID));
    expect(paused.status).toBe("PAUSED");
    expect(paused.pending_approval?.kind).toBe("execute");
    expect((await pending(api.files(DEMO_RUN_ID))).length).toBeGreaterThan(0);

    const reject: Decision = { decision: "reject" };
    await expect(api.decide(paused.pending_approval!.id, reject)).rejects.toThrow(/Approve/);
    await pending(api.decide(paused.pending_approval!.id, { decision: "approve" }));

    while (!demoReplay.waiting) await advance();
    const commit = await pending(api.getRun(DEMO_RUN_ID));
    expect(commit.pending_approval?.kind).toBe("commit");
    await pending(api.decide(commit.pending_approval!.id, { decision: "approve" }));
    while (!demoReplay.finished) await advance();

    const done = await pending(api.getRun(DEMO_RUN_ID));
    expect(done.status).toBe("SUCCESS");
    expect(done.commit_sha).toBe(recording.run.commit_sha);
    expect((await pending(api.git(DEMO_RUN_ID))).commits).toHaveLength(1);
    expect((await pending(api.report(DEMO_RUN_ID))).steps).toHaveLength(
      recording.report.steps.length,
    );

    async function pending<T>(promise: Promise<T>): Promise<T> {
      await vi.advanceTimersByTimeAsync(100);
      return promise;
    }
  });

  it("restarts the replay instead of starting a real run", async () => {
    const started = await api.startRun(DEMO_PROJECT_ID);
    expect(started.run_id).toBe(DEMO_RUN_ID);
    expect(real.startRun).not.toHaveBeenCalled();
  });
});
