# API Design

> Status: designed in Phase 0, built in Phase 7.

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
