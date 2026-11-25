# Evaluation

> Status: all 10 benchmark cases measured (below): 5/10 `SUCCESS`; easy 3/3, medium 2/3, hard 0/4.

## Why

Unit tests prove the plumbing works. They do not show whether the system produces working
software. The benchmark measures that, with numbers that can be reported honestly.

## Benchmark set

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

## End-to-end benchmark (2026-11-20 to 2026-11-25): all 10 cases

Each case runs the real workflow: Groq `gpt-oss-120b` (reasoning effort low) for the agents,
E2B for the tests, a real local commit. Pauses are approved automatically. Code:
`backend/app/evaluation/benchmark.py`, runner `eval/run_benchmark.py`, raw results
`eval/results/2026-11-20-e2e-openai_gpt-oss-120b.json`. The free tier allows 200,000 tokens per
day and 8,000 per minute, so the cases ran over three days; fixes made between runs are listed
below with the case that exposed them.

| Case | Difficulty | Status | Review rounds | Fix rounds | Tests | LLM calls | Tokens | Time |
|---|---|---|---|---|---|---|---|---|
| b01 health check | easy | SUCCESS | 0 | 0 | 5/5 | 4 | 8,046 | 21 s |
| b02 todo CRUD | easy | SUCCESS | 0 | 0 | 10/10 | 5 | 16,167 | 118 s |
| b03 notes with SQLite | easy | SUCCESS | 0 | 0 | 11/11 | 5 | 19,674 | 121 s |
| b04 URL shortener | medium | FAILED_TESTS | 0 | 2 | 6/7 | 9 | 29,953 | 226 s |
| b05 inventory | medium | SUCCESS | 0 | 0 | 13/13 | 5 | 19,637 | 99 s |
| b06 bookmarks with tags | medium | SUCCESS (after a fix round) | 1 | 1 | 6/6 | 9 | 31,700 | 207 s |
| b07 tasks with JWT login | hard | FAILED_REVIEW | 2 | 0 | — | 13 | 66,699 | 448 s |
| b08 library loans | hard | ERROR (request over 8,000 tokens/minute) | 0 | 0 | — | 3 | 12,081 | 68 s |
| b09 expense tracker | hard | ERROR (request over 8,000 tokens/minute) | 0 | 0 | — | 4 | 15,976 | 75 s |
| b10 event booking | hard | FAILED_REVIEW | 2 | 0 | — | 11 | 42,851 | 276 s |

**Headline (as measured): 5 of 10 reached `SUCCESS`: easy 3/3, medium 2/3, hard 0/4.** In the
five successes every generated test passed (45/45). b06 and b04 show the fix loop working
(triage blamed the tests, the Tester fixed them, the re-run improved); b04 still had one
failing test after the two allowed rounds. No hard case succeeded on the free tier.

### What each failure showed, and what changed

- **b04, first run (2026-11-20):** triage did not name the failing tests in a form the check
  accepted. Bare function names are now accepted. Re-run on 2026-11-25: 5/7 → 6/7 → 6/7 over
  two fix rounds, ending as `FAILED_TESTS`: the loop is bounded and says so.
- **b05, first two attempts:** one triage request was larger than 8,000 tokens per minute
  (HTTP 413, 8,497 and 9,223 tokens). Triage and test fixes now get only the failing test files,
  and failure messages share a budget with identical errors shown once (about 9,200 → 7,000
  tokens on that run's saved state). Then 13/13.
- **b07 and b10 (`FAILED_REVIEW`): mostly false alarms from the Reviewer, found by reading the
  saved review reports against the generated files.** Large projects are reviewed in parts;
  files outside a part are shown as outlines. The outlines wrote every function body as `: ...`
  and dropped module-level calls, so complete files looked unfinished: the Reviewer reported
  "all task routes are placeholders" and "main.py never includes the routers", while `tasks.py`
  had five working routes and `main.py` included both routers and created the tables. With 10
  such high findings, two revisions could not satisfy it. Changes:
  - outlines label omitted bodies (`# body not shown: 6 lines`), say when a value is shortened,
    and keep module-level calls such as `app.include_router(...)`;
  - a finding about a file the Reviewer saw only as an outline is capped at medium and marked
    "(seen in an outline)". Every file is still reviewed in full in its own part, where a real
    problem keeps its severity.

  Checked live by reviewing b07's saved code again with the model: 1 high finding instead of
  10, and that one is real (`Field(..., env="JWT_SECRET_KEY")` makes the settings required and
  Pydantic v2 ignores `env=`, so the app fails at start-up without `APP_JWT_SECRET_KEY`). b07 and
  b10 have not been re-run end to end since.
- **b08 and b09 (`ERROR`):** a review request came to 8,056 and 8,089 tokens, just over the
  per-minute limit. The Reviewer now has its own smaller full-text budget (5,500 characters,
  numbered lines cost more tokens), and the plan is sent as compact JSON in every request
  (800–1,000 characters less for these plans). Estimated on their saved state, calibrated on
  the provider's own counts: about 7,500 tokens. Not yet re-run.
- **Runner:** a 413 was treated like a quota error and stopped the benchmark, so b09 and b10 did
  not run at first. Only rate limits (HTTP 429) now stop it or are redone by `--resume`.

### Next measurement

Re-run the hard cases with the fixes above when the daily quota allows (15,000–67,000 tokens
per hard case so far, so spread them over two days):

```powershell
cd backend
..\.venv\Scripts\python.exe ..\eval\run_benchmark.py --only b07,b08,b09,b10 --reasoning-effort low
```

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

### Commit (Phase 6, 2026-11-20, live)

| Check | Result |
|---|---|
| Commit through the real Filesystem and Git MCP servers (child processes) on the Phase 5 todo project (9/9 tests passed), which lives inside this project's own checkout | Status before init `NOT_A_REPOSITORY`; commit without token refused; commit with the approved token created `de4565cef9` (12 files, author DevTeam AI); reused token refused (`TOKEN_USED`); working tree clean; the outer repository's status unchanged |
| Full run to a commit with an LLM (`gpt-oss-120b`, then `gpt-oss-20b`) | Not completed: both daily token quotas were used up mid-run. Both runs ended cleanly as `ERROR` with records saved |

### API (Phase 7, 2026-11-20, live)

| Check | Result |
|---|---|
| API startup | Migration `0001` applied to `data/devteam.db`; Filesystem and Git MCP servers started; `/api/health`: executor e2b, model gpt-oss-120b, git available |
| Run driven over HTTP (todo API, `gpt-oss-120b`) | `SUCCESS` in 64 s: plan, develop, review (pass), tests written, execution approved via `/api/approvals`, E2B 8/8 passed, commit approved, commit `234e7e8`; 4 LLM calls, about 12,000 tokens |
| Database after the run | Run, 2 approvals (commit row holds only a token hash), test run with 8 cases, 6 tracked files, 4 LLM-call rows, 9 agent steps |
| Event stream | 11 `log`, 9 `step`, 2 `approval_required`, 2 `approval_decided`, 1 `finished` |

### Dashboard (Phase 8, 2026-11-20, live)

| Check | Result |
|---|---|
| Dashboard against the real API (Vite dev server and `python -m app.api`) | Project list with earlier runs and their statuses; health line (e2b sandbox, model) |
| New run started from the form and approved by clicking (notes API, `gpt-oss-120b`) | Live: SSE connected, agent cards switched to *working* and *done*, approval panels for execution and commit. `SUCCESS`: E2B 7/7 tests passed, commit `ac22432`, 4 LLM calls, about 11,000 tokens |
| Workspace and Report tabs | File tree with finding counts, code viewer, git status and history; review and test status shown separately, every test case, LLM usage per agent, steps |
| Narrow window and dark mode | Agent cards in two columns; dark theme readable |

Free-tier limits (Groq `gpt-oss-120b`): 8,000 tokens per minute and 200,000 tokens per day. A hard
requirement uses roughly 30,000–60,000 tokens per run, so only a few such runs fit in a day.

## Uses

- Choose the default model in Phase 1.
- Compare prompt changes before and after.
- Final numbers for the README.
