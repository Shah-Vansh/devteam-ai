# Evaluation

> Status: planned for Phase 9; the benchmark set is drafted in Phase 1 and used to choose the model.

## Why

Unit tests prove the plumbing works. They do not show whether the system produces working
software. The benchmark measures that, with numbers that can be reported honestly.

## Benchmark set (draft)

Ten fixed requirements, increasing in difficulty:

| # | Requirement | Difficulty |
|---|---|---|
| 1 | Health-check API returning version and time | easy |
| 2 | Todo list CRUD (in memory) | easy |
| 3 | Notes CRUD with SQLite | easy |
| 4 | URL shortener with redirect and click counts | medium |
| 5 | Inventory API with validation and low-stock query | medium |
| 6 | Bookmarks with tags and tag filtering | medium |
| 7 | Task API with registration, login (JWT) and per-user tasks | hard |
| 8 | Library loans with due dates and overdue listing | hard |
| 9 | Expense tracker with categories and monthly totals | hard |
| 10 | Event booking with capacity limits and cancellation | hard |

## Metrics per run

- Terminal status (`SUCCESS`, `FAILED_TESTS`, …).
- Review rounds and fix rounds used.
- Generated tests passed / total.
- LLM calls, input and output tokens.
- Wall-clock time.

## Reporting

`eval/results/<date>-<model>.json` plus a summary table in this file, e.g. "7/10 benchmark
requirements reach SUCCESS with model X". Results are reported as measured, including failures.

## Results so far

### Planner only (Phase 1, 2026-11-19)

Measures valid structured output, not plan quality.

| Model | Valid | Retries | Cases with questions | Avg output tokens |
|---|---|---|---|---|
| openai/gpt-oss-120b | 10/10 | 0 | 6/10 | 1,504 |
| openai/gpt-oss-20b | 10/10 | 1 | 0/10 | 1,107 |

Run with `python eval/run_planner_benchmark.py [--model <id>]`. Latency figures are not
compared: they include waiting on free-tier rate limits.

### Develop and review (Phase 3, 2026-11-19, `gpt-oss-120b`, live)

Spot checks, not the full benchmark (that needs Phase 4 test results).

| Requirement | Files | Result | LLM calls | Notes |
|---|---|---|---|---|
| Todo API: create, list, mark done, delete (easy) | 5 | `REVIEW_PASSED`, 1 review | 2 (+1 plan) | One medium spec finding (PATCH needs a body instead of toggling) did not block |
| Recipe API with search by ingredient (medium) | 6 | `REVIEW_PASSED`, 1 review | 2 (+1 plan) | `/recipes/search` correctly declared before `/recipes/{id}` |
| Task API with registration, JWT login, per-user tasks (hard) | 8–10 | Not completed | — | Exposed the token-budget problems below. After the fixes, a run did generate, review, revise and re-review; it then stopped on an empty revision (now handled as `FAILED_REVIEW`). The final rerun used up the free tier's daily token quota during the first review. |

### Build and test (Phase 4, 2026-11-19, live)

| What | Verified live? |
|---|---|
| E2B executor alone: pinned install, internet off, pytest, JUnit, kill (known app, 4 tests) | Yes: 3 passed, the deliberately wrong test failed with its message, network blocked; 30 s |
| Plan → write → review → 2 revisions → review pass | Yes (`gpt-oss-20b`) |
| Tester → E2B run of generated tests | Yes: e.g. 7 passed, 3 failed in 12.6 s |
| Triage of real failures | Yes: 2 `bad_code`, 1 `bad_test` |
| Fix → re-test → pass | Not yet: the 20b model's fix was rejected as invalid JSON twice (run ended cleanly as `FAILED_TESTS`); then both models' daily quotas were used up. Covered by unit tests; to repeat with `gpt-oss-120b` |

### Workflow (Phase 5, 2026-11-19, live)

| Run | Model | Result |
|---|---|---|
| Todo API: start in one process, paused at approval (the prompt crashed on a Windows quirk), `status` and `resume --yes` in new processes | `gpt-oss-120b` | `TESTS_PASSED`: 9/9 generated tests passed in E2B; 5 LLM calls, about 19,000 tokens; no step redone after resume |
| JWT task API (hard) | `gpt-oss-120b` | `ERROR`: daily token quota used up (clean terminal state, record saved) |
| JWT task API (hard) | `gpt-oss-20b` | `FAILED_REVIEW`: the model could not produce valid JSON for the first file batch, twice |

Free-tier limits (Groq `gpt-oss-120b`): 8,000 tokens per minute and 200,000 tokens per day. A hard
requirement uses roughly 30,000–60,000 tokens per run, so only a few such runs fit in a day.

## Uses

- Choose the default model in Phase 1.
- Compare prompt changes before and after.
- Final numbers for the README.
