# 0009 Bounded loops and failure triage

- Status: Accepted
- Date: 2026-11-19

## Context
Review and test-fix loops can repeat indefinitely and waste budget. Generated tests can
themselves be wrong.

## Problem
How to stop loops and route test failures correctly.

## Options
1. One shared retry counter.
2. Separate `review_rounds` and `fix_rounds` counters plus a global LLM-call limit, with a
   triage step.
3. No limits; rely on the model to stop.

## Decision
Option 2: each counter at most 2 (configurable), `MAX_LLM_CALLS_PER_RUN`, and triage
classifying each failure as bad code, bad test or environment.

## Reasons
Every run ends in a defined state; fixes go to the right agent instead of changing correct code
to match a wrong test.

## Advantages
Predictable cost; honest outcomes; easier debugging.

## Disadvantages
Some runs stop that one more round might have fixed; triage is itself a model judgement.

## Consequences
`FAILED_REVIEW` and `FAILED_TESTS` are normal outcomes, shown in the report.

## Reconsider when
Benchmark data shows a third round raises the success rate significantly at acceptable cost.
