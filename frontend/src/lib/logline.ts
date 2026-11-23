/** How a plain log line (one without an agent prefix) is shown in the terminal. */
export type LogTone = "fail" | "pass" | "info";

const ZERO_COUNTS = /\b(failed|errors?) 0\b/gi;
const FAILURE = /fail|refused|error|no usable/i;

export function logTone(message: string): LogTone {
  // "tests 1: PASSED (passed 8, failed 0, errors 0)" is a pass: zero counts are not failures.
  const text = message.replace(ZERO_COUNTS, "");
  if (FAILURE.test(text)) return "fail";
  if (/\bPASSED\b/.test(text)) return "pass";
  return "info";
}
