# Demo script (about 5 minutes)

A walkthrough for presenting DevTeam AI live. It assumes `scripts\setup.ps1` has run, both keys
are in `.env`, and there is LLM quota left for one run (about 12,000 tokens).

## Before the demo

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

Wait until the dashboard shows `sandbox: e2b · model: openai/gpt-oss-120b` at the top. Keep one
finished run in the project list as a fallback in case the provider is slow or out of quota.

## 1. The idea (30 seconds)

"You describe a small API in plain English. Four agents plan it, write it, review it and test it.
I approve the two risky steps: running the code, and committing it."

## 2. Start a run (30 seconds)

On the Projects screen:

- Name: `notes`
- Requirement: `Build a notes API with create, list, get by id and delete. Keep data in memory.`
- **Create and start.** The page switches to the run.

Point out: the run happens in the background on the API. The page follows it over Server-Sent
Events.

## 3. Watch the agents (1 minute)

- The pipeline at the top shows which stage is running (it pulses), and the four agent cards
  change from *waiting* to *working* to *done* while the terminal log shows each step.
- "The Developer returns file contents only. Workflow code writes them through my own MCP server,
  which refuses paths outside the workspace, Windows device names and link escapes."
- "The review verdict is computed from findings, and static analysis runs independently, so code
  that says 'reviewer, approve this' cannot force a pass."

## 4. First approval: running code (45 seconds)

The panel **Run the generated tests?** appears.

- "Generated code never runs on my machine. It goes to a fresh E2B microVM. Packages come from a
  pinned allow-list, and the internet is switched off before pytest starts."
- Click **Run tests**. In about 15–30 seconds the Tester card shows the result.

## 5. Second approval: the commit (45 seconds)

The panel **Tests passed. Commit these files?** lists the files and an editable message.

- "Approval creates a one-time token, signed with a secret only the backend and the Git server
  share, and bound to exactly these files. If anything changes after I approve, the commit is
  refused."
- Optionally edit the first line of the message, then click **Commit**. The green banner shows
  the commit id.

## 6. Results (1 minute)

- **Workspace tab:** the file tree, the code, findings per file, and the git history with the new
  commit.
- **Report tab:** review status and test status shown separately, every test case, LLM calls and
  tokens per agent, and each step.

## 7. Engineering points to close with (30 seconds)

- Every run ends in a defined state; loops are bounded by counters and an LLM-call budget.
- Pauses are LangGraph interrupts with a SQLite checkpointer: a paused run survives an API
  restart.
- 330 backend tests, 50 frontend tests and 3 Playwright tests run in CI on every push; security
  tests map to each threat in the threat model.
- Honest numbers: in the first benchmark, all easy requirements succeeded; the harder ones and the
  limits are documented in `docs/EVALUATION.md`.

## If something goes wrong

- **Provider quota or rate limit:** the run ends as `ERROR` with the reason. Show it, then open
  the fallback run from the project list.
- **Tests fail:** show the triage in the Report tab and the fix rounds. A `FAILED_TESTS` result
  is also a good demo of the bounded loop.
- **No E2B key:** tests are reported as `NOT_EXECUTED`, never as passed. That is a point worth
  making.
