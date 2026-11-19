# Evaluation

> Status: planned for Phase 9; the benchmark set is drafted in Phase 1 and used to choose the model.

## Why

Unit tests prove the plumbing works. They do not show whether the system produces working
software. The benchmark measures that, with numbers that can be reported honestly.

## Benchmark set (draft)

Ten fixed requirements, increasing in difficulty:

| # | Requirement | Difficulty |
|---|---|---|
| 1 | Health-check API returning version and time | easy |
| 2 | Todo list CRUD (in memory) | easy |
| 3 | Notes CRUD with SQLite | easy |
| 4 | URL shortener with redirect and click counts | medium |
| 5 | Inventory API with validation and low-stock query | medium |
| 6 | Bookmarks with tags and tag filtering | medium |
| 7 | Task API with registration, login (JWT) and per-user tasks | hard |
| 8 | Library loans with due dates and overdue listing | hard |
| 9 | Expense tracker with categories and monthly totals | hard |
| 10 | Event booking with capacity limits and cancellation | hard |

## Metrics per run

- Terminal status (`SUCCESS`, `FAILED_TESTS`, …).
- Review rounds and fix rounds used.
- Generated tests passed / total.
- LLM calls, input and output tokens.
- Wall-clock time.

## Reporting

`eval/results/<date>-<model>.json` plus a summary table in this file, e.g. "7/10 benchmark
requirements reach SUCCESS with model X". Results are reported as measured, including failures.

## Uses

- Choose the default model in Phase 1.
- Compare prompt changes before and after.
- Final numbers for the README.
