# Agent Design

> Status: designed in Phase 0. Planner structured output verified in a Phase 0 spike.

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

## Prompting approach

- System prompt per role, stored as versioned files in `backend/app/agents/prompts/`.
- User content (the requirement, generated code) is passed as clearly delimited data, never
  mixed into instructions (prompt-injection defence).
- Revision prompts include only the relevant findings or failures, not the whole history.

## Known limitations

- LLM review can miss bugs and security issues; static analysis and tests reduce but do not
  remove this.
- Code quality depends heavily on the model; small free models may fail multi-file apps.
