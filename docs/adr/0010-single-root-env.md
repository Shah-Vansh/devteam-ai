# 0010 One shared root .env

- Status: Accepted
- Date: 2026-11-19

## Context
Backend, MCP servers and frontend all need configuration.

## Problem
Where configuration lives.

## Options
1. One `.env` at the repo root for everything.
2. Separate `backend/.env` and `frontend/.env`.
3. Operating-system environment variables only.

## Decision
Option 1, with a committed `.env.example` template.

## Reasons
One source of truth; no duplicated values drifting apart.

## Advantages
Simple setup; one file to protect.

## Disadvantages
The frontend must never see backend secrets.

## Consequences
The backend loads the root file through a path computed from its own location; Vite uses
`envDir: '..'` and exposes only `VITE_` variables; MCP servers and the sandbox receive only what
they need (the sandbox receives nothing).

## Reconsider when
Deploying to a server with a secrets manager.
