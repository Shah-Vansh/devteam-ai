# Database Schema

> Status: designed in Phase 0, built in Phase 7.

## Choices

- **SQLite** via **SQLAlchemy 2.0**, migrations with **Alembic** ([ADR 0006](adr/0006-sqlite-and-alembic.md)).
- Two separate files in `data/`: `devteam.db` (application data) and `checkpoints.db`
  (LangGraph's own checkpoint tables). They have different owners and lifecycles.
- Generated source files stay on disk in `workspaces/<project_id>/`. The database stores only
  metadata (path, SHA-256, size, version), not file contents.

## ER diagram

```mermaid
erDiagram
  PROJECTS ||--o{ RUNS : has
  RUNS ||--o{ AGENT_STEPS : logs
  RUNS ||--o{ GENERATED_FILES : produces
  RUNS ||--o{ REVIEW_REPORTS : has
  REVIEW_REPORTS ||--o{ REVIEW_FINDINGS : lists
  RUNS ||--o{ TEST_RUNS : has
  TEST_RUNS ||--o{ TEST_CASES : lists
  RUNS ||--o{ APPROVALS : needs
  RUNS ||--o{ LLM_CALLS : records
```

## Tables

| Table | Columns | Notes |
|---|---|---|
| `projects` | `id` PK, `name`, `requirement`, `workspace_path`, `created_at` | one project, many runs |
| `runs` | `id` PK, `project_id` FK, `status`, `review_status`, `test_status`, `review_rounds`, `fix_rounds`, `thread_id`, `error`, `started_at`, `finished_at` | `thread_id` links to the LangGraph checkpoint |
| `agent_steps` | `id` PK, `run_id` FK, `agent`, `round`, `status`, `summary`, `started_at`, `finished_at` | progress timeline |
| `generated_files` | `id` PK, `run_id` FK, `path`, `sha256`, `size_bytes`, `version` | metadata only |
| `review_reports` | `id` PK, `run_id` FK, `round`, `verdict` | one per review round |
| `review_findings` | `id` PK, `report_id` FK, `file`, `line`, `severity`, `category`, `message`, `suggested_fix` | |
| `test_runs` | `id` PK, `run_id` FK, `round`, `executor`, `passed`, `failed`, `errors`, `duration_ms`, `triage` | `triage` is JSON |
| `test_cases` | `id` PK, `test_run_id` FK, `name`, `outcome`, `message` | |
| `approvals` | `id` PK, `run_id` FK, `kind` (`clarify` / `execute` / `commit`), `status`, `answer`, `token_hash`, `created_at`, `decided_at` | only a hash of the commit token is stored |
| `llm_calls` | `id` PK, `run_id` FK, `agent`, `model`, `input_tokens`, `output_tokens`, `latency_ms`, `created_at` | cost and usage tracking |

## Indexes

Every foreign key column, plus `runs.status` and `approvals.status` (listing pending approvals).

## Concepts covered when this is built

Primary and foreign keys, one-to-many relationships, normalisation (findings and test cases in
their own tables rather than JSON blobs), transactions (a review report and its findings are
written together), Alembic migrations and schema evolution.

## When to move to PostgreSQL

Multiple users, concurrent runs writing at once, more than one backend instance, or a need for
managed backups. SQLAlchemy keeps the migration mostly to a connection-string change.
