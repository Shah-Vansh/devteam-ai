# 0008 Server-Sent Events for progress

- Status: Accepted
- Date: 2026-11-19

## Context
Runs take minutes; the dashboard must show progress and approval requests as they happen.

## Problem
How the frontend receives updates.

## Options
1. Polling.
2. Server-Sent Events.
3. WebSockets.

## Decision
Server-Sent Events.

## Reasons
Updates flow one way (server to browser); SSE works over plain HTTP and reconnects automatically.
Actions such as approvals are normal REST calls.

## Advantages
Simple server code; built-in browser support; no extra protocol.

## Disadvantages
One direction only; per-browser connection limits; several backend instances would need a
shared event channel.

## Consequences
`GET /api/runs/{id}/events` streams step, approval and finish events.

## Reconsider when
Real two-way interaction is needed (WebSockets), or the backend runs as several instances
(add Redis pub/sub).
