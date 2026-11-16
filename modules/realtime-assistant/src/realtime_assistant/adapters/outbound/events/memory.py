"""Almacén de eventos en memoria: un registro acotado por reunión y suscripciones en vivo para el SSE."""

import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator

from realtime_assistant.domain.events import AssistantEvent


class MemoryEventStore:
    def __init__(self, max_events: int = 500):
        self._max = max_events
        self._events: dict[int, deque[AssistantEvent]] = defaultdict(lambda: deque(maxlen=self._max))
        self._counters: dict[int, int] = defaultdict(int)
        self._subscribers: dict[int, set[asyncio.Queue[AssistantEvent]]] = defaultdict(set)

    def append(self, meeting_id: int, type: str, data: dict[str, object]) -> AssistantEvent:
        self._counters[meeting_id] += 1
        event = AssistantEvent(self._counters[meeting_id], type, dict(data))
        self._events[meeting_id].append(event)
        for queue in list(self._subscribers[meeting_id]):
            queue.put_nowait(event)
        return event

    def after(self, meeting_id: int, after_id: int) -> list[AssistantEvent]:
        return [e for e in self._events.get(meeting_id, ()) if e.id > after_id]

    async def subscribe(
        self, meeting_id: int, after_id: int, heartbeat_seconds: float | None = None
    ) -> AsyncIterator[AssistantEvent | None]:
        # Primero se registra la cola y luego se lee el histórico: no se pierde nada entre ambos pasos.
        queue: asyncio.Queue[AssistantEvent] = asyncio.Queue()
        self._subscribers[meeting_id].add(queue)
        try:
            last = after_id
            for event in self.after(meeting_id, after_id):
                last = event.id
                yield event
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), heartbeat_seconds)
                except TimeoutError:
                    yield None  # latido: la conexión sigue viva aunque no haya eventos
                    continue
                if event.id > last:
                    last = event.id
                    yield event
        finally:
            self._subscribers[meeting_id].discard(queue)
