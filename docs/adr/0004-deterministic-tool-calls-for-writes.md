# 0004 Workflow code performs writes and commits

- Status: Accepted
- Date: 2026-11-19

## Context
Agents could call MCP tools themselves through LLM tool calling. Requirements and generated
content may contain prompt injection.

## Problem
Who decides when files are written and commits are made.

## Options
1. The LLM chooses all tools.
2. Workflow code performs writes and commits; the LLM gets read-only tools.
3. No tools for the LLM at all.

## Decision
Option 2.

## Reasons
An injected instruction cannot make the system write outside the plan or commit; behaviour is
predictable and testable; the LLM can still inspect the workspace.

## Advantages
Smaller attack surface; deterministic tests; clear audit trail.

## Disadvantages
Less agent autonomy; the Developer returns full file contents instead of editing incrementally.

## Consequences
Agents return structured data (`CodeChanges`); a workflow node validates and writes it.

## Reconsider when
A later version edits large existing codebases, where incremental edit tools become necessary.
