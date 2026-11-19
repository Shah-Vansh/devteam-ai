# Glossary

| Term | Meaning |
|---|---|
| ADR | Architecture Decision Record: a short document recording one decision, its options and reasons |
| Agent | Here: one LLM role (Planner, Developer, Reviewer, Tester) with a defined input and validated output |
| Checkpointer | LangGraph component that saves workflow state after each step so a run can pause and resume |
| Conditional edge | A LangGraph edge whose target is chosen by a function reading the state |
| Constraints file | A pip file pinning exact versions of all packages, including indirect ones |
| E2B | Cloud service that runs code in short-lived microVMs |
| Egress | Outbound network traffic from a machine or sandbox |
| MCPServer | High-level server API in the official MCP Python SDK (named FastMCP before 2.0) |
| Junction | Windows folder link that works without admin rights; treated like a symlink |
| Interrupt | LangGraph mechanism that pauses a run until a human provides input |
| JUnit XML | Standard test-result file format that pytest can write |
| MCP | Model Context Protocol: a standard for exposing tools to clients with discovery and JSON schemas |
| microVM | A very small virtual machine with its own kernel, started in seconds; stronger isolation than a container |
| Modular monolith | One deployable application organised into clearly separated modules |
| Node | A step in a LangGraph graph; here usually one agent or one tool action |
| Path traversal | An attack using paths like `../` to reach files outside an allowed folder |
| Prompt injection | Text in user input or data that tries to change an LLM's instructions |
| Reducer | A LangGraph function defining how a state field is updated when nodes write to it |
| SSE | Server-Sent Events: one-way streaming of events from server to browser over HTTP |
| StateGraph | LangGraph's main class: a graph of nodes sharing a typed state |
| stdio transport | MCP client and server communicating through a child process's standard input and output |
| Static analysis | Checking code by reading it, without running it |
| AST | Abstract syntax tree: the parsed structure of source code |
| Outline | A file reduced to imports, signatures, routes and fields (built from the AST) |
| TPM | Tokens per minute: a provider's rate limit on input plus output tokens |
| Verdict | Review result, `pass` or `changes_needed`, computed from finding severities |
| Structured output | LLM output constrained to and validated against a schema |
| Triage | Deciding whether a failing test is caused by the code, the test or the environment |
