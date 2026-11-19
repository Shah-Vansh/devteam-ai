# Project Overview

> Status: Phase 0 (planning). Everything below is the agreed design, not yet implemented.

## Problem

AI can generate code quickly, but generated code is hard to trust: it may not run, may be
insecure, may not match the requirement, and usually leaves no record of how it was checked.

## What DevTeam AI does

A user describes a small backend application in plain English. DevTeam AI:

1. Plans it (features, tasks, files, assumptions, open questions).
2. Asks the user to clarify open questions.
3. Generates a Python FastAPI project into an isolated workspace.
4. Runs static analysis and an LLM code review, then revises the code (at most 2 rounds).
5. Generates pytest tests and, after user approval, runs them in a remote microVM sandbox.
6. Triages failures (bad code or bad test) and fixes them (at most 2 rounds).
7. Commits to a local Git repository after user approval.
8. Produces a final report: review status, test results, files, cost and time.

## Version 1 scope

**In scope:** Python + FastAPI generation, pytest tests, static analysis, LLM review, sandboxed
test execution, local Git, one local user, web dashboard.

**Out of scope:** other languages, running generated apps as live servers, user accounts and
roles, pushing to remote Git, Docker / Kubernetes / Redis / queues / microservices, full autonomy,
editing large existing codebases.

## Objectives

- A working, honestly documented system.
- Practical depth in multi-agent orchestration (LangGraph), the Model Context Protocol, sandboxed
  execution, structured LLM output and evaluation.
- Every decision recorded with alternatives and reasons (`docs/TECHNOLOGY_DECISIONS.md`,
  `docs/adr/`).

## Documents

| Document | Contents |
|---|---|
| [SYSTEM_ARCHITECTURE](SYSTEM_ARCHITECTURE.md) | Components, workflow, diagrams |
| [AGENT_DESIGN](AGENT_DESIGN.md) | The four agents, inputs, outputs, prompts |
| [MCP_ARCHITECTURE](MCP_ARCHITECTURE.md) | Filesystem and Git MCP servers, client |
| [EXECUTION_SANDBOX](EXECUTION_SANDBOX.md) | How generated code is run safely |
| [DATABASE_SCHEMA](DATABASE_SCHEMA.md) | Tables and relationships |
| [API_DESIGN](API_DESIGN.md) | REST and SSE endpoints |
| [SECURITY_DESIGN](SECURITY_DESIGN.md) | Threat model and controls |
| [TESTING_STRATEGY](TESTING_STRATEGY.md) | Test levels and tooling |
| [EVALUATION](EVALUATION.md) | Benchmark and metrics |
| [TECHNOLOGY_DECISIONS](TECHNOLOGY_DECISIONS.md) | Stack comparisons |
| [DEVELOPMENT_ROADMAP](DEVELOPMENT_ROADMAP.md) | Phases, milestones, effort, risks |
| [LEARNING_NOTES](LEARNING_NOTES.md) | Concepts learned per phase |
| [GLOSSARY](GLOSSARY.md) | Terms |
| [adr/](adr/) | Architecture Decision Records |
