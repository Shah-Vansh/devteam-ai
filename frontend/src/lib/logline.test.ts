import { expect, it } from "vitest";
import { logTone } from "./logline";

it.each([
  // Seen live: a passing result was tagged as an error because of "failed 0, errors 0".
  ["tests 1: PASSED (passed 8, failed 0, errors 0, 19.4s)", "pass"],
  ["tests 2: FAILED (passed 4, failed 1, errors 0, 13.6s)", "fail"],
  ["tests 1: ERROR (passed 0, failed 0, errors 1)", "fail"],
  ["write_tests: no usable answer: tester: no valid TestSuite", "fail"],
  ["commit refused: files changed after approval", "fail"],
  ["plan: notes-api, 5 files", "info"],
  ["review 1: pass (high 0, medium 0, low 0)", "info"],
])("logTone(%s) = %s", (message, tone) => {
  expect(logTone(message)).toBe(tone);
});
