from dataclasses import dataclass
from enum import StrEnum


class QuestionOrigin(StrEnum):
    DETECTED = "detected"  # la detectó el asistente en la conversación
    MANUAL = "manual"  # la escribió el usuario


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """Fragmento de la transcripción del módulo 1. `source`: mic (el usuario), system (los demás) o mix."""

    id: int
    source: str
    start: float
    end: float
    text: str


@dataclass(frozen=True, slots=True)
class Candidate:
    """Posible pregunta encontrada por las reglas, antes de confirmarla."""

    text: str
    ts: float  # segundos desde el inicio de la reunión
    source: str
    score: float  # 0..1


@dataclass(frozen=True, slots=True)
class Verdict:
    """Decisión del clasificador sobre un candidato."""

    is_question: bool
    directed_at_me: bool = True


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    meeting_id: int
    text: str
    ts: float
    origin: QuestionOrigin
    score: float
