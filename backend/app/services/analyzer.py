"""Resumen de la reunión con LLM local. El LLM NUNCA reescribe la transcripción:
solo genera un resumen aparte; los segmentos originales no se tocan."""

import logging
from collections.abc import Sequence
from typing import ClassVar, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Meeting, Segment

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un asistente que resume reuniones a partir de su transcripción.
Reglas estrictas:
- Incluye TODO lo relevante que se dijo: temas tratados, datos, cifras, fechas, nombres, acuerdos,
  tareas, problemas y dudas. No omitas información importante.
- Usa SOLO lo que aparece en la transcripción. No inventes, no completes, no deduzcas.
- Escribe en español, en texto claro: párrafos breves y, cuando ayude, listas con "- ".
- Sin encabezados ni categorías fijas, sin introducción ni despedida: solo el resumen."""

MERGE_PROMPT = """Recibirás las notas de resumen de partes consecutivas de una misma reunión.
Únelas en un único resumen coherente y ordenado, sin repetir información y sin perder ningún
dato relevante (cifras, fechas, nombres, acuerdos, tareas, dudas). No inventes nada.
Escribe en español, con párrafos breves y listas con "- " cuando ayude. Sin encabezados, introducción ni despedida."""


def _with_glossary(prompt: str) -> str:
    """Añade los términos propios para que el LLM corrija nombres que Whisper deforma."""
    glossary = get_settings().glossary.strip()
    if not glossary:
        return prompt
    hint = "Términos del proyecto (escríbelos exactamente así si aparecen, aunque la transcripción los deforme)"
    return f"{prompt}\n- {hint}: {glossary}."


class Analyzer(Protocol):
    def summarize(self, transcript_window: str) -> str: ...

    def merge(self, partial_summaries: list[str]) -> str: ...


class OllamaAnalyzer:
    def __init__(self):
        self.s = get_settings()

    def _chat(self, system: str, user: str) -> str:
        resp = httpx.post(
            f"{self.s.ollama_url}/api/chat",
            json={
                "model": self.s.ollama_model,
                "stream": False,
                "options": {"temperature": 0, "num_ctx": self.s.ollama_num_ctx},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=self.s.ollama_timeout,
        )
        resp.raise_for_status()
        return str(resp.json()["message"]["content"]).strip()

    def summarize(self, transcript_window: str) -> str:
        return self._chat(_with_glossary(SYSTEM_PROMPT), f"Transcripción:\n\n{transcript_window}")

    def merge(self, partial_summaries: list[str]) -> str:
        parts = "\n\n".join(f"--- Parte {i} ---\n{p}" for i, p in enumerate(partial_summaries, 1))
        return self._chat(_with_glossary(MERGE_PROMPT), parts)


class FakeAnalyzer:
    """Para tests: devuelve `script` como resumen de cada ventana, sin llamar a ningún LLM."""

    script: ClassVar[str] = ""

    def summarize(self, transcript_window: str) -> str:
        return self.script

    def merge(self, partial_summaries: list[str]) -> str:
        return "\n\n".join(partial_summaries)


def get_analyzer() -> Analyzer | None:
    name = get_settings().analyzer
    if name == "ollama":
        return OllamaAnalyzer()
    if name == "fake":
        return FakeAnalyzer()
    return None


def _windows(segments: Sequence[Segment], max_chars: int) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    size = 0
    for s in segments:
        line = s.text
        if size + len(line) > max_chars and cur:
            out.append("\n".join(cur))
            cur, size = cur[-2:], sum(len(x) for x in cur[-2:])  # solape de 2 segmentos
        cur.append(line)
        size += len(line)
    if cur:
        out.append("\n".join(cur))
    return out


def analyze_meeting(session: Session, meeting: Meeting) -> None:
    """Genera el resumen de la reunión (por ventanas si es larga) y lo guarda."""
    s = get_settings()
    analyzer = get_analyzer()
    if analyzer is None:
        meeting.analysis_status = "skipped"
        session.commit()
        return

    segments = session.scalars(select(Segment).where(Segment.meeting_id == meeting.id).order_by(Segment.start)).all()
    windows = _windows(segments, s.analysis_window_chars)
    partials = [p for w in windows if (p := analyzer.summarize(w).strip())]
    summary = partials[0] if len(partials) == 1 else analyzer.merge(partials) if partials else ""
    meeting.summary = summary.strip() or None
    meeting.analysis_status = "done"
    meeting.analysis_error = None
    session.commit()
    log.info("Resumen de la reunión %s generado (%s ventanas)", meeting.id, len(windows))
