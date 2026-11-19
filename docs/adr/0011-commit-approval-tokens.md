# 0011 Commit approval tokens bound to approved content

- Status: Accepted
- Date: 2026-11-20

## Context
A commit records generated code in history and must happen only after a human approves it
(ADR 0004). The Git MCP server is a separate process. Runs can pause at the approval and be
resumed much later, possibly by another process.

## Problem
How the Git server can tell that a specific commit was approved, and approved for exactly the
content that is about to be committed.

## Options
1. Trust the caller: workflow code only calls `create_commit` after approval.
2. A shared static password or API key for `create_commit`.
3. A one-time token signed by the backend with a per-start secret, carrying the workspace, a
   digest of the approved files, a nonce and an expiry.

## Decision
Option 3. The backend creates a random secret each time it starts the Git server and passes
it only to that child process. `prepare_commit` stores the digest of the files shown to the
human in the checkpointed state; after approval, `commit` signs a token for that digest. The
server checks the signature (HMAC-SHA256, constant-time comparison), expiry (10 minutes),
workspace, unused nonce, and recomputes the digest from disk.

## Reasons
Option 1 has no defence in depth: any bug or injected path that reaches the tool commits.
Option 2 is a standing credential that could be reused forever and says nothing about
content. Option 3 limits each approval to one commit of one exact file set, soon.

## Advantages
- A commit without a fresh approval is refused, even if `create_commit` is called directly.
- Files edited after approval (for example while the run waited) block the commit
  (`CONTENT_CHANGED`) instead of slipping in.
- A server restart invalidates every outstanding token; tokens are never stored.

## Disadvantages
- The digest must be taken in its own node: a paused node runs again on resume, so taking it
  in the approval node would cover edits made during the pause. Found during design and
  covered by a test.
- Used nonces live in the server's memory; they are only meaningful while that server (and its
  secret) lives, which is also when its tokens are valid.

## Consequences
Phase 7 stores only a hash of the token in the `approvals` table. The API never returns the
secret.

## Reconsider when
Several backend instances share one Git service (the secret and used nonces would need a shared
store), or commits must be signed with a human's own key.
