# API Design

> Status: built in Phase 7 (`backend/app/api/`). Start with `python -m app.api`;
> interactive docs at `http://127.0.0.1:8000/docs`.

Base URL: `http://127.0.0.1:8000` (`BACKEND_HOST`, `BACKEND_PORT`). JSON everywhere except SSE.
v1 has no authentication: it is a single-user tool bound to localhost (documented limitation).

## Endpoints

| Method | Path | Purpose | Success |
|---|---|---|---|
| POST | `/api/projects` | Create a project with a requirement | 201 |
| GET | `/api/projects` | List projects | 200 |
| GET | `/api/projects/{project_id}` | Project detail with its runs | 200 |
| POST | `/api/projects/{project_id}/runs` | Start a run (runs in the background) | 202 |
| GET | `/api/runs/{run_id}` | Status, current agent, counters | 200 |
| GET | `/api/runs/{run_id}/events` | Server-Sent Events progress stream | 200 (stream) |
| GET | `/api/runs/{run_id}/files` | File tree | 200 |
| GET | `/api/runs/{run_id}/files/content?path=` | One file's content (path validated) | 200 |
| GET | `/api/runs/{run_id}/reviews` | Review reports with findings | 200 |
| GET | `/api/runs/{run_id}/tests` | Test runs with cases | 200 |
| GET | `/api/runs/{run_id}/report` | Final report | 200 |
| GET | `/api/runs/{run_id}/approvals` | Pending and past approvals | 200 |
| POST | `/api/approvals/{approval_id}` | Approve or reject | 200 |
| POST | `/api/runs/{run_id}/cancel` | Cancel a run | 202 |
| GET | `/api/runs/{run_id}/archive` | The generated project as a ZIP file | 200 |
| GET | `/api/runs/{run_id}/preview` | State of "Try the API" (`starting`, `running` with URL and expiry, `stopped`) | 200 |
| POST | `/api/runs/{run_id}/preview` | Start the generated app in an E2B sandbox for 10 minutes (only after tests passed) | 200, 409 |
| POST | `/api/runs/{run_id}/preview/stop` | Stop it and delete the sandbox | 200 |
| GET | `/api/usage` | LLM tokens used by this dashboard's runs in the last 24 hours, against `LLM_DAILY_TOKEN_LIMIT` | 200 |
| GET | `/api/health` | Health and active executor | 200 |

## Examples

Create a project:

```http
POST /api/projects
{"name": "task-api", "requirement": "Build a task management API with ..."}
```
```json
{"id": "prj_01", "name": "task-api", "requirement": "Build ...", "created_at": "..."}
```

Start a run:

```http
POST /api/projects/prj_01/runs
```
```json
{"run_id": "run_01", "status": "RUNNING"}
```

Answer an approval:

```http
POST /api/approvals/apr_07
{"decision": "approve"}
```
For a clarification: `{"decision": "approve", "answer": "Users only see their own tasks."}`

SSE events (one JSON object per `data:` line):

```
event: step
data: {"agent": "reviewer", "round": 1, "status": "done", "summary": "3 findings"}

event: approval_required
data: {"approval_id": "apr_07", "kind": "execute"}

event: finished
data: {"status": "SUCCESS"}
```

## As built (Phase 7)

- Runs are executed by `RunManager` (`backend/app/services/run_manager.py`): one asyncio task
  per active run drives the LangGraph graph. After every node the state is synced into the
  database and a `step` event is published. A pause creates a pending approval;
  `POST /api/approvals/{id}` resumes the run from its checkpoint in a new task, so approvals also
  work after the API restarts.
- Run statuses in the API: `RUNNING`, `PAUSED` (waiting for an approval) and the workflow's
  terminal states. Runs left `RUNNING` by a crash are marked `ERROR` at startup.
- Decisions: `{"decision": "approve" | "reject" | "cancel", "answers": [...], "message": "..."}`.
  For a clarification, `reject` keeps the Planner's assumptions; for a commit, `message` replaces
  the proposed commit message.
- SSE events: `log` (progress line), `step` (node finished), `approval_required`,
  `approval_decided`, `finished`. Events carry ids; reconnecting with `Last-Event-ID` resumes. A
  run whose events are no longer in memory (after a restart) is described from the database.
- File endpoints read through the Filesystem MCP server's read-only view, so path rules
  (traversal, device names, ...) are enforced by the same code as for agents.
- `GET /api/health` also reports whether the LLM is configured; starting a run without it gives
  `503 LLM_NOT_CONFIGURED`.
- Every response has an `X-Request-ID` header; unexpected errors log it and return only it.

## Errors

One shape for every error:

```json
{"error": {"code": "RUN_NOT_FOUND", "message": "Run run_99 does not exist", "details": {}}}
```

| Status | Used for |
|---|---|
| 400 | Invalid state (approving an already decided approval) |
| 404 | Unknown project, run, approval or file |
| 409 | Starting a run while one is active for the same project |
| 422 | Request body validation failure (Pydantic) |
| 500 | Unexpected error (details logged, not returned) |

## Concepts covered when this is built

HTTP methods and status codes, REST resource design, request and response models, dependency
injection (database session, settings), middleware (request IDs, CORS), exception handlers,
async endpoints, background execution, SSE.
