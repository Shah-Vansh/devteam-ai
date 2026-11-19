# Interview Guide

Answers describe what is actually built. Planned parts are labelled as planned.

## Phase 0 — Architecture and decisions

**What is DevTeam AI in one sentence?**
A system where four specialised agents plan, write, review and test a small FastAPI project from
a plain-English requirement, coordinated by a LangGraph workflow, with generated code executed
only in a remote sandbox and a human approving risky steps. (Status: designed; built across
Phases 1–8.)

**Why an orchestrator at all? Why not let agents talk freely?**
Free conversation between agents is unpredictable in cost and outcome. An explicit graph makes
the order, loops, limits and pause points visible and testable.

**Why LangGraph instead of CrewAI or AutoGen?**
I needed bounded loops, conditional routing and human pauses that survive across HTTP requests.
LangGraph gives explicit edges plus `interrupt()` and checkpointers. CrewAI and AutoGen optimise
for quick role-based or conversational agents, with less control over exact flow.

**How is MCP different from function calling?**
Function calling is how a model *asks* for a tool call. MCP is a protocol for how tools are
*hosted, described and discovered* by any client. They work together: an MCP tool's schema can
be offered to a model as a function.

**Why can't the LLM commit code itself?**
Requirements and generated text can contain prompt injection. Writes and commits are performed
by workflow code, commits need human approval and a one-time token checked by the Git server.

**How do you run generated code safely without Docker?**
Each test run gets a fresh E2B microVM. Packages are installed from a pinned list, the internet
is switched off, then pytest runs. I verified in a spike that the network is really blocked
afterwards. Without a sandbox key the system only runs static analysis and reports tests as
not executed.

**Container vs microVM?**
A container shares the host kernel; a microVM has its own kernel, so escaping needs a hypervisor
bug. Stronger isolation for untrusted code.

**How do you prevent infinite agent loops?**
Separate counters for review rounds and fix rounds (two each), a global LLM-call limit per run,
and timeouts. Every run ends in a defined state such as `SUCCESS` or `FAILED_TESTS`.

**Why SQLite? How would you support 10,000 users?**
One local user, zero setup, and SQLAlchemy keeps PostgreSQL a configuration change away. For
10,000 users: PostgreSQL, authentication, a job queue with workers for runs, object storage for
workspaces, several API instances, and Redis for event fan-out.

**What did you verify before writing code?**
Two spikes: E2B can run pytest with internet off (3.2 s to create a sandbox, about 42 s total),
and Groq models produce schema-valid plans (12/12 valid; the larger model asked better
clarifying questions).
