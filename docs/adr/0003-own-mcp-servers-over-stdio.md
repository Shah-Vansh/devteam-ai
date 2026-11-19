# 0003 Own MCP servers over stdio

- Status: Accepted
- Date: 2026-11-19

## Context
Agents need controlled file and Git access. Understanding MCP by building servers is a project goal.

## Problem
How tools are exposed to the workflow and agents.

## Options
1. Own MCP servers (official Python SDK) over stdio.
2. Own MCP servers over streamable HTTP.
3. Existing community filesystem and Git MCP servers.
4. Plain Python functions.
5. Custom REST API.

## Decision
Option 1.

## Reasons
Standard discovery and JSON schemas; separate processes isolate file and Git access; stdio needs
no ports or authentication for a local tool; owning the servers gives full control of the
security rules.

## Advantages
Process boundary; reusable by any MCP client; exact control over validation.

## Disadvantages
More code than plain functions; process lifecycle to manage; debugging across processes.

## Consequences
The backend manages server processes in the FastAPI lifespan; servers receive only the
environment they need.

## Reconsider when
Servers must be shared by several machines or users: move to streamable HTTP with authentication.
