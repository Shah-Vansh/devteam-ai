# 0001 Modular monolith

- Status: Accepted
- Date: 2026-11-19

## Context
Single-user local tool built by one developer. Components: API, workflow, agents, MCP servers,
executor, frontend.

## Problem
How to structure and deploy the backend.

## Options
1. Modular monolith: one FastAPI process, MCP servers as child processes.
2. Microservices: agents, executor and API as separate services.
3. Serverless functions.

## Decision
Option 1.

## Reasons
One user and one machine; no independent scaling needs; simplest to run, debug and test.

## Advantages
One process to start; in-process calls; shared settings and database session; easy debugging.

## Disadvantages
Everything scales together; a crash in the API process stops running workflows.

## Consequences
Clear module boundaries (`api`, `graph`, `agents`, `execution`, `db`) so parts can be split out later.

## Reconsider when
Runs need to scale independently of the API: move workflows and execution to workers behind a queue.
