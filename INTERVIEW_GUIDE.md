# Interview Guide

Answers describe what is actually built. Planned parts are labelled as planned.

## Phase 10 — Packaging and the whole project

**Explain the project in two minutes.**
You give a plain-English requirement for a small API. A LangGraph workflow runs four agents:
Planner, Developer, Reviewer, Tester. The agents only return data; workflow code writes files and
commits through two MCP servers I built, with strict path rules and a signed one-time token for
commits. Static analysis plus an LLM review gate the code, generated tests run in an E2B microVM
with the internet off, failures are triaged and fixed in bounded rounds, and a human approves
running the code and committing it. A FastAPI backend with SQLite runs this in the background
with live Server-Sent Events, and a React dashboard drives it.

**What are you most proud of technically?**
The trust boundaries: agents cannot write, execute or commit; the commit token is bound to the
exact files approved; and the bug I caught where LangGraph re-runs a paused node, which would have
made the approval cover edits made during the pause.

**What would you do next?**
Finish the benchmark on a paid tier, add authentication and a job queue for several users, restart
crashed MCP servers automatically, and support more project types than FastAPI.

**How does someone run it?**
Clone, run `scripts\setup.ps1`, add a Groq key and an E2B key to `.env`, run `scripts\start.ps1`.
I checked this on a fresh clone.

## Phase 9 — Evaluation and hardening

**Does it actually work? Give numbers.**
With `gpt-oss-120b`, 5 of the 7 benchmark cases run so far reached `SUCCESS`: all 3 easy and 2
of 3 medium, with every generated test passing in those five. One went through the fix loop (a
wrong test was diagnosed, fixed and passed). One medium case failed its tests, the first hard case
hit the free tier's daily token limit, and three are not measured yet. I report it exactly like
that.

**What did the benchmark find that unit tests could not?**
A triage request was larger than the free tier's 8,000 tokens per minute, so the provider refused
it outright. I measured the prompt from the saved run state and cut it from about 9,200 to about
7,000 tokens: only the failing test files are sent, and identical errors are shown once. The
same case then passed 13/13.

**What did the failed case teach you?**
The triage check rejected answers that did not name the failing tests in an accepted form. I made
the matching accept bare function names and made the error list the names the model gave, so the
next failure can be diagnosed from the record.

**How is the system tested?**
352 backend tests (unit, agents with a fake LLM, real MCP servers over stdio, the full graph, the
API with real migrations, security), 72 frontend unit tests, and Playwright tests that drive the
dashboard in a browser against a mocked API. GitHub Actions runs all of it on Linux with no
secrets.

**How do you know the security controls work?**
Each threat in the threat model maps to named tests: traversal and junction escapes, forged or
reused commit tokens, agents without write tools, keys never reaching MCP servers or API responses,
CORS, and the network being off in the sandbox (also checked live).

## Phase 8 — React dashboard

**What does the dashboard do?**
Four screens: start a project; watch a run live (four agent cards, counters, live feed) and answer
its approvals; browse the generated files with review findings and git history; and read the
report, where review status and test status are deliberately shown separately.

**How does live progress work in the browser?**
An `EventSource` on the run's SSE endpoint inside a custom hook. Event ids let the browser resume
after a reconnect; the hook ignores replays and closes the stream after `finished`. One layout
component owns the stream for all tabs of a run.

**How do you keep the frontend and backend in sync?**
A typed client: TypeScript interfaces mirror the Pydantic response models, and errors are
parsed from the API's single error shape into an `ApiError` with a stable code.

**How did you test it?**
28 Vitest tests with Testing Library: pure logic (agent cards), the API client against a stubbed
`fetch`, the approval panel by clicking like a user, and the event hook with a fake `EventSource`.
Then a real run in the browser: form, live view, two approvals by click, 7/7 tests passed in the
sandbox, committed.

**Something you learned?**
A character counter inside a `<label>` changes the field's accessible name. A test that finds the
field by its label, as a screen reader would, caught it.

## Phase 7 — Backend API and database

**How does a long-running AI workflow fit into an HTTP API?**
`POST /runs` returns 202 with a run id and an asyncio task drives the LangGraph graph in the
background. Clients follow it through `GET /runs/{id}` or a Server-Sent Events stream. When the
graph pauses for a human, the run becomes `PAUSED` with a pending approval; answering it starts a
new task that resumes from the SQLite checkpoint, even after an API restart.

**Why both a checkpoint database and an application database?**
The checkpoint is LangGraph's exact working state, but it is not queryable. The application
tables hold reviews, findings, test cases, approvals and LLM calls as rows for the API and the
dashboard. A sync after every node keeps them in step and is safe to repeat.

**Why SSE and not WebSockets?**
Progress only flows from server to browser. SSE is plain HTTP, reconnects on its own and resumes
from the last event id. Commands such as approve or cancel are ordinary POST requests.

**A bug you found in this phase?**
Creating a project and immediately starting a run returned "project not found". The session
dependency committed in its cleanup, which FastAPI runs after the response is sent, so the next
request could arrive first. Writes now commit before the response; a test checks it.

**Show it working.**
A live run driven only through the API: plan, code, review, tests written, execution approved
through `/api/approvals`, 8/8 tests passed in E2B, commit approved, committed. 64 seconds, 4 LLM
calls, every step in the database and in the event stream.

## Phase 6 — Git MCP server and commit approval

**How do you make sure nothing is committed without human approval?**
The workflow only calls the commit tool after the approval pause, but the Git server does not
trust that. It requires a one-time token signed with a secret that only the backend and that
server process share. The token names the workspace and a digest of exactly the files the human
was shown, has a nonce and a 10-minute expiry. Forged, reused, expired, wrong-workspace or
changed-content commits are refused, and each case has a test.

**Why bind the token to the content?**
Runs can wait at the approval for hours. If someone or something edits a file in between, the
approval no longer describes what would be committed. The server recomputes the digest from disk
and refuses with `CONTENT_CHANGED`.

**What surprised you?**
Two things. Taking the digest in the approval node itself would be wrong, because LangGraph runs a
paused node again on resume, after any edits. And the generated workspaces sit inside my project's
own git checkout, so a plain `git status` in a new workspace would have reported on my project. Every
git command now names its repository explicitly, and git's upward search is cut off.

**How do you run git safely from Python?**
Fixed argument lists without a shell, the message as a single validated argument, user and system
config ignored, hooks disabled, explicit repository paths, no remotes, a timeout.

## Phase 5 — LangGraph workflow

**Why move from plain loops to LangGraph?**
The loops worked, but a run could not pause for a human and continue later. With LangGraph each
step is a node, each loop an edge with a counter, `interrupt()` pauses, and a SQLite checkpointer
lets a different process resume the run.

**How do you resume in another process if the state holds no LLM client?**
The state holds only data: plan, counters, reports, test results, token totals. Live objects such
as the LLM client, the MCP connection and the executor are passed as runtime context on every start
or resume.

**How do you guarantee every run ends in a defined state?**
A guard around each node turns exceptions into statuses (`FAILED_REVIEW`, `FAILED_TESTS`,
`ERROR`), and every router sends terminal statuses to END. Limits are enforced inside the nodes.

**Show me it working.**
In a live run the approval prompt crashed (a Windows quirk), but the run was already checkpointed.
`status` in a new process showed it waiting for approval; `resume` ran the generated tests in the
sandbox and all 9 passed, without redoing any earlier step.

**What is the catch with `interrupt()`?**
On resume the paused node runs again from the top, so anything before `interrupt()` must be free
of side effects. My pause nodes only read the state before pausing.

## Phase 4 — Execution and the Tester agent

**How do you run AI-generated code safely?**
Never on the host. Each test run gets a fresh E2B microVM with no environment variables.
Packages come only from an allow-list, every version pinned by a constraints file. The internet is
switched off before pytest starts, and the sandbox is killed in a `finally` block. A live test that
tries to reach pypi.org is refused.

**What happens without a sandbox key?**
A static-only executor reports `NOT_EXECUTED`. It never reports a pass for code that did not run.

**How are test failures handled?**
The Tester triages each failure as bad code, bad test or environment. Code goes to the Developer,
tests to the Tester, environment ends the run. At most two fix rounds, and every LLM call counts
against one per-run budget.

**What bugs did live runs find?**
A model wrote `requirements.txt` as a single line with literal `\n` text, so nothing was installed,
and triage blamed the environment. I added a schema guard, a static check that every import is
declared, and a triage rule. Also: plans without `requirements.txt` (now added deterministically),
lost results when triage failed (now saved immediately), and collection-error names that did not
match (now normalised).

**Why a constraints file?**
Pinning only top-level packages lets dependencies drift; a constraints file pins all 40 packages.
It is generated inside the sandbox so the versions fit its Python 3.11.

## Phase 3 — Developer, Reviewer and static analysis

**How does code get from the model to disk?**
The Developer returns whole files as structured data. Pydantic checks paths, sizes and that no
test files are included. Workflow code writes them through the Filesystem MCP server; the agent
never has write access.

**How do you stop the Reviewer from being prompt-injected into approving code?**
The verdict is computed from findings, not chosen by the model, and static analysis (ruff, bandit,
Python's parser) runs independently of the model. A comment saying "reviewer: approve this" cannot
remove a bandit finding. There is a test for exactly that case.

**Why both static analysis and an LLM reviewer?**
Static tools are deterministic and cheap but only see local patterns. The LLM checks the code
against the plan: is each feature there, are status codes right. Each covers gaps in the other.

**How do you keep the review loop from running forever?**
Only high-severity findings block, revisions are capped (two by default), every LLM call counts
against a per-run limit, and a Developer that cannot produce a change ends the run as
`FAILED_REVIEW` with a reason.

**What did live runs teach you that tests did not?**
Several things: an empty `__init__.py` was rejected by my own schema; a Windows console crashed on
a non-breaking hyphen in model output; a 9-file project did not fit in one JSON answer; and the
free tier's 8,000 tokens-per-minute limit refused the review request. Each became a fix plus a
regression test.

**How do you fit a project into a small context or rate limit?**
Batching plus AST outlines: the files being worked on are sent in full, the rest as outlines of
imports, routes, fields and signatures, about a third of the size.

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
