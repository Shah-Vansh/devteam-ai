# Technology Decisions

> Status: Phase 0. Each row is expanded into a full entry (what, problem, how it works, where
> used, pros, cons, limits, alternatives, when alternatives win, scale outlook) in the phase
> where the technology is first used.

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
| Packaging | `venv` + PowerShell scripts | Native on Windows | Linux deployment (containers) | — |
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

## Comparisons to be completed

Orchestration: LangGraph vs LangChain agents vs CrewAI vs AutoGen vs plain Python.
Orchestration framework vs agent library.

Tool integration: MCP vs direct function calls vs LLM function calling vs custom REST.

Execution: E2B vs Modal vs Daytona vs Docker vs VMs vs GitHub Actions vs local subprocess vs
WebAssembly; container vs microVM isolation.

Databases: SQLite vs PostgreSQL; PostgreSQL vs MySQL; SQL vs NoSQL; MongoDB vs relational.

Backend: FastAPI vs Flask vs Django; Pydantic vs manual validation.

Frontend: React vs Vue vs Angular; JavaScript vs TypeScript; polling vs SSE vs WebSocket.

Python modelling: TypedDict vs Pydantic BaseModel vs dataclass vs dict.

Infrastructure: synchronous vs background workers; local vs distributed execution; Docker Compose
vs Kubernetes.

Testing and data access: pytest vs unittest; SQLAlchemy vs raw SQL.

## Scalability outlook

| Stage | Change | Trigger |
|---|---|---|
| Local prototype | As designed | — |
| Small team | Authentication, PostgreSQL, per-user workspaces | More than one user |
| 10,000 users | Job queue and workers, object storage for workspaces, several API instances, Redis for SSE fan-out | Runs block the API or one machine is too slow |
| Many executors | Executor pool, per-user sandbox quotas and cost caps | Sandbox concurrency limits |
| Enterprise | SSO, roles, audit logs, self-hosted sandboxes, observability stack | Compliance requirements |
