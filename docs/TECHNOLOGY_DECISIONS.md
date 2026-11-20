# Technology Decisions

> Status: final. The selected stack below is what was built; comparisons follow, written as
> each technology was introduced.

## Selected stack

| Area | Choice | Why | Revisit when | ADR |
|---|---|---|---|---|
| Language | Python 3.14 | Best AI ecosystem; all needed libraries install on it (checked in Phase 0) | A key library drops support | — |
| Orchestration | LangGraph | Explicit graph, bounded loops, `interrupt()` and checkpointers built in | Workflow becomes trivial or needs distributed agents | 0002 |
| Tool protocol | Official MCP Python SDK, stdio | Standard discovery and schemas, process isolation, reusable by any MCP client | Tools are only ever used by this app | 0003 |
| LLM | Provider-agnostic client; Groq `openai/gpt-oss-120b` default | Swap providers without touching agents; free tier; valid structured output in spike | Benchmark shows another model is clearly better | 0007 |
| Backend | FastAPI + Pydantic v2 + pydantic-settings | Async, validation, auto docs, typed settings | — | — |
| Database | SQLite + SQLAlchemy 2.0 + Alembic | Zero setup, single user, easy move to PostgreSQL | Multi-user or multi-instance | 0006 |
| Live updates | Server-Sent Events | One-way progress over plain HTTP, auto-reconnect | Two-way interaction needed | 0008 |
| Frontend | React + TypeScript + Vite | Common skills, type safety, no server rendering needed | SEO or server rendering needed | — |
| Static analysis | `ast`, `ruff`, `bandit` | Fast, free, parse without executing | Custom rules needed (Semgrep) | — |
| Execution | E2B microVM behind `CodeExecutor`; static-only fallback | Real isolation without local virtualization; verified in spike | Docker becomes available or self-hosting needed | 0005 |
| Tests | pytest, TestClient, Vitest, Playwright | Standard, fast, good fixtures | — | — |
| Config | One root `.env` | Single source of truth; Vite reads it via `envDir` | Deployment with a secrets manager | 0010 |
| Packaging | `venv` + `scripts/setup.ps1` / `start.ps1` (Windows), `setup.sh` (Linux, macOS) | Native tools only; a fresh clone runs with one command | Hosted or multi-user deployment (containers) | — |
| CI | GitHub Actions | Free, Linux runners | — | — |

## Comparisons completed

### Static analysis (Phase 3)

| Option | Strengths | Weaknesses | Decision |
|---|---|---|---|
| `ast` (standard library) | Exact syntax errors, no install, also used for outlines | Syntax only | Used |
| `ruff` | Very fast, pyflakes and bugbear rules, JSON output | Not a security tool | Used (E9, F, B) |
| `bandit` | Python security rules (shell, eval, secrets, binding) | Some noise (hard-coded "password" strings) | Used |
| pylint | Deep checks | Slow and noisy for generated code | Not used |
| mypy | Type errors | Generated code is often partly typed; many false alarms | Not used |
| Semgrep | Custom cross-language rules | Heavier setup; rules to maintain | Later, if needed |

All three run on a temporary copy of the files with fixed arguments and no shell. They parse code
and never execute it, so running them on the host is safe.

### Dependency pinning in the sandbox (Phase 4)

| Option | Strengths | Weaknesses | Decision |
|---|---|---|---|
| Pin top-level packages only | Simple | Transitive packages float (seen in Spike A) | Not used |
| pip constraints file generated in the sandbox | Pins everything; matches the sandbox's Python; plain pip | Must be regenerated when the allow-list changes | Used |
| `pip-compile` / `uv pip compile` on the host | Good tooling | Host Python 3.14 differs from the sandbox's 3.11, so pins could be wrong | Not used |
| Custom E2B template with packages preinstalled | Fastest runs, no install step | Template build and maintenance; less flexible | Later, if install time matters |

### Parsing test results (Phase 4)

JUnit XML (`pytest --junitxml`) over parsing console output: structured, per-test outcomes and
messages. Parsed with `defusedxml` because the file is produced by untrusted code.

### Workflow engine as built (Phase 5)

| Need | How LangGraph covers it |
|---|---|
| Bounded loops | Conditional edges; counters live in the state and are checked by nodes |
| Human pauses across processes | `interrupt()` + `AsyncSqliteSaver`; resume with `Command(resume=...)` |
| Dependencies that cannot be stored | Runtime context (`context_schema`), passed on each start or resume |
| Inspectable flow | `get_graph().draw_mermaid()` draws the real graph |

The plain-async loops from Phases 3–4 were simpler but could not pause and resume from another
process. One cost: LangGraph's first import takes about 20 s on this machine (bytecode compile),
then about 3 s.

### Orchestration

| Option | Strengths | Weaknesses for this project |
|---|---|---|
| **LangGraph** (chosen) | Explicit graph; bounded loops as edges plus counters; `interrupt()`; checkpointers that survive restarts | More concepts than a plain loop |
| LangChain agents | Quick tool-using agent | The model decides the flow; hard to bound and test |
| CrewAI | Role-based crews out of the box | Less control over exact order, pauses and persistence |
| AutoGen | Conversational multi-agent patterns | Free-form conversation is unpredictable in cost and outcome |
| Plain Python | No dependency; what Phases 3–4 used | Pausing for a human and resuming in another process means writing a checkpointer |

An orchestration framework decides *what runs when*; an agent library decides *how one agent
calls a model and tools*. This project uses LangGraph for the first and its own small agents for
the second.

### Tool integration

| Option | Strengths | Weaknesses |
|---|---|---|
| **MCP over stdio** (chosen) | Standard discovery and JSON schemas; servers run as separate processes with only the environment they need; any MCP client can reuse them | A protocol layer to learn; process start-up cost |
| Direct function calls | Simplest | No process boundary; tools share the backend's secrets and memory |
| LLM function calling | The model picks tools | Gives the model the decision; this project keeps writes in workflow code (ADR 0004) |
| Custom REST service | Familiar | Ports, authentication and schemas to design by hand |

MCP and function calling are not competitors: an MCP tool's schema can be offered to a model as a
function. Here only read-only tools would ever be offered.

### Execution sandbox

| Option | Isolation | Notes |
|---|---|---|
| **E2B microVM** (chosen) | Own kernel per run | Starts in about 3 s; network switch; no local virtualization needed (this machine has none) |
| Modal, Daytona | Containers or VMs, provider-managed | Similar idea; E2B's per-run network switch fit best |
| Docker | Shared host kernel | Not available here (no virtualization); a kernel bug can be an escape route |
| Full VMs | Strong | Slow to start, heavy to manage per run |
| GitHub Actions | Strong, remote | Minutes per run, needs a repository push |
| Local subprocess | None | Generated code would run on the host: ruled out |
| WebAssembly | Strong for pure code | Most Python packages and a real server stack do not run |

### Database

| Option | Strengths | Weaknesses |
|---|---|---|
| **SQLite + SQLAlchemy + Alembic** (chosen) | Zero setup, one file, transactions, foreign keys, WAL | One writer at a time; one machine |
| PostgreSQL | Concurrency, roles, scale | A server to install and run for a single-user tool |
| MySQL | Widely hosted | Same trade-off as PostgreSQL, weaker on some SQL features |
| MongoDB / NoSQL | Flexible documents | The data is relational (runs → reports → findings) and queried by relations |

SQLAlchemy keeps PostgreSQL a configuration change away. Raw SQL would be shorter for a few
queries but loses the typed models and makes migrations manual.

### Backend

| Option | Strengths | Weaknesses |
|---|---|---|
| **FastAPI + Pydantic** (chosen) | Async (needed for SSE and MCP), validation from types, automatic OpenAPI docs | Fewer built-ins than Django |
| Flask | Small and simple | Sync by default; validation and docs by hand |
| Django | Admin, ORM, auth included | Heavy for an API with no server-rendered pages |

Pydantic validation is used everywhere the system meets untrusted data: model output, API
requests, plans. Manual validation would be repeated and easy to get wrong.

### Frontend and live updates

| Option | Strengths | Weaknesses |
|---|---|---|
| **React + TypeScript** (chosen) | Large ecosystem; types catch API mismatches at build time | More setup than a template |
| Vue, Angular | Good frameworks | No advantage here; Angular is heavier |
| JavaScript only | Less setup | API shapes unchecked |
| Polling | Simplest | Delayed updates, wasted requests |
| **SSE** (chosen) | One-way server push over plain HTTP, auto-reconnect, resume by event id | One direction only (commands are normal POSTs) |
| WebSocket | Two-way | Not needed; more to manage |

### Python modelling

| Option | Used for |
|---|---|
| **Pydantic BaseModel** | Anything validated: LLM output, plans, API bodies, settings |
| **TypedDict** | The LangGraph state: plain data that must be checkpointed as-is |
| **dataclass** | Internal value objects without validation (results, dependencies) |
| dict | Only at boundaries (JSON payloads) before validation |

### Infrastructure and testing

- **Background work:** an asyncio task per run inside the API is enough for one user; a job queue
  with workers (Celery, RQ, Arq) is the next step for many users (see the scalability outlook).
- **Local vs distributed:** everything runs on one machine except the sandbox. Docker Compose or
  Kubernetes would matter only for a hosted, multi-user version.
- **pytest vs unittest:** pytest's fixtures, parametrisation and plain `assert` keep 329 tests
  short; unittest would add boilerplate.

## Scalability outlook

| Stage | Change | Trigger |
|---|---|---|
| Local prototype | As designed | — |
| Small team | Authentication, PostgreSQL, per-user workspaces | More than one user |
| 10,000 users | Job queue and workers, object storage for workspaces, several API instances, Redis for SSE fan-out | Runs block the API or one machine is too slow |
| Many executors | Executor pool, per-user sandbox quotas and cost caps | Sandbox concurrency limits |
| Enterprise | SSO, roles, audit logs, self-hosted sandboxes, observability stack | Compliance requirements |
