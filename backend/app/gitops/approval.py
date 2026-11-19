"""One-time commit approval tokens.

When a human approves a commit, the backend signs a token that says: *this* workspace,
with *exactly this content*, may be committed *once*, *within the next few minutes*. The
Git MCP server refuses `create_commit` unless the token checks out. Even a caller that can
reach the Git server (a bug, a compromised agent) cannot commit without a fresh approval.

- Signature: HMAC-SHA256 with a random secret that the backend creates when it starts the
  Git server and passes only to that child process. Server restart = new secret, so old
  tokens die with it.
- Content binding: the token carries a digest of every file's path and bytes at approval
  time; the server recomputes it from disk just before committing.
- One-time: each token has a random nonce; the server remembers nonces it has accepted.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping

TOKEN_TTL_SECONDS = 600


class TokenError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def new_secret() -> str:
    return secrets.token_hex(32)


def content_digest(files: Mapping[str, bytes]) -> str:
    """Order-independent fingerprint of a set of files: path and content of each."""
    outer = hashlib.sha256()
    for path in sorted(files):
        outer.update(path.encode("utf-8") + b"\0")
        outer.update(hashlib.sha256(files[path]).digest())
    return outer.hexdigest()


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(bytes.fromhex(secret), body, hashlib.sha256).hexdigest()


def issue_token(
    secret: str,
    workspace: str,
    digest: str,
    *,
    ttl: int = TOKEN_TTL_SECONDS,
    now: float | None = None,
) -> str:
    payload = {
        "workspace": workspace,
        "digest": digest,
        "nonce": secrets.token_hex(16),
        "expires": int((now if now is not None else time.time()) + ttl),
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).rstrip(b"=")
    return f"{body.decode()}.{_sign(secret, body)}"


def verify_token(
    secret: str,
    token: str,
    *,
    workspace: str,
    digest: str,
    used_nonces: set[str],
    now: float | None = None,
) -> dict:
    """Check a token; on success remember its nonce so it cannot be used again."""
    if not token:
        raise TokenError("TOKEN_MISSING", "an approval token is required to commit")
    body, _, signature = token.partition(".")
    if not body or not signature:
        raise TokenError("TOKEN_INVALID", "malformed approval token")
    # compare_digest: constant time, so the signature cannot be guessed byte by byte
    if not hmac.compare_digest(_sign(secret, body.encode()), signature):
        raise TokenError("TOKEN_INVALID", "approval token signature does not match")
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except ValueError:
        raise TokenError("TOKEN_INVALID", "unreadable approval token") from None
    if payload.get("expires", 0) < (now if now is not None else time.time()):
        raise TokenError("TOKEN_EXPIRED", "approval token has expired; approve again")
    if payload.get("workspace") != workspace:
        raise TokenError("TOKEN_WRONG_WORKSPACE", "approval token is for another workspace")
    if payload.get("nonce") in used_nonces:
        raise TokenError("TOKEN_USED", "approval token was already used")
    if payload.get("digest") != digest:
        raise TokenError(
            "CONTENT_CHANGED", "files changed after approval; approve the current files again"
        )
    used_nonces.add(payload["nonce"])
    return payload
