"""Database engine and sessions (SQLite through SQLAlchemy 2.0).

The application database (`DATABASE_URL`, default `data/devteam.db`) is separate from
LangGraph's checkpoint database: different owners, different lifecycles.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import REPO_ROOT


def sqlite_url(url: str) -> str:
    """Make a relative SQLite path absolute (from the repo root) and create its folder."""
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url == "sqlite:///:memory:":
        return url
    path = Path(url[len(prefix) :])
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path.as_posix()}"


def make_engine(url: str) -> Engine:
    engine = create_engine(
        sqlite_url(url),
        # The API serves requests from a thread pool and the run manager from the event
        # loop; SQLite connections may be used from several threads, one at a time.
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")  # SQLite ignores FKs unless asked
        cursor.execute("PRAGMA journal_mode=WAL")  # readers do not block the writer
        cursor.close()

    return engine


class Database:
    def __init__(self, url: str) -> None:
        self.engine = make_engine(url)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def new_session(self) -> Session:
        return self._sessions()

    @contextmanager
    def session(self) -> Iterator[Session]:
        """One unit of work: committed on success, rolled back on any error."""
        session = self._sessions()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
