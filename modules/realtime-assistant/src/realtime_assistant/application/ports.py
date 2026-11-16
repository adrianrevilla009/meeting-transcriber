"""Puertos: lo que el núcleo necesita del exterior. Los adaptadores los implementan."""

from collections.abc import AsyncIterator
from typing import Protocol

from realtime_assistant.domain.entities import TranscriptSegment, Verdict
from realtime_assistant.domain.events import AssistantEvent


class TranscriptSourcePort(Protocol):
    async def fetch_after(self, meeting_id: int, after_id: int) -> list[TranscriptSegment]:
        """Segmentos con id > after_id, en orden. Lanza MeetingNotFound o TranscriberUnavailable."""
        ...


class QuestionClassifierPort(Protocol):
    async def classify(self, question: str, context: str) -> Verdict:
        """¿Es una pregunta que merece respuesta? Lanza ClassifierUnavailable si no puede decidir."""
        ...


class AnswerGeneratorPort(Protocol):
    def stream_answer(self, meeting_id: int, question: str, context: str) -> AsyncIterator[str]:
        """Trozos de respuesta. SIEMPRE vía privacy-shield. Lanza ShieldBlocked o ShieldUnavailable."""
        ...


class EventStorePort(Protocol):
    def append(self, meeting_id: int, type: str, data: dict[str, object]) -> AssistantEvent: ...

    def after(self, meeting_id: int, after_id: int) -> list[AssistantEvent]: ...

    def subscribe(
        self, meeting_id: int, after_id: int, heartbeat_seconds: float | None = None
    ) -> AsyncIterator[AssistantEvent | None]:
        """Eventos con id > after_id y luego los nuevos. Con heartbeat, emite None si pasa ese tiempo sin eventos."""
        ...


class ClockPort(Protocol):
    def monotonic(self) -> float: ...
