# Agent Design

> Status: Planner built in Phase 1; Developer and Reviewer in Phase 3; Tester and triage in Phase 4.

## Principles

- Each agent is one LLM role with a defined input and a **validated Pydantic output**. They are
  deliberately not free-roaming autonomous agents: predictable structure beats autonomy here.
- Agents never write files or commit. They return data; workflow code performs writes through the
  Filesystem MCP server and commits through the Git MCP server ([ADR 0004](adr/0004-deterministic-tool-calls-for-writes.md)).
- Agents may use **read-only** MCP tools (`read_file`, `list_files`).
- Every LLM call is logged (model, tokens, latency) to the `llm_calls` table.

## Agents

| Agent | Input | Output model | Notes |
|---|---|---|---|
| Planner | requirement text, clarification answers | `ProjectPlan` | features, tasks, files, assumptions, open questions, complexity |
| Developer | plan, plus review findings or test failures on revision | `CodeChanges` | list of `{path, content, reason}` |
| Reviewer | files, plan, static-analysis report | `ReviewReport` | findings `{file, line, severity, category, message, suggested_fix}`, verdict `pass` / `changes_needed` |
| Tester | files, plan | `TestSuite` | pytest files |
| Tester (triage) | test results, files, tests | `FailureTriage` | per failure: `bad_code`, `bad_test` or `environment`, with reason |

## Structured output (Phase 0 spike result)

Spike B asked Groq `openai/gpt-oss-120b` and `openai/gpt-oss-20b` for a `ProjectPlan` on three
requirements, in two modes:

| Model | Mode | Valid | Typical latency | Output tokens | Open questions |
|---|---|---|---|---|---|
| gpt-oss-120b | `json_schema` (strict, provider-enforced) | 3/3 | 2.6–3.8 s | 1,100–1,600 | 4–5 |
| gpt-oss-120b | `json_object` + Pydantic | 3/3 | 1.9–5.7 s | 600–1,000 | 3–5 |
| gpt-oss-20b | `json_schema` | 3/3 | 0.9–1.6 s | 500–1,100 | 0–3 |
| gpt-oss-20b | `json_object` + Pydantic | 3/3 | 1.0–1.1 s | 520–570 | 0–4 |

Findings:

- Both models produced schema-valid output 12/12 times. Sample size is small; this is a
  feasibility check, not a benchmark.
- The 20b model sometimes asked **no** open questions for an ambiguous requirement (login and
  registration), so it guesses more. The 120b model consistently surfaced real questions.
- Decision for Phase 1: use strict `json_schema` mode and still validate with Pydantic; default
  to `gpt-oss-120b`; consider `gpt-oss-20b` for cheap steps such as triage. Final choice is made
  with the benchmark ([EVALUATION](EVALUATION.md), [ADR 0007](adr/0007-provider-agnostic-llm-client.md)).

## Planner (built in Phase 1)

- Code: `backend/app/agents/planner.py`, prompt `backend/app/agents/prompts/planner_system.md`,
  schema `backend/app/schemas/plan.py`.
- Input: requirement (1–4,000 characters) and optional clarification answers, wrapped in
  `<requirement>` / `<clarifications>` tags.
- Output: `ProjectPlan` — `project_name` (normalised to a slug), `summary`, `features`, `files`
  (application files only, at most 20, safe relative paths with allowed extensions), `tasks`
  (unique ids, only referencing planned files), `dependencies`, `assumptions`,
  `open_questions` (at most a few, only design-changing), `complexity`.
- Validation happens twice: the provider enforces the JSON schema, then Pydantic validators
  enforce rules a schema cannot express. A failure is retried once.

Benchmark (10 requirements, Groq, 2026-11-19): `gpt-oss-120b` 10/10 valid, asked questions on
6/10 (none on the easy, fully specified cases); `gpt-oss-20b` 10/10 valid after the retry fix,
asked none. Default: `gpt-oss-120b`. Full results in `eval/results/`.

## Developer (built in Phase 3)

- Code: `backend/app/agents/developer.py`, prompt `prompts/developer_system.md`, schema
  `backend/app/schemas/code.py` (`CodeChanges`: whole files `{path, content, reason}`, never
  diffs; same path rules as the plan; no test files; empty content only for `__init__.py`).
- **Generate:** planned files are written in task order, at most 4 per LLM call. Each call sees
  the plan and **AST outlines** of files already written (imports, routes, classes, fields and
  signatures, no bodies), so names stay consistent while requests stay small. A call must return
  exactly the requested files; otherwise it is asked once more with the exact problem.
- **Revise:** receives findings of severity high and medium. Only files with findings are sent
  in full (in size-limited batches); the rest of the project is sent as outlines. It may only
  change the files shown in full. Returning nothing, or only unchanged files, gets one corrective
  retry; after that the run ends as `FAILED_REVIEW` with a reason.
- The Developer never writes. Workflow code writes its output through the Filesystem MCP server.

## Reviewer (built in Phase 3)

- Code: `backend/app/agents/reviewer.py`, prompt `prompts/reviewer_system.md`, schemas in
  `backend/app/schemas/review.py`.
- Reads the workspace through `ReadOnlyFilesystem` (the agent view of the Filesystem MCP server),
  so it cannot change what it judges.
- Runs static analysis first (`backend/app/analysis/static.py`): Python's parser for syntax
  errors, `ruff` (E9, F, B rules; `B008` ignored for FastAPI `Depends`) and `bandit` for
  security. Tools run on a temporary copy, with fixed arguments, no shell and `--isolated`, so a
  generated config file cannot switch rules off. A tool that fails is reported, not fatal.
- Then asks the model, with files numbered by line. Large projects are reviewed in parts of about
  8,000 characters of full text; each part also sees outlines of the other files.
- Findings: `{file, line, severity (high/medium/low), category (bug/security/spec/quality),
  message, suggested_fix}`, plus `source` (`reviewer`, `python`, `ruff`, `bandit`) in the report.
  Every cited file must exist in the project.
- **The verdict is computed, not chosen by the model:** `changes_needed` if any finding is high,
  otherwise `pass`. A comment in generated code telling the reviewer to approve cannot override
  an independent static finding.

## Develop-and-review loop (Phase 3; becomes a LangGraph graph in Phase 5)

Code: `backend/app/pipeline/develop.py`.

1. Developer generates; files are written through MCP.
2. Reviewer reviews. `pass` → `REVIEW_PASSED`.
3. `changes_needed` and `review_rounds < MAX_REVIEW_ROUNDS` → Developer revises (high and medium
   findings), files are updated, back to 2.
4. Otherwise → `FAILED_REVIEW`, with a stop reason.

Every LLM call counts against `MAX_LLM_CALLS_PER_RUN`. `python -m app.cli build "<requirement>"`
runs plan → develop → review and saves the plan and each review report to `data/runs/<workspace>/`
(git-ignored).

## Tester (built in Phase 4)

- Code: `backend/app/agents/tester.py`, prompt `prompts/tester_system.md`, schemas in
  `backend/app/schemas/testing.py`.
- **Write tests:** plan plus app files (full text up to a budget, outlines for the rest) →
  `TestSuite`: files directly under `tests/` only (`test_*.py`, `conftest.py`, `__init__.py`),
  at most 6. pytest with FastAPI `TestClient`, state reset between tests, no network.
- **Triage:** after a failed run, each failing test is classified `bad_code` (must name an app
  file), `bad_test` (must name a test file) or `environment`, with a reason and a fix. Every
  failure shown must be classified; test names are matched leniently (`tests.test_a.test_x`,
  `tests/test_a.py::test_x` and a bare module for collection errors are the same test).
- **Fix tests:** rewrites only test files, for `bad_test` items.

## Build-and-test run (Phase 4; becomes a LangGraph graph in Phase 5)

Code: `backend/app/pipeline/run.py`. After develop-and-review passes:

1. Tester writes tests (written through MCP into `tests/` of the workspace).
2. Human approval before execution (CLI prompt; `--yes` to skip).
3. Packages from `requirements.txt` are checked against the allow-list. Unknown names go back to
   the Developer as a finding (a fix round); they are never installed.
4. Executor runs the tests. `PASSED` → `TESTS_PASSED`; `NOT_EXECUTED` → `NOT_EXECUTED`;
   `ERROR` (install, timeout, sandbox) → `ERROR`.
5. `FAILED` and `fix_rounds < MAX_FIX_ROUNDS` → triage → `bad_code` to the Developer, `bad_test`
   to the Tester (both in one round if needed); only `environment` → `FAILED_TESTS`.
6. Limit reached → `FAILED_TESTS`.

One error policy for every agent step after review: a model that cannot give a usable answer
ends the run as `FAILED_TESTS`; a provider that cannot be reached (or a used-up quota) is
`ERROR`. Rounds recorded so far are kept. One `LLMBudget` counts calls across all stages.
`SUCCESS` and `NOT_COMMITTED` arrive with the Git commit in Phase 6.

## Fitting a small token budget

Groq's free tier allows 8,000 tokens per minute for `gpt-oss-120b`, and a single request larger
than that is refused (HTTP 413). Found in live runs, handled by:

- batching the Developer (4 files per call) and the Reviewer (about 8,000 characters per call);
- sending other files as AST outlines (about a third of their full size);
- `LLM_REASONING_EFFORT=low` for gpt-oss, which spends fewer output tokens on hidden reasoning;
- `LLM_MAX_OUTPUT_TOKENS` to set the answer limit explicitly; an answer cut off at the limit is
  not retried (it would be cut off again) and fails with a clear message;
- the SDK waiting and retrying when the per-minute limit is hit (runs get slower, not broken).

## Prompting approach

- System prompt per role, stored as versioned files in `backend/app/agents/prompts/`.
- User content (the requirement, generated code) is passed as clearly delimited data, never
  mixed into instructions (prompt-injection defence).
- Revision prompts include only the relevant findings or failures, not the whole history.

## Known limitations

- LLM review can miss bugs and security issues; static analysis and tests reduce but do not
  remove this.
- Medium findings do not block a pass, so a review can pass with a known medium issue (seen
  live: a spec mismatch rated medium). Only high findings force a revision.
- The Reviewer can be wrong in both directions; a high finding that the Developer disputes
  ends the run as `FAILED_REVIEW`. Tests in Phase 4 give an independent signal.
- On the free tier a large project takes several minutes because of per-minute token limits.
- Code quality depends heavily on the model; small free models may fail multi-file apps.
