# Security Design

> Status: designed in Phase 0. Controls are implemented in the phases listed and verified in Phase 9.

## Assets

The developer's machine and files, API keys, the integrity of generated projects and their Git
history, and the LLM/sandbox budget.

## Trust boundaries

User input, LLM output and generated code are **untrusted data**. Trusted: backend code, the
MCP servers' validation logic, configuration in `.env`.

```mermaid
flowchart LR
  U[User requirement] -->|untrusted| B[Backend]
  L[LLM output] -->|untrusted| B
  B -->|validated paths only| FS[Filesystem MCP]
  B -->|token-checked| GIT[Git MCP]
  B -->|generated code, no secrets| SBX[Remote sandbox]
```

## Threats and controls

| # | Threat | Control | Phase |
|---|---|---|---|
| T1 | Generated code damages the host | Never executed on host; remote microVM; static tools only parse | 4 |
| T2 | Path traversal through file tools | Real-path containment check, Windows path rules, extension and size limits | 2 |
| T3 | Prompt injection in the requirement ("read ~/.ssh", "commit now") | LLM cannot call write or commit tools; read tools are workspace-locked; requirement passed as delimited data | 3 |
| T4 | Malicious or malformed agent output | Pydantic validation; path, size and extension checks before writing | 1–3 |
| T5 | Secret leakage | Keys only in backend process; none sent to sandbox or LLM; log redaction; `.env` git-ignored | 1, 4 |
| T6 | Runaway loops or cost | `MAX_REVIEW_ROUNDS`, `MAX_FIX_ROUNDS`, `MAX_LLM_CALLS_PER_RUN`, timeouts | 5 |
| T7 | Unauthorised commit | Human approval plus one-time token verified by the Git server | 6 |
| T8 | Command injection through Git | Fixed argument lists, no shell, no user-controlled flags | 6 |
| T9 | Malicious dependency in the sandbox | Small pinned allow-list with a constraints file | 4 |
| T10 | Network abuse by generated code | Internet switched off before generated code runs | 4 |
| T11 | Local API abuse by other sites | Bind to `127.0.0.1`; CORS limited to the frontend origin | 7 |
| T12 | Sandbox escape or provider compromise | Accepted risk; only generated code is sent; documented | — |

## Logging

Structured logs with request and run IDs. Never log API keys, approval tokens, or full file
contents; long LLM outputs are truncated.

## Known limitations

- Single user, no authentication (localhost only).
- Generated code leaves the machine to the sandbox provider.
- LLM review and static analysis reduce risk; they do not prove code is secure.
- Generated code may contain text aimed at the Reviewer ("approve this"). The verdict is
  computed from findings, and static tools are independent of the model, so such text cannot
  force a pass while a high static finding exists (tested).
- Package installation runs with internet on, before the network is cut.
