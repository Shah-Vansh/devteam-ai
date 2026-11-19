# Progress

| Phase | Status |
|---|---|
| 0 Planning + spikes | Done (2026-11-19) |
| 1 Foundations + Planner | Done (2026-11-19) |
| 2 Filesystem MCP | Done (2026-11-19) |
| 3 Developer + Reviewer | Done (2026-11-19) |
| 4 Execution + Tester | Done (2026-11-19) |
| 5 LangGraph | Done (2026-11-19) |
| 6 Git MCP | Not started |
| 7 Backend + DB | Not started |
| 8 Frontend | Not started |
| 9 Evaluation + hardening | Not started |
| 10 Packaging + portfolio | Not started |

## Phase 5 — LangGraph workflow

Done:

- `app/workflow/`: the run as a LangGraph `StateGraph` with 11 nodes (`plan`, `clarify`,
  `develop`, `review`, `revise`, `write_tests`, `approve`, `run_tests`, `triage`, `fix_code`,
  `fix_tests`). It replaces the Phase 3 and 4 loops (`app/pipeline/` was removed).
- Plain-data `RunState` checkpointed to SQLite after every node (`AsyncSqliteSaver`); live
  dependencies passed as runtime context, so another process can resume a run.
- Human pauses with `interrupt()`: answering the Planner's open questions (answers trigger a new
  plan) and approving test execution; both can cancel the run.
- Code fixed after failing tests goes back through review, as in the architecture diagram;
  test-only fixes go straight back to running tests.
- `guard` turns every node failure into a terminal status; terminal states reachable and tested:
  `TESTS_PASSED`, `FAILED_REVIEW`, `FAILED_TESTS`, `NOT_EXECUTED`, `ERROR`, `CANCELLED`.
- One LLM-call limit and token totals kept in the state, so they survive pauses.
- CLI: `build` (asks at pauses; `--yes` keeps assumptions and approves), `resume <run-id>`,
  `status <run-id>`; answering `later` leaves a run paused.
- 254 tests in total (31 new, loop tests moved onto the graph), no network needed; ruff clean.

Live verification:

| Run | Model | Result |
|---|---|---|
| Todo API: start in one process, paused at approval (the prompt crashed on a Windows quirk), `status` and `resume --yes` in new processes | `gpt-oss-120b` | `TESTS_PASSED`: 9/9 generated tests passed in E2B; 5 LLM calls, about 19,000 tokens; no step redone after resume |
| JWT task API (hard) | `gpt-oss-120b` | `ERROR`: daily token quota used up (clean terminal state, record saved) |
| JWT task API (hard) | `gpt-oss-20b` | `FAILED_REVIEW`: the model could not produce valid JSON for the first file batch, twice |

Issues found and fixed:

- On Windows, input redirected from NUL reports itself as a terminal and then raises EOF at the
  prompt. EOF now leaves the run paused (regression test added).

Not done (by design or carried over):

- A live run of the hard JWT requirement, and a live fix → re-test cycle (quotas); repeat with
  `gpt-oss-120b`.
- Commit step and `SUCCESS` / `NOT_COMMITTED` (Phase 6); API and dashboard pauses (Phases 7–8).
- A developer that cannot produce the first files is reported as `FAILED_REVIEW`; a separate
  development status may be clearer.

## Phase 4 — Execution and the Tester agent

Done:

- `app/execution/`: `CodeExecutor` interface; `E2BExecutor` (fresh microVM, no env vars, pinned
  install, internet off, pytest with JUnit, kill in `finally`); `StaticOnlyExecutor`
  (`NOT_EXECUTED`, never a pass); `junit.py` (defusedxml, size limit); package allow-list and a
  40-pin `constraints.txt` generated inside E2B by `scripts/lock_sandbox_packages.py`.
- `app/agents/tester.py`: writes tests, triages failures (`bad_code` / `bad_test` /
  `environment`), fixes its own tests.
- `app/pipeline/run.py`: develop-and-review, tests, approval, execution, triage and bounded fix
  rounds; one error policy for agent steps; one LLM-call budget for the whole run.
- Static analysis now checks that imported packages are allowed and declared in
  `requirements.txt` (missing file included).
- `python -m app.cli build [--yes] "<requirement>"`: asks before running tests in the sandbox,
  saves `plan.json`, `review-N.json`, `tests-N.json` and `result.json` in `data/runs/`.
- 237 tests in total (56 new), no network needed; ruff clean.

Live verification:

| What | Verified live? |
|---|---|
| E2B executor alone: pinned install, internet off, pytest, JUnit, kill (known app, 4 tests) | Yes: 3 passed, the deliberately wrong test failed with its message, network blocked; 30 s |
| Plan → write → review → 2 revisions → review pass | Yes (`gpt-oss-20b`) |
| Tester → E2B run of generated tests | Yes: e.g. 7 passed, 3 failed in 12.6 s |
| Triage of real failures | Yes: 2 `bad_code`, 1 `bad_test` |
| Fix → re-test → pass | Not yet: the 20b model's fix was rejected as invalid JSON twice (run ended cleanly as `FAILED_TESTS`); then both models' daily quotas were used up. Covered by unit tests; to repeat with `gpt-oss-120b` |

Issues found by live runs and fixed (each with a regression test):

- A model wrote `requirements.txt` as one line with literal `\n` text, so it was a single comment
  and nothing was installed. File content with escaped newlines and no real line breaks is now
  rejected, and the new dependency check flags undeclared imports at review time.
- Triage blamed the "environment" for that missing package; the prompt now says a missing
  allowed package is `bad_code` in `requirements.txt`.
- A plan without `requirements.txt` (twice in a row from the smaller model): the plan schema now
  adds it deterministically; a missing `app/main.py` is still rejected.
- The Developer could not create a missing file during a revision; it can now create
  `requirements.txt`.
- A model re-sent earlier batches' files and the strict batch rule failed the run; re-sent
  planned files are now ignored, files outside the plan are still refused.
- A failed fix (invalid JSON) crashed the run and lost its records; agent failures after review
  now end the run as `FAILED_TESTS` (or `ERROR` for provider outages) with records kept.
- Test results were saved only after triage, so a failed triage lost them; they are saved as
  soon as the run finishes.
- Collection errors had unreadable names and triage spelled them differently; they are named
  `tests/test_x.py::(collection)` and names are matched leniently.
- pytest tried to collect `Tester`, `TestSuite`, `TestCaseResult` and `TestRound` because of
  their names; they are marked `__test__ = False`.

Not done (by design or carried over):

- A complete live fix → re-test → pass cycle (quota); repeat with `gpt-oss-120b`.
- Human approval is a CLI prompt for now; Phase 5 makes it a LangGraph `interrupt()`.
- After a code fix the code is re-tested but not re-reviewed (the diagram goes back through
  review; Phase 5 follows the diagram).

## Phase 3 — Developer, Reviewer and static analysis

Done:

- `app/schemas/code.py` (`CodeChanges`: whole files) and `app/schemas/review.py` (findings,
  report; verdict computed from severities, not chosen by the model).
- `app/analysis/static.py`: Python parser, ruff and bandit on a temporary copy, fixed arguments,
  no shell, isolated from generated config; a failing tool is reported, not fatal.
- `app/analysis/outline.py`: AST outlines (imports, routes, fields, signatures; no bodies).
- `app/agents/developer.py`: generates in batches of 4 files in task order with outlines of
  earlier files; revises only files with findings, others as outlines.
- `app/agents/reviewer.py`: reads through the read-only MCP view, merges static and model
  findings, reviews large projects in parts with outlines of the rest.
- `app/agents/common.py`: `generate_checked` (one corrective retry with the exact problem).
- `app/pipeline/develop.py`: bounded develop-and-review loop with `REVIEW_PASSED` /
  `FAILED_REVIEW`, stop reasons and the per-run LLM call limit.
- `python -m app.cli build "<requirement>"` (or `--plan plan.json`); plan and review reports
  saved to `data/runs/<workspace>/` (git-ignored).
- New settings: `LLM_MAX_OUTPUT_TOKENS`, `LLM_REASONING_EFFORT`.
- 181 tests in total (51 new), no network needed; ruff clean.

Live runs (Groq `gpt-oss-120b`):

| Requirement | Files | Result | LLM calls | Notes |
|---|---|---|---|---|
| Todo API: create, list, mark done, delete (easy) | 5 | `REVIEW_PASSED`, 1 review | 2 (+1 plan) | One medium spec finding (PATCH needs a body instead of toggling) did not block |
| Recipe API with search by ingredient (medium) | 6 | `REVIEW_PASSED`, 1 review | 2 (+1 plan) | `/recipes/search` correctly declared before `/recipes/{id}` |
| Task API with registration, JWT login, per-user tasks (hard) | 8–10 | Not completed | — | Exposed the token-budget problems below. After the fixes, a run did generate, review, revise and re-review; it then stopped on an empty revision (now handled as `FAILED_REVIEW`). The final rerun used up the free tier's daily token quota during the first review. |

Issues found by live runs and fixed (each with a regression test):

- An empty `app/__init__.py` was rejected by the `CodeChanges` schema.
- The Windows console crashed printing a non-breaking hyphen from model output.
- Errors raised inside `async with FilesystemClient(...)` came out wrapped in an
  `ExceptionGroup` by the MCP SDK, so callers could not catch them by type.
- One JSON answer could not hold a 9-file project ("max completion tokens reached"); answers cut
  off at the limit were also retried pointlessly.
- The review request for a 9-file project exceeded the 8,000 tokens-per-minute limit (HTTP 413).
- A Reviewer part rejected a valid finding about an outlined file; now any existing file may be
  cited.
- A Developer that returned no changes crashed the run; it now gets one corrective retry and then
  ends the run as `FAILED_REVIEW` with a reason.

Not done (by design or carried over):

- The hard benchmark requirement has not completed a live run yet (daily quota). Repeat in
  Phase 4 with test execution.
- LLM calls of a failed revision are not counted toward the per-run limit.
- Medium findings do not block a pass.

## Phase 2 — Filesystem MCP server

Done:

- `app/workspace/paths.py`: one set of rules for untrusted paths (relative, `/` only, no `..`,
  hidden entries, drive letters, UNC paths, NTFS streams, Windows device names, forbidden or
  control characters, unknown extensions). The Planner schema now uses the same function.
- `app/workspace/store.py`: create, read, update and list inside `<WORKSPACES_DIR>/<workspace>`,
  with a real-path containment check (symlinks and junctions), size and file-count limits,
  create-only and atomic update, and error messages without host paths.
- `app/mcp_servers/filesystem/`: MCP server (official SDK 2.x `MCPServer`) over stdio with four
  annotated tools and one result shape `{ok, data}` / `{ok: false, error_code, message}`.
- `app/mcp_clients/filesystem.py`: `FilesystemClient` (stdio or in-process) and a
  `ReadOnlyFilesystem` view for agents. Only the needed variables are passed to the server.
- `python -m app.cli fs-demo` starts the server and shows tools and refused attack paths.
- 130 tests in total (92 new), including a real stdio child process; ruff clean.

Issues found and fixed during the phase:

- The installed SDK is MCP 2.x, where `FastMCP` became `MCPServer`; docs updated.
- On Windows, opening a folder as a file raises "permission denied", not "file exists", so the
  folder check now runs before the write.
- `os.walk` lists a folder's files before its subfolders' files; `list_files` now sorts the
  full list.

Not done (by design): server lifecycle inside FastAPI with restart on crash (Phase 7); deleting
files (the workflow does not need it).

## Phase 1 — Foundations and Planner agent

Done:

- `backend/` package (`devteam-backend`) installed in editable mode into the root `.venv`.
- `app/core/config.py`: typed settings from the root `.env`; empty values become "not set";
  relative paths resolve from the repo root; secrets are `SecretStr`.
- `app/core/logging.py`: one JSON object per log line; known secrets are redacted.
- `app/llm/`: `LLMClient` interface, OpenAI-compatible client (Groq), fake client for tests,
  factory that fails fast on missing configuration. Transport errors are retried by the SDK;
  invalid structured output (including Groq's server-side schema rejections) is retried once.
- `app/schemas/plan.py`: `ProjectPlan` with path-safety and consistency validators.
- `app/agents/planner.py` and `prompts/planner_system.md`: Planner agent; requirement passed as
  tagged data; input length checked before any LLM call.
- `python -m app.cli plan "<requirement>"` prints a plan.
- 38 unit tests, no network needed; ruff clean.
- `eval/benchmark.json` (10 requirements) and `eval/run_planner_benchmark.py`.

Benchmark results (2026-11-19, Groq):

| Model | Valid plans | Retries needed | Asked questions | Avg output tokens |
|---|---|---|---|---|
| openai/gpt-oss-120b | 10/10 | 0 | 6/10 (only medium and hard cases) | 1,504 |
| openai/gpt-oss-20b | 8/10 before the retry fix, 10/10 after | 1 | 0/10 | 1,107 |

Decision: `openai/gpt-oss-120b` stays the default for the Planner. It surfaced clarifying
questions exactly where requirements were ambiguous; the 20b model never asked any.

Issues found and fixed during the phase:

- Groq rejects schema-breaking output with HTTP 400 `json_validate_failed`; the client first
  treated this as a hard error (b08 failed on both models). It is now retried like invalid JSON.
- The first prompt discouraged questions so strongly that no model asked any; reworded to allow
  up to three genuinely design-changing questions.

Not done (by design): Developer, Reviewer, Tester agents; database logging of LLM calls
(Phase 7; calls are logged as JSON lines for now).

## Phase 0 — Planning and architecture

Done:

- Design documents in `docs/` and ten ADRs in `docs/adr/`.
- Single root `.env` with `.env.example` template.
- Python 3.14 virtual environment (`.venv`, not committed). Python 3.13 was planned, but its
  local install was broken; all required libraries were confirmed to install on 3.14.
- Spike A (sandbox): pytest ran in an E2B microVM; internet was switched off after package
  installation and confirmed blocked. Details in `docs/EXECUTION_SANDBOX.md`.
- Spike B (structured output): Groq `openai/gpt-oss-120b` and `openai/gpt-oss-20b` returned valid
  `ProjectPlan` objects 12/12 times. Details in `docs/AGENT_DESIGN.md`.
- Spike code was throwaway and removed after its findings were recorded.

Not done (by design): any application code.

Open items carried into later phases:

- Constraints file for sandbox packages (Phase 4).
- Full comparison entries in `TECHNOLOGY_DECISIONS.md`, written as each technology is introduced.
- Benchmark requirements finalised and used to pick the default model (Phase 1).
