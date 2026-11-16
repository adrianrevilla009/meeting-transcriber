"""Utilidades de los tests: piezas falsas (transcripción, clasificador, generador de respuestas, reloj) y runtime."""

from collections.abc import AsyncIterator, Sequence

from realtime_assistant.adapters.outbound.events.memory import MemoryEventStore
from realtime_assistant.application.runtime import Runtime
from realtime_assistant.bootstrap import build_runtime
from realtime_assistant.config import Settings
from realtime_assistant.domain.entities import TranscriptSegment, Verdict


def seg(id: int, text: str, source: str = "system", start: float | None = None) -> TranscriptSegment:
    begin = float(id * 5) if start is None else start
    return TranscriptSegment(id, source, begin, begin + 4.0, text)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSource:
    def __init__(self, *segments: TranscriptSegment):
        self.segments = list(segments)
        self.calls: list[tuple[int, int]] = []
        self.error: Exception | None = None

    def add(self, *segments: TranscriptSegment) -> None:
        self.segments.extend(segments)

    async def fetch_after(self, meeting_id: int, after_id: int) -> list[TranscriptSegment]:
        self.calls.append((meeting_id, after_id))
        if self.error:
            raise self.error
        return [s for s in self.segments if s.id > after_id]


class FakeClassifier:
    def __init__(self, verdict: Verdict = Verdict(True, True), error: Exception | None = None):  # noqa: B008
        self.verdict = verdict
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def classify(self, question: str, context: str) -> Verdict:
        self.calls.append((question, context))
        if self.error:
            raise self.error
        return self.verdict


class FakeGenerator:
    def __init__(self, chunks: Sequence[str] = ("Respuesta ", "corta."), error: Exception | None = None):
        self.chunks = list(chunks)
        self.error = error
        self.calls: list[tuple[int, str, str]] = []

    async def stream_answer(self, meeting_id: int, question: str, context: str) -> AsyncIterator[str]:
        self.calls.append((meeting_id, question, context))
        if self.error:
            raise self.error
        for chunk in self.chunks:
            yield chunk


def make_runtime(
    *,
    classifier: FakeClassifier | None = None,
    source: FakeSource | None = None,
    generator: FakeGenerator | None = None,
    **settings: object,
) -> tuple[Runtime, FakeSource, FakeGenerator, FakeClock]:
    source = source or FakeSource()
    generator = generator or FakeGenerator()
    clock = FakeClock()
    config = Settings(api_token="tok", poll_seconds=0.01, user_names="Adrián, Adri", **settings)  # type: ignore[arg-type]
    rt = build_runtime(
        config,
        source=source,
        classifier=classifier,
        rules_only=classifier is None,
        generator=generator,
        store=MemoryEventStore(),
        clock=clock,
    )
    return rt, source, generator, clock
