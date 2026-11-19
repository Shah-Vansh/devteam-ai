# Interview Guide

Answers describe what is actually built. Planned parts are labelled as planned.

## Phase 2 — Filesystem MCP server

**What is MCP and why build your own server?**
A protocol for exposing tools: a client lists a server's tools with their JSON schemas and calls
them. I built my own server so I control exactly what file access exists: four tools, all locked
to one workspace folder, with my own limits and error codes.

**How do you stop path traversal?**
Two layers. First, string rules before touching the disk: relative paths with `/` only, no `..`,
no drive letters, UNC paths, NTFS streams, hidden files or Windows device names like `CON`.
Second, the real path after following symlinks and junctions must be inside the workspace. The
first catches tricks in the text; the second catches links that look harmless as text.

**Why are Windows device names a security issue?**
`nul.py` or `con.txt` open a device, not a file, whatever the extension. Windows also strips
trailing dots and spaces, so `main.py.` is a different string but the same file.

**What stops a prompt-injected agent from writing files?**
Code, not the prompt. Agents receive a read-only view that has no write methods and rejects
write tool names before anything is sent. Only workflow code holds the full client.

**Why stdio and not HTTP?**
The server is a child process of the backend: no open port, no authentication to design, and it
receives only the environment variables it needs, so API keys never reach it.

**What did testing on Windows find?**
Opening a folder as a file reports "permission denied" on Windows rather than "already exists",
and directory walking returned files in an unsorted order. Both were caught by tests.

## Phase 1 — LLM integration and the Planner

**How do you get reliable structured output from an LLM?**
Strict JSON-schema mode generated from a Pydantic model, then Pydantic validation with extra
rules the schema cannot express, and one retry on failure. On a 10-requirement benchmark the
Planner produced valid plans 10/10 times with `gpt-oss-120b`.

**What happens when the model returns invalid output?**
The client samples again once. If it still fails, it raises `LLMResponseError` and the caller
decides (later: the workflow ends the run in a clear failure state). Network and rate-limit
errors are retried separately by the SDK with backoff.

**What bug did the benchmark catch that unit tests did not?**
Groq validates the schema on its side and returns HTTP 400 when the model's JSON does not
match. My client treated every 400 as fatal, so one hard requirement failed on both models.
I now recognise that specific error as "invalid output" and retry it.

**How do you keep agents provider-independent?**
Agents depend on an `LLMClient` protocol. A factory builds the real client from settings; tests
inject a fake. Changing provider is configuration, not code.

**How do you defend against prompt injection in the requirement?**
The requirement is wrapped in tags and the system prompt says to treat it as data. More
importantly, the Planner can only return a plan; it cannot write files or run anything, and
every path it proposes is validated.

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
