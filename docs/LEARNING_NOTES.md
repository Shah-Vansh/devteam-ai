# Learning Notes

## Phase 8 — React dashboard

### Components, props, state
Each screen is a component; data flows down as props (`ApprovalPanel` gets the approval and an
`onDecide` function) and user actions flow back up through those functions. Local `useState`
holds form input; the run itself comes from the API.

### Custom hooks
`useAsync` packages "load, show loading, show error, reload" once. `useRunEvents` packages the
event stream: open, listen, de-duplicate, close. Screens stay about what they show.

### One stream for several tabs
`RunLayout` opens the stream and loads the run once; the Live, Workspace and Report tabs read
them through the router's outlet context. Switching tabs does not reconnect.

### Typed API client
TypeScript interfaces mirror the backend's response models, and every error becomes an
`ApiError` with the API's code, so screens can react to `LLM_NOT_CONFIGURED` or
`RUN_ALREADY_ACTIVE` specifically.

### Tests that use the page like a person
Testing Library finds fields by their label and buttons by their text, like a screen reader. That
is how the badly labelled requirement field was found.

### Checkpoint questions
1. Why does `useRunEvents` close the `EventSource` after `finished`?
2. Why does `RunLayout`, not each tab, own the event stream?
3. What does `useAsync` do to avoid showing an old answer after the screen changed?
4. Why was the requirement field's character counter moved out of its label?

## Phase 7 — Backend API and database

### Two databases, two jobs
LangGraph's checkpoint database is the run's working memory: exact, but opaque. The application
database is the record the API and dashboard query: reviews, findings, test cases, approvals and
LLM calls as rows. A sync after every node copies one into the other, adding only what is missing.

### Background work in a web server
Starting a run returns 202 immediately; an asyncio task drives the graph. A pause ends the task;
approving starts a new task that resumes from the checkpoint. Nothing waits in memory, which is
why approvals survive restarts.

### Server-Sent Events
A one-way stream over plain HTTP: `event:` and `data:` lines. Simpler than WebSockets when only the
server talks. Event ids plus `Last-Event-ID` let a browser reconnect without missing anything.

### Migrations
Alembic turns model changes into versioned scripts. The API applies them at startup, and a test
compares the migrated schema with the models, so a forgotten migration fails the build.

### When cleanup runs
FastAPI runs the code after `yield` in a dependency after the response has been sent. A commit
placed there raced the client's next request. Writes now commit before returning.

### Checkpoint questions
1. Why does starting a run return 202 and not 201 or 200?
2. Why is the run's state stored twice (checkpoint and tables), and which one wins?
3. What happens to a paused run when the API restarts, and to one that was mid-step?
4. Why did committing in the session dependency's cleanup cause `PROJECT_NOT_FOUND`?

## Phase 6 — Git MCP server and commit approval

### Approval as a credential
An approval is turned into a token the Git server can check on its own: signed with a secret only
the backend and that server know (HMAC), for one workspace, one exact set of file contents (a
digest), once (a nonce), soon (an expiry). Each part closes a gap: forgery, reuse, wrong project,
late edits, stale approvals.

### Constant-time comparison
`hmac.compare_digest` takes the same time whether the first or the last character differs, so the
signature cannot be guessed one character at a time by measuring response times.

### Pauses and side effects, again
A paused node runs again from the top on resume. Anything that must reflect "what the human
saw" has to be stored in the state by an earlier node. This was a real design flaw caught before
it shipped, and a test now edits a file during the pause.

### Git is a program with its own ideas
It searches upward for a repository, reads your global config, runs hooks, may convert line
endings and may ask for a signing passphrase. Each of these was switched off or made explicit.

### Checkpoint questions
1. What does each part of the token (signature, workspace, digest, nonce, expiry) protect against?
2. Why is the digest taken in `prepare_commit` and not in `approve_commit`?
3. What would `git status` report in an uninitialised workspace without `--git-dir`, and why?
4. Why does restarting the Git server invalidate every outstanding token?

## Phase 5 — LangGraph workflow

### Nodes, edges, state
A node is a function from state to a partial update. Conditional edges are small functions that
read the state and name the next node. The loops of Phases 3 and 4 became edges plus counters, and
the diagram LangGraph draws is the real flow, not documentation that can drift.

### What goes in the state
Only data that can be saved: dicts, lists, numbers. The LLM client, the MCP connection and the
executor are passed as runtime context on every start and resume. That split is what makes it
possible to resume a run in a different process.

### interrupt() and resume
`interrupt(payload)` stops the run and returns the payload to the caller; the checkpointer keeps
the state. `Command(resume=answer)` continues, and `interrupt()` returns the answer. The paused
node runs again from its first line, so it must do nothing before `interrupt()`.

### Every run ends somewhere defined
A `guard` around each node turns exceptions into statuses, and every router sends a terminal
status to END. Even a provider outage becomes `ERROR` with a reason, not a traceback.

### Live findings
A crashed prompt did not lose the run: the checkpoint held it, and a new process resumed it to
`TESTS_PASSED` (9/9 tests). On Windows, input redirected from NUL claims to be a terminal and then
gives end-of-file; the CLI now treats that as "leave the run paused".

### Checkpoint questions
1. Why are the LLM client and MCP connection not part of the graph state?
2. Why must a node do nothing before calling `interrupt()`?
3. After a code fix the graph goes back to `review`, but after a test-only fix straight to
   `run_tests`. Why the difference?
4. What does a run look like in SQLite while it waits for approval, and what does `resume` do?

## Phase 4 — Execution and the Tester agent

### Interface first, again
The run depends on `CodeExecutor`, not on E2B. The static-only executor makes "no sandbox" an
honest `NOT_EXECUTED`; a fake sandbox in tests records the order of steps so the security
sequence (install, internet off, pytest, kill) is asserted, not assumed.

### Pin everything, where it runs
Pinning top-level packages still lets their dependencies float. A constraints file pins all of
them. It is generated inside the sandbox, because pins resolved on the host's Python 3.14 could
differ from what the sandbox's Python 3.11 needs. One real conflict showed up: passlib needs
bcrypt below 4.1.

### Untrusted output
The test report is written by generated code, so it is size-limited and parsed with defusedxml
(no entity expansion). Test output given to models is delimited data.

### Triage is a routing decision
A failing test means the code is wrong, the test is wrong, or the environment is wrong. Sending
each kind to the right fixer (Developer, Tester, or nobody) is what keeps fix rounds useful.

### Deterministic repair beats asking again
When the fix is certain (add the missing `requirements.txt`), code repairs the output. When it
is not (missing entry point), the output is rejected and the model is asked again.

### One error policy
After review, any agent failure ends the run with a status and keeps the records: a model that
cannot answer → `FAILED_TESTS`, a provider that cannot be reached → `ERROR`.

### Checkpoint questions
1. Why is the constraints file generated inside the sandbox rather than on your machine?
2. In which order do install, internet-off and pytest happen, and why does the order matter?
3. Why does the static-only executor return `NOT_EXECUTED` instead of running static checks and
   calling that a pass?
4. A test fails with `ModuleNotFoundError: fastapi`. Is that bad code, bad test or environment?

## Phase 3 — Developer, Reviewer and static analysis

### Whole files, not diffs
The Developer returns complete files. Diffs are smaller but models often produce patches that do
not apply; complete files are easy to validate (path rules, size, no test files) and to write.

### Validate, then tell the model exactly what was wrong
`generate_checked` runs rules the JSON schema cannot express ("you skipped app/store.py") and asks
once more with that exact problem. Specific feedback fixes most mistakes in one retry; a second
failure is an error, so loops stay bounded.

### The AST as a tool
`ast.parse` turns source into a tree. Walking only the top-level nodes gives an outline: imports,
decorators (FastAPI routes), class fields and function signatures, without bodies. It is about a
third of the size and keeps everything another file needs to use the code.

### Static analysis vs review
Static tools are deterministic, fast and cannot be talked into anything, but they only see local
patterns. The LLM reviewer sees intent ("is the feature in the plan implemented?") but can be
wrong or manipulated. Using both, and computing the verdict from the findings, gets the strengths
of each.

### Severity drives the loop
Only `high` findings block. If every finding blocked, a model can always find something minor
and the loop would never end. Revisions fix high and medium findings together.

### Rate limits are an architectural input
A free tier of 8,000 tokens per minute means a whole multi-file project cannot go into a single
request. Batching, outlines and lower reasoning effort were needed before the hard benchmark
requirement could even be attempted.

### Errors inside `async with`
The MCP SDK runs its connection in a task group. An exception raised inside
`async with FilesystemClient(...)` came out as an `ExceptionGroup`, so `except LLMBudgetExceeded`
never matched. The client now unwraps it; a regression test keeps it that way.

### Checkpoint questions
1. Why is the verdict computed from findings instead of being a field the model fills in?
2. What does an AST outline keep and drop, and why is that enough context for another file?
3. Why do medium findings not block a pass, but still get fixed in a revision?
4. A request was refused with HTTP 413 although each file was small. Why, and what fixed it?

## Phase 2 — Filesystem MCP server

### MCP in one picture
A server declares tools (name, description, JSON schema built from type hints). A client starts
the server, lists the tools, then calls them. Over stdio, the client writes JSON-RPC messages to
the server's stdin and reads replies from its stdout. That is why the server must never print to
stdout: logs go to stderr.

### Separate the rules from the protocol
`app/workspace/` knows nothing about MCP; the server is a thin wrapper. The rules can be tested
directly, and the Planner schema reuses the same path function.

### String checks are not enough
`link/secret.txt` is a perfectly valid string. If `link` is a symlink or junction to another
folder, only resolving the real path reveals the escape. That is why there are two layers.

### Errors as data
Rule violations return `{ok: false, error_code, message}` instead of crashing, so the workflow
(and later an agent) can react to `FILE_EXISTS` or `PATH_ESCAPE`. Messages leave out absolute
host paths, because they may be shown to an LLM.

### Least privilege in code
`ReadOnlyFilesystem` has no write methods at all. A permission that does not exist cannot be
talked into existing by a prompt.

### Atomic writes
Write to a temporary file in the same folder, then `os.replace` it over the target. Readers see
either the old file or the new one, never half of one.

### Checkpoint questions
1. Why must an MCP server that uses stdio never print to stdout?
2. `link/secret.txt` passes every string rule. Which check stops it, and how?
3. Why does `create_file` open with mode `"xb"` instead of checking `exists()` first?
4. What is the difference between a tool returning `ok: false` and an MCP protocol error?

## Phase 1 — Foundations and the Planner agent

### Settings from one `.env`
`pydantic-settings` turns environment variables into a typed object. `Settings` points at the
root `.env` using `Path(__file__).resolve().parents[3]`, so it works no matter which folder a
command is run from. Validators turn empty strings into `None` and make relative paths absolute.
`SecretStr` hides keys in `repr()` and logs; `.get_secret_value()` is needed to use them.

### Interface first: `LLMClient`
Agents depend on a `Protocol` (a description of methods), not on a vendor SDK. Two classes
satisfy it: the real `OpenAICompatibleClient` and `FakeLLMClient` for tests. This is
dependency inversion: high-level code (agents) does not import low-level details (HTTP).

### Two kinds of failure, two kinds of retry
- Transport (timeout, 429, 5xx): the OpenAI SDK retries with backoff.
- Output (JSON that breaks the schema): our client samples again once. Groq reports this as
  HTTP 400 `json_validate_failed`, which looks like a client error but means "bad output" —
  found by the benchmark, not by unit tests.

### Schema vs validators
The JSON schema (field names and types) goes to the model. Rules like "paths must stay inside
the project" or "tasks may only reference planned files" are Pydantic validators that run
after parsing. Both are needed: the schema shapes generation, the validators protect the system.

### Prompt wording changes behaviour
"Only ask if it would change the design... leave empty if none" produced zero questions on all
ten requirements. Naming concrete kinds of ambiguity (authentication, data ownership,
persistence, edge cases) and capping at three gave questions on exactly the ambiguous cases.

### Tests without the network
A stub object imitating `client.chat.completions.parse` lets tests script outcomes (success,
invalid output, provider rejection) and assert retry counts — fast, free and deterministic.

### Checkpoint questions
1. Why does the Planner check the requirement length before calling the model?
2. Where does a 429 rate-limit error get retried, and where does a schema failure get retried?
3. Why is `project_name` normalised instead of rejected?
4. What would you lose if agents called the OpenAI SDK directly?

## Phase 0 — Planning and architecture

### Orchestration vs tool protocol
- LangGraph controls *flow*: which step runs next, with what state, and when to stop or pause.
- MCP controls *tool access*: how a tool is described (name, JSON schema), discovered and called.
- A LangGraph node can be an MCP client. Neither replaces the other.

### Why bounded loops
LLM review and fix loops can go on forever. Two separate counters (`review_rounds`,
`fix_rounds`) plus a global LLM-call limit guarantee every run ends in a clear state.

### Container vs microVM
- A container is an isolated process that **shares the host kernel**. A kernel bug can let code
  escape.
- A microVM has **its own kernel**; escaping needs a hypervisor bug, which is much rarer.
- Spike A showed E2B microVMs start in about 3 seconds, so the stronger isolation costs little.

### Network control in a sandbox
Install pinned packages first, then call `update_network({"allow_internet_access": False})`.
Afterwards both a Python socket and `curl` failed to reach `pypi.org`. Blocked connections wait
for their timeout, so generated tests must never need the network.

### Structured output
Two ways to get JSON from an LLM:
- `json_object`: the model promises valid JSON; the schema is only described in the prompt.
- `json_schema` (strict): the provider constrains output to the schema.
Always validate with Pydantic anyway. In Spike B both modes were valid 12/12 times; the larger
model asked better clarifying questions, the smaller one was about 3x faster.

### Untrusted data
User requirements, LLM output and generated code are all untrusted. Design consequence: the LLM
returns data, and fixed code decides what gets written, executed or committed.

### Single `.env`
Backend reads the root `.env` through a path computed from its own file location; Vite reads it
through `envDir: '..'`; only `VITE_`-prefixed values ever reach the browser.

### Checkpoint questions
1. Why can't a passed review count as passed tests?
2. What would break if the Developer agent could call `create_commit` itself?
3. Why is a microVM safer than a container for running generated code?
4. Why store file metadata in the database but file contents on disk?
