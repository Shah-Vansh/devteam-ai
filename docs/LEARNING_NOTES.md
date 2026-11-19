# Learning Notes

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
