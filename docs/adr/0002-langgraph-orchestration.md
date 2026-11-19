# 0002 LangGraph for orchestration

- Status: Accepted
- Date: 2026-11-19

## Context
Four agents with review and fix loops, three human pauses, and runs that must survive waiting
for approval.

## Problem
Which tool coordinates the workflow.

## Options
1. LangGraph.
2. CrewAI.
3. AutoGen.
4. LangChain agent executor.
5. Plain Python orchestration.

## Decision
LangGraph.

## Reasons
Explicit nodes and conditional edges make loops and limits visible and testable. Built-in
`interrupt()` and checkpointers handle human pauses and resume.

## Advantages
Deterministic routing; typed shared state; persistence; good fit for bounded loops.

## Disadvantages
Learning curve; API changes between versions; more ceremony than a plain loop.

## Consequences
Phase 4 builds a plain Python loop first; Phase 5 replaces it with a StateGraph, which also
shows concretely what LangGraph adds.

## Reconsider when
The workflow becomes a fixed linear pipeline, or agents must run across machines.
