"""Errors a service raises for the API to turn into its error response."""

from typing import Any


class ServiceError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(kind: str, ident: str) -> ServiceError:
    return ServiceError(404, f"{kind.upper()}_NOT_FOUND", f"{kind} {ident} does not exist")
