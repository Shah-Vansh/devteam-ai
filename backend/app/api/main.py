"""The FastAPI application.

    python -m app.api        # serves on BACKEND_HOST:BACKEND_PORT (default 127.0.0.1:8000)

At startup: apply database migrations, start the MCP servers and the checkpointer (the
runtime), and mark runs that were active when the API last stopped. Single-user and
local: bound to 127.0.0.1 and CORS limited to the frontend origin.
"""

import shutil
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.routes import projects, runs
from app.api.schemas import Health
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.migrate import upgrade_database
from app.db.session import Database
from app.services.events import EventBroker
from app.services.run_manager import RunManager
from app.services.runtime import Runtime, real_runtime

RuntimeFactory = Callable[[Settings], AbstractAsyncContextManager[Runtime]]


def create_app(
    settings: Settings | None = None, runtime_factory: RuntimeFactory = real_runtime
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        upgrade_database(settings.database_url)
        db = Database(settings.database_url)
        async with runtime_factory(settings) as runtime:
            events = EventBroker()
            manager = RunManager(db, runtime, events)
            manager.recover_after_restart()
            app.state.db, app.state.runtime = db, runtime
            app.state.events, app.state.manager = events, manager
            yield
            await manager.shutdown()
        db.engine.dispose()

    app = FastAPI(title="DevTeam AI", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        # Every response carries an id that also appears in error logs.
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    install_error_handlers(app)
    app.include_router(projects.router)
    app.include_router(runs.router)

    @app.get("/api/health", tags=["system"])
    def health(request: Request) -> Health:
        runtime: Runtime = request.app.state.runtime
        return Health(
            status="ok",
            executor=runtime.executor_name,
            model=runtime.model,
            llm_configured=runtime.make_deps is not None,
            llm_error=runtime.llm_error,
            git_available=shutil.which("git") is not None,
        )

    return app


def main() -> None:
    import uvicorn

    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    uvicorn.run(create_app(settings), host=settings.backend_host, port=settings.backend_port)
