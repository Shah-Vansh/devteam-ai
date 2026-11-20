"""The long-lived pieces the API needs to run workflows, created once at startup.

`Runtime` holds the compiled graph (with its SQLite checkpointer), the MCP clients and
a factory for per-run dependencies. Tests build a `Runtime` with fakes instead.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph

from app.agents.developer import Developer
from app.agents.planner import Planner
from app.agents.reviewer import Reviewer
from app.agents.tester import Tester
from app.core.config import Settings
from app.execution.factory import build_executor
from app.gitops.repo import CommitAuthor
from app.llm.base import LLMConfigError
from app.llm.factory import build_llm_client
from app.mcp_clients.filesystem import FilesystemClient
from app.mcp_clients.git import GitClient
from app.workflow.graph import build_graph
from app.workflow.state import WorkflowDeps

DepsFactory = Callable[[Callable[[str], None]], WorkflowDeps]


@dataclass
class Runtime:
    graph: CompiledStateGraph
    fs: FilesystemClient
    make_deps: DepsFactory | None  # None when the LLM is not configured
    executor_name: str
    model: str | None
    llm_error: str | None = None


@asynccontextmanager
async def real_runtime(settings: Settings) -> AsyncIterator[Runtime]:
    """Start the MCP servers and open the checkpointer for the lifetime of the API."""
    executor = build_executor(settings)
    try:
        llm = build_llm_client(settings)
        llm_error = None
    except LLMConfigError as exc:  # the API still starts; starting a run explains why not
        llm, llm_error = None, str(exc)

    author = CommitAuthor(settings.commit_author_name, settings.commit_author_email)
    settings.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
    async with (
        AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path)) as saver,
        FilesystemClient.over_stdio(settings.workspaces_dir) as fs,
        GitClient.over_stdio(settings.workspaces_dir, author) as git,
    ):

        def make_deps(progress: Callable[[str], None]) -> WorkflowDeps:
            return WorkflowDeps(
                planner=Planner(llm),
                developer=Developer(llm),
                reviewer=Reviewer(llm),
                tester=Tester(llm),
                executor=executor,
                fs=fs,
                git=git,
                max_review_rounds=settings.max_review_rounds,
                max_fix_rounds=settings.max_fix_rounds,
                max_llm_calls=settings.max_llm_calls_per_run,
                test_timeout_seconds=settings.sandbox_timeout_seconds,
                progress=progress,
            )

        yield Runtime(
            graph=build_graph().compile(checkpointer=saver),
            fs=fs,
            make_deps=make_deps if llm is not None else None,
            executor_name=executor.name,
            model=settings.llm_model or None,
            llm_error=llm_error,
        )
