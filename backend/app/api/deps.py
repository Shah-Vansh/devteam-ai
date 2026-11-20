"""FastAPI dependencies: the objects created at startup, handed to each request."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.session import Database
from app.services.events import EventBroker
from app.services.run_manager import RunManager
from app.services.runtime import Runtime


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_session(request: Request) -> Iterator[Session]:
    """A session for one request. It does NOT commit on exit: FastAPI runs this cleanup
    after the response has been sent, so a commit here would race the client's next
    request (found live: a project was not found right after being created). Endpoints
    that write call `session.commit()` before returning."""
    session = request.app.state.db.new_session()
    try:
        yield session
    finally:
        session.rollback()  # nothing uncommitted may leak; no-op after an explicit commit
        session.close()


def get_manager(request: Request) -> RunManager:
    return request.app.state.manager


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def get_events(request: Request) -> EventBroker:
    return request.app.state.events
