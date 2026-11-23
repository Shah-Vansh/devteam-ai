import type { Usage } from "../api/types";

export type UsageLevel = "ok" | "low" | "out";

export interface UsageView {
  level: UsageLevel;
  usedPercent: number;
  message: string;
}

/** Turn the token estimate into what the composer shows, or nothing when no daily
 * allowance is configured. "low" means probably not enough left for a typical run. */
export function describeUsage(usage: Usage | undefined): UsageView | undefined {
  if (!usage || !usage.daily_limit || usage.tokens_left === null) return undefined;
  const k = (n: number) => `${Math.round(n / 1000)}k`;
  const typical = usage.typical_run_tokens ?? 20_000;
  const usedPercent = Math.min(100, Math.round((usage.tokens_used / usage.daily_limit) * 100));
  const level: UsageLevel =
    usage.tokens_left < typical * 0.5 ? "out" : usage.tokens_left < typical * 1.5 ? "low" : "ok";
  const runs = Math.floor(usage.tokens_left / typical);
  const message =
    level === "out"
      ? `Only about ${k(usage.tokens_left)} tokens left; a run would likely stop with ERROR. Try again later.`
      : level === "low"
        ? `About ${k(usage.tokens_left)} tokens left: maybe one more run (a run uses about ${k(typical)}).`
        : `About ${k(usage.tokens_left)} tokens left: roughly ${runs} more run${runs === 1 ? "" : "s"}.`;
  return { level, usedPercent, message };
}
