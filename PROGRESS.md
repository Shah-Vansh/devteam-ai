# Progress

| Phase | Status |
|---|---|
| 0 Planning + spikes | Done (2026-11-19) |
| 1 Foundations + Planner | Done (2026-11-19) |
| 2 Filesystem MCP | Done (2026-11-19) |
| 3 Developer + Reviewer | Not started |
| 4 Execution + Tester | Not started |
| 5 LangGraph | Not started |
| 6 Git MCP | Not started |
| 7 Backend + DB | Not started |
| 8 Frontend | Not started |
| 9 Evaluation + hardening | Not started |
| 10 Packaging + portfolio | Not started |

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
