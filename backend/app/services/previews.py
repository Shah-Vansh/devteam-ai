"""Previews of generated APIs: at most one per run, started and stopped on request.

The E2B SDK is synchronous, so starting runs in a worker thread and the API stays
responsive while packages install. A run's preview is forgotten once its time is up; the
sandbox has already deleted itself by then.
"""

import asyncio
import time
from dataclasses import dataclass

from app.execution.preview import E2BPreview, PreviewError, PreviewHandle, stop
from app.services.errors import ServiceError


@dataclass
class PreviewInfo:
    status: str  # "starting" | "running" | "stopped"
    url: str | None = None
    expires_at: float | None = None


class PreviewManager:
    def __init__(self, preview: E2BPreview | None) -> None:
        self._preview = preview  # None: no sandbox configured, previews unavailable
        self._running: dict[str, PreviewHandle] = {}
        self._starting: set[str] = set()

    @property
    def available(self) -> bool:
        return self._preview is not None

    def info(self, run_id: str) -> PreviewInfo:
        if run_id in self._starting:
            return PreviewInfo("starting")
        handle = self._running.get(run_id)
        if handle is None or handle.expires_at <= time.time():
            self._running.pop(run_id, None)
            return PreviewInfo("stopped")
        return PreviewInfo("running", handle.url, handle.expires_at)

    async def start(self, run_id: str, files: dict[str, str]) -> PreviewInfo:
        if self._preview is None:
            raise ServiceError(
                409, "PREVIEW_UNAVAILABLE", "Trying the API needs the E2B sandbox (E2B_API_KEY)."
            )
        current = self.info(run_id)
        if current.status != "stopped":
            return current
        self._starting.add(run_id)
        try:
            handle = await asyncio.to_thread(self._preview.start, files)
        except (PreviewError, ValueError) as exc:
            raise ServiceError(422, "PREVIEW_FAILED", str(exc)) from None
        except Exception as exc:  # sandbox or network problems
            raise ServiceError(
                502, "PREVIEW_FAILED", f"sandbox error: {type(exc).__name__}: {exc}"[:400]
            ) from None
        finally:
            self._starting.discard(run_id)
        self._running[run_id] = handle
        return self.info(run_id)

    async def stop(self, run_id: str) -> PreviewInfo:
        handle = self._running.pop(run_id, None)
        if handle is not None:
            await asyncio.to_thread(stop, handle.sandbox)
        return PreviewInfo("stopped")

    async def stop_all(self) -> None:
        for run_id in list(self._running):
            await self.stop(run_id)
