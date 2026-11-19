# Learning Notes

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
