# Learning Notes

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
