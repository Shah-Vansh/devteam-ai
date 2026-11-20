# Testing Strategy

> Status: planned. Each phase adds the tests for what it builds.

## Principles

- Tests are deterministic and free: agent tests use recorded LLM responses (fixtures), never
  live calls. A small optional "live" test group is run manually.
- Every security control has a test that tries to break it.
- Test the workflow's routing separately from the agents' content.

## Levels

| Level | What | Tools | Phase |
|---|---|---|---|
| Unit | Settings, schemas, path validation, routing functions, triage logic, token checks | pytest | 1–6 |
| Agent | Each agent with recorded LLM responses; malformed output is rejected | pytest + fixtures | 1–4 |
| MCP integration | Real MCP client ↔ server over stdio; tool discovery and calls | pytest | 2, 6 |
| Executor | `StaticOnlyExecutor` always; `E2BExecutor` with a fake sandbox that records the order of steps (install, internet off, pytest, kill); live checks run by hand | pytest | 4 |
| Workflow | Full graph with a fake LLM; every terminal state reachable; limits enforced; pause/resume | pytest | 5 |
| API | Endpoints against a temporary SQLite database | pytest + FastAPI TestClient | 7 |
| Frontend | Agent-card logic, typed API client, approval panel, event-stream hook (fake `EventSource`), new-project form | Vitest + Testing Library (jsdom) | 8 (built, 28 tests) |
| End-to-end | Create project → run → two approvals (edited commit message) → report; refused start; unknown page. Mocked backend (`page.route`) | Playwright (installed Edge locally, Chromium in CI) | 9 (built) |
| Security | One test per threat control; see the index in [SECURITY_DESIGN](SECURITY_DESIGN.md#security-tests) | pytest | 9 (built) |
| Benchmark | The 10 benchmark requirements end to end, live (Groq, E2B, git) | `eval/run_benchmark.py` | 9 (by hand; needs keys and quota) |

## CI

`.github/workflows/ci.yml` runs on every push and pull request, on Ubuntu:

- **Backend** on Python 3.12 (oldest supported) and 3.14 (development): ruff lint and format
  check, then pytest.
- **Frontend**: `npm ci`, type check (browser and Node code separately), Vitest, production build.
- **End-to-end**: Playwright with Chromium; the HTML report is uploaded when a test fails.

CI needs no secrets: no automated test calls Groq or E2B. Live checks (the benchmark) are run by
hand with real keys.

## Not tested automatically

Output quality of real LLM calls; that is measured by the benchmark in [EVALUATION](EVALUATION.md).
