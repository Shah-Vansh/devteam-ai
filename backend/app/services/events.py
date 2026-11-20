"""Per-run event stream for Server-Sent Events.

Each run keeps its event history in memory, so a browser that connects late (or
reconnects) first receives everything that already happened, then live events. The
stream for a run ends after its `finished` event. History is lost on restart; the API
then sends a snapshot from the database instead (see the events route).
"""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

MAX_EVENTS_PER_RUN = 2000


@dataclass(frozen=True)
class Event:
    id: int
    event: str  # log, step, approval_required, finished
    data: dict[str, Any]


class EventBroker:
    def __init__(self) -> None:
        self._history: dict[str, list[Event]] = defaultdict(list)
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)

    def publish(self, run_id: str, event: str, data: dict[str, Any]) -> Event:
        history = self._history[run_id]
        item = Event(id=len(history) + 1, event=event, data=data)
        history.append(item)
        del history[:-MAX_EVENTS_PER_RUN]
        for queue in self._subscribers[run_id]:
            queue.put_nowait(item)
        return item

    def history(self, run_id: str) -> list[Event]:
        return list(self._history.get(run_id, []))

    def has_history(self, run_id: str) -> bool:
        return bool(self._history.get(run_id))

    async def subscribe(self, run_id: str, after: int = 0) -> AsyncIterator[Event]:
        """Past events (with id > `after`), then live ones until `finished`. A run that
        pauses keeps the stream open: approving it continues the same stream."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers[run_id].add(queue)
        try:
            seen = after
            for item in self.history(run_id):
                if item.id > seen:
                    seen = item.id
                    yield item
                    if item.event == "finished":
                        return
            while True:
                item = await queue.get()
                if item.id <= seen:
                    continue  # already sent from history
                seen = item.id
                yield item
                if item.event == "finished":
                    return
        finally:
            self._subscribers[run_id].discard(queue)
