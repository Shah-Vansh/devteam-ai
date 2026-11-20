"""Apply Alembic migrations from code (the API does this at startup)."""

from alembic import command
from alembic.config import Config

from app.db.session import sqlite_url
from app.mcp_clients.base import BACKEND_DIR


def upgrade_database(url: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlite_url(url))
    config.attributes["configure_logger"] = False  # keep the app's JSON logging
    command.upgrade(config, "head")
