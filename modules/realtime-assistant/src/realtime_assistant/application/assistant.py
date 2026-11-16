"""Caso de uso principal: seguir una reunión, detectar preguntas y responderlas (siempre vía privacy-shield)."""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from realtime_assistant.application.context import format_context
from realtime_assistant.application.ports import (
    AnswerGeneratorPort,
    ClockPort,
    EventStorePort,
    QuestionClassifierPort,
    TranscriptSourcePort,
)
from realtime_assistant.application.question_rules import RuleQuestionDetector, fold
from realtime_assistant.domain.entities import Candidate, Question, QuestionOrigin, TranscriptSegment, Verdict
from realtime_assistant.domain.errors import (
    ClassifierUnavailable,
    MeetingNotFound,
    QuestionNotFound,
    ShieldBlocked,
    ShieldUnavailable,
    TranscriberUnavailable,
)

log = logging.getLogger("assistant")

_RECENT_SEGMENTS = 12  # ventana sobre la que se buscan preguntas en cada vuelta
_SEEN_LIMIT = 40


@dataclass(frozen=True)
class AssistantSettings:
    poll_seconds: float = 1.5
    context_chars: int = 6000
    auto_answer: bool = True
    answer_cooldown_seconds: float = 15.0  # entre respuestas automáticas; las manuales no esperan
    dedupe_ratio: float = 0.88  # similitud a partir de la cual dos preguntas son la misma
    idle_timeout_seconds: float = 1800.0  # sin segmentos nuevos durante este tiempo, deja de seguir
    own_source: str = "mic"


@dataclass
class _Session:
    meeting_id: int
    after_id: int = 0
    following: bool = False
    transcript: deque[TranscriptSegment] = field(default_factory=lambda: deque(maxlen=600))
    recent: deque[TranscriptSegment] = field(default_factory=lambda: deque(maxlen=_RECENT_SEGMENTS))
    questions: dict[str, Question] = field(default_factory=dict)
    answered: set[str] = field(default_factory=set)
    seen: list[str] = field(default_factory=list)
    counter: int = 0
    last_auto_answer: float | None = None
    last_activity: float = 0.0
    unavailable_notified: bool = False
    task: asyncio.Task[None] | None = None
    pending: set[asyncio.Task[None]] = field(default_factory=set)
    answer_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class MeetingAssistant:
    def __init__(
        self,
        source: TranscriptSourcePort,
        detector: RuleQuestionDetector,
        classifier: QuestionClassifierPort | None,
        generator: AnswerGeneratorPort,
        store: EventStorePort,
        clock: ClockPort,
        settings: AssistantSettings,
    ):
        self._source = source
        self._detector = detector
        self._classifier = classifier
        self._generator = generator
        self._store = store
        self._clock = clock
        self._settings = settings
        self._sessions: dict[int, _Session] = {}

    # ------------------------------------------------------------------ seguimiento
    async def follow(self, meeting_id: int) -> None:
        """Empieza a seguir la reunión (idempotente). Lanza MeetingNotFound / TranscriberUnavailable."""
        session = self._session(meeting_id)
        if session.following:
            return
        await self._source.fetch_after(meeting_id, 0)  # comprueba que existe y que se puede leer
        session.following = True
        session.last_activity = self._clock.monotonic()
        self._emit(session, "status", {"state": "following"})
        session.task = asyncio.create_task(self._loop(session))

    async def unfollow(self, meeting_id: int) -> None:
        session = self._sessions.get(meeting_id)
        if session is None or session.task is None:
            return
        session.following = False
        session.task.cancel()
        await asyncio.gather(session.task, return_exceptions=True)

    async def shutdown(self) -> None:
        for session in list(self._sessions.values()):
            session.following = False
            tasks = [t for t in (session.task, *session.pending) if t is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def status(self, meeting_id: int) -> dict[str, object]:
        session = self._sessions.get(meeting_id)
        if session is None:
            return {"following": False, "questions": 0, "answers": 0}
        return {"following": session.following, "questions": len(session.questions), "answers": len(session.answered)}

    async def wait_idle(self, meeting_id: int) -> None:
        """Espera a que terminen las respuestas en curso (para tests y para cerrar limpiamente)."""
        session = self._sessions.get(meeting_id)
        if session and session.pending:
            await asyncio.gather(*session.pending, return_exceptions=True)

    async def _loop(self, session: _Session) -> None:
        try:
            while session.following:
                try:
                    await self.step(session.meeting_id)
                    session.unavailable_notified = False
                except MeetingNotFound:
                    self._emit(session, "error", {"error": "meeting_not_found"})
                    break
                except TranscriberUnavailable:
                    if not session.unavailable_notified:
                        session.unavailable_notified = True
                        self._emit(session, "error", {"error": "transcriber_unavailable"})
                if self._clock.monotonic() - session.last_activity > self._settings.idle_timeout_seconds:
                    break
                await asyncio.sleep(self._settings.poll_seconds)
        finally:
            session.following = False
            self._emit(session, "status", {"state": "stopped"})

    async def step(self, meeting_id: int) -> int:
        """Una vuelta: lee los segmentos nuevos y evalúa las preguntas que aparezcan. Devuelve cuántos había."""
        session = self._session(meeting_id)
        segments = await self._source.fetch_after(meeting_id, session.after_id)
        if not segments:
            return 0
        session.last_activity = self._clock.monotonic()
        for seg in segments:
            session.after_id = max(session.after_id, seg.id)
            session.transcript.append(seg)
            session.recent.append(seg)
        for candidate in self._detector.detect(list(session.recent)):
            await self._consider(session, candidate)
        return len(segments)

    # ------------------------------------------------------------------ preguntas
    async def ask(self, meeting_id: int, text: str) -> str:
        """Pregunta manual del usuario: se responde siempre, sin esperar al enfriamiento."""
        session = self._session(meeting_id)
        last_end = session.transcript[-1].end if session.transcript else 0.0
        question = self._new_question(session, text.strip(), last_end, QuestionOrigin.MANUAL, 1.0)
        self._emit_question(session, question)
        self._spawn_answer(session, question)
        return question.id

    async def answer(self, meeting_id: int, question_id: str) -> None:
        """Responde una pregunta detectada que no se contestó sola (o reintenta una que falló)."""
        session = self._sessions.get(meeting_id)
        question = session.questions.get(question_id) if session else None
        if session is None or question is None:
            raise QuestionNotFound(question_id)
        if question_id not in session.answered:
            self._spawn_answer(session, question)

    async def _consider(self, session: _Session, candidate: Candidate) -> None:
        key = fold(candidate.text)
        if self._is_duplicate(session, key):
            return
        session.seen.append(key)
        del session.seen[:-_SEEN_LIMIT]
        verdict = await self._verdict(session, candidate)
        if not (verdict.is_question and verdict.directed_at_me):
            return
        question = self._new_question(session, candidate.text, candidate.ts, QuestionOrigin.DETECTED, candidate.score)
        self._emit_question(session, question)
        now = self._clock.monotonic()
        last = session.last_auto_answer
        cooled = last is None or now - last >= self._settings.answer_cooldown_seconds
        if self._settings.auto_answer and cooled:
            session.last_auto_answer = now
            self._spawn_answer(session, question)

    def _is_duplicate(self, session: _Session, key: str) -> bool:
        return any(SequenceMatcher(None, key, old).ratio() >= self._settings.dedupe_ratio for old in session.seen)

    async def _verdict(self, session: _Session, candidate: Candidate) -> Verdict:
        if self._classifier is None:
            return Verdict(True)
        context = format_context(session.transcript, self._settings.context_chars, self._settings.own_source)
        try:
            return await self._classifier.classify(candidate.text, context)
        except ClassifierUnavailable:
            return Verdict(True)  # sin LLM local, se confía en las reglas

    def _new_question(
        self, session: _Session, text: str, ts: float, origin: QuestionOrigin, score: float
    ) -> Question:
        session.counter += 1
        question = Question(f"q{session.counter}", session.meeting_id, text, ts, origin, score)
        session.questions[question.id] = question
        return question

    # ------------------------------------------------------------------ respuestas
    def _spawn_answer(self, session: _Session, question: Question) -> None:
        session.answered.add(question.id)
        task = asyncio.create_task(self._run_answer(session, question))
        session.pending.add(task)
        task.add_done_callback(session.pending.discard)

    async def _run_answer(self, session: _Session, question: Question) -> None:
        async with session.answer_lock:  # una respuesta a la vez por reunión
            self._emit(session, "answer_start", {"question_id": question.id})
            context = format_context(session.transcript, self._settings.context_chars, self._settings.own_source)
            chunks: list[str] = []
            try:
                async for chunk in self._generator.stream_answer(session.meeting_id, question.text, context):
                    chunks.append(chunk)
                    self._emit(session, "answer_chunk", {"question_id": question.id, "content": chunk})
            except ShieldBlocked as exc:
                self._fail(session, question, exc.code)
                return
            except ShieldUnavailable as exc:
                self._fail(session, question, exc.code)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Fallo inesperado generando una respuesta (reunión %s)", session.meeting_id)
                self._fail(session, question, "provider_error")
                return
            self._emit(session, "answer_done", {"question_id": question.id, "content": "".join(chunks)})

    def _fail(self, session: _Session, question: Question, code: str) -> None:
        session.answered.discard(question.id)  # se puede reintentar con "Responder"
        self._emit(session, "error", {"question_id": question.id, "error": code})

    # ------------------------------------------------------------------ eventos
    def _session(self, meeting_id: int) -> _Session:
        session = self._sessions.get(meeting_id)
        if session is None:
            session = _Session(meeting_id, last_activity=self._clock.monotonic())
            self._sessions[meeting_id] = session
        return session

    def _emit(self, session: _Session, type: str, data: dict[str, object]) -> None:
        self._store.append(session.meeting_id, type, data)

    def _emit_question(self, session: _Session, question: Question) -> None:
        self._emit(
            session,
            "question",
            {
                "question_id": question.id,
                "text": question.text,
                "ts": question.ts,
                "origin": question.origin.value,
                "score": question.score,
            },
        )
