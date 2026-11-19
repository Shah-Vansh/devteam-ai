# 0006 SQLite with SQLAlchemy and Alembic

- Status: Accepted
- Date: 2026-11-19

## Context
One local user; the data is relational (projects, runs, findings, tests).

## Problem
Database and access layer for v1.

## Options
1. SQLite + SQLAlchemy + Alembic.
2. PostgreSQL.
3. MongoDB.
4. Raw SQL with `sqlite3`.

## Decision
Option 1.

## Reasons
No server to install; transactional; SQLAlchemy keeps a later move to PostgreSQL mostly a
configuration change; Alembic versions the schema.

## Advantages
Zero setup; single file; easy throwaway test databases.

## Disadvantages
One writer at a time; no network access; fewer features than PostgreSQL.

## Consequences
Application data and LangGraph checkpoints live in separate files under `data/`; file contents
stay on disk.

## Reconsider when
Multiple users, concurrent writes, or more than one backend instance.
