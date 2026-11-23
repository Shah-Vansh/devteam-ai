import { expect, it } from "vitest";
import type { Usage } from "../api/types";
import { describeUsage } from "./usage";

const usage = (used: number, typical: number | null = 20_000, limit = 200_000): Usage => ({
  window_hours: 24,
  tokens_used: used,
  daily_limit: limit,
  tokens_left: limit ? Math.max(0, limit - used) : null,
  typical_run_tokens: typical,
});

it("shows nothing without a configured allowance", () => {
  expect(describeUsage(undefined)).toBeUndefined();
  expect(describeUsage(usage(1000, 20_000, 0))).toBeUndefined();
});

it("estimates how many runs are left", () => {
  const view = describeUsage(usage(40_000))!;
  expect(view.level).toBe("ok");
  expect(view.usedPercent).toBe(20);
  expect(view.message).toContain("160k tokens left");
  expect(view.message).toContain("8 more runs");
});

it("warns when about one run is left, and stops encouraging below half a run", () => {
  expect(describeUsage(usage(175_000))!.level).toBe("low");
  const out = describeUsage(usage(195_000))!;
  expect(out.level).toBe("out");
  expect(out.message).toContain("likely stop with ERROR");
});

it("assumes about 20k tokens per run before any run has finished", () => {
  expect(describeUsage(usage(0, null))!.message).toContain("10 more runs");
});
