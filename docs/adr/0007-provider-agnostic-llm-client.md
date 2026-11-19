# 0007 Provider-agnostic LLM client

- Status: Accepted
- Date: 2026-11-19

## Context
Model quality and pricing change often; the free Groq tier is the starting point.

## Problem
How agents call language models.

## Options
1. Call one provider's SDK directly from each agent.
2. A small `LLMClient` interface with provider implementations.
3. A large framework abstraction.

## Decision
Option 2, starting with Groq through its OpenAI-compatible endpoint; default model
`openai/gpt-oss-120b`.

## Reasons
Agents stay unchanged when the provider changes; usage logging and retries live in one place.
Spike B: both Groq models returned valid `ProjectPlan` objects 12/12 times; the 120b model asked
better clarifying questions, the 20b model was about 3x faster.

## Advantages
Swappable; testable with a fake client; one place for token accounting.

## Disadvantages
Provider-specific features need adapting; one more layer.

## Consequences
Strict `json_schema` structured output plus Pydantic validation; model configurable per agent;
final choice made with the benchmark.

## Reconsider when
A required feature exists only in one provider's SDK.
