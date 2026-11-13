"""Extracción de requisitos/decisiones/dudas con LLM local. El LLM NUNCA reescribe la transcripción:
solo extrae, y cada elemento debe traer una cita literal que se verifica contra los segmentos."""
import json
import logging
from typing import Protocol

import httpx
from pydantic import BaseModel, ValidationError
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Meeting, Requirement, RequirementEvent, Segment
from app.services.verifier import locate_quote

log = logging.getLogger(__name__)

KINDS = {"new_requirement", "changed_requirement", "decision", "open_question"}

SYSTEM_PROMPT = """Eres un analista que extrae información de transcripciones de reuniones de proyecto.
Reglas estrictas:
- Extrae SOLO lo que se dice explícitamente. No inventes, no completes, no deduzcas.
- Cada elemento DEBE incluir "quote": una cita LITERAL, copiada tal cual de la transcripción (máx. 40 palabras).
- Si no estás seguro, no lo incluyas.
- Responde únicamente con JSON válido con esta forma:
{"items":[{"kind":"new_requirement|changed_requirement|decision|open_question",
"requirement":"nombre corto del requisito (vacío si no aplica)","summary":"una frase","quote":"cita literal"}]}
Tipos: new_requirement = requisito nuevo; changed_requirement = el negocio modifica o contradice algo dicho antes;
decision = algo acordado; open_question = duda sin resolver."""


class Item(BaseModel):
    kind: str
    requirement: str = ""
    summary: str
    quote: str


class Analyzer(Protocol):
    def extract(self, transcript_window: str) -> list[Item]: ...


class OllamaAnalyzer:
    def __init__(self):
        self.s = get_settings()

    def extract(self, transcript_window: str) -> list[Item]:
        resp = httpx.post(
            f"{self.s.ollama_url}/api/chat",
            json={
                "model": self.s.ollama_model,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Transcripción:\n\n{transcript_window}"},
                ],
            },
            timeout=self.s.ollama_timeout,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        try:
            data = json.loads(content)
            return [Item(**i) for i in data.get("items", [])]
        except (json.JSONDecodeError, ValidationError, TypeError, AttributeError):
            log.warning("Respuesta del LLM no válida, se descarta la ventana")
            return []


class FakeAnalyzer:
    """Para tests: devuelve el guion `script` (lista de Item) sin llamar a ningún LLM."""

    script: list[Item] = []

    def extract(self, transcript_window: str) -> list[Item]:
        return list(self.script)


def get_analyzer() -> Analyzer | None:
    name = get_settings().analyzer
    if name == "ollama":
        return OllamaAnalyzer()
    if name == "fake":
        return FakeAnalyzer()
    return None


def _windows(segments: list[Segment], max_chars: int) -> list[str]:
    out, cur, size = [], [], 0
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


def _match_requirement(session: Session, project: str, name: str, threshold: float) -> Requirement:
    existing = session.scalars(select(Requirement).where(Requirement.project == project)).all()
    best, best_score = None, 0.0
    for r in existing:
        score = fuzz.token_set_ratio(name.lower(), r.title.lower())
        if score > best_score:
            best, best_score = r, score
    if best is not None and best_score >= threshold:
        return best
    req = Requirement(project=project, title=name)
    session.add(req)
    session.flush()
    return req


def analyze_meeting(session: Session, meeting: Meeting) -> dict:
    """Ejecuta el análisis y guarda solo los elementos cuya cita se verifica."""
    s = get_settings()
    analyzer = get_analyzer()
    if analyzer is None:
        meeting.analysis_status = "skipped"
        session.commit()
        return {"accepted": 0, "rejected": 0}

    segments = session.scalars(
        select(Segment).where(Segment.meeting_id == meeting.id).order_by(Segment.start)
    ).all()
    # Reanálisis: reemplaza los eventos previos de esta reunión.
    for ev in list(meeting.events):
        session.delete(ev)
    session.flush()

    accepted = rejected = 0
    seen: set[tuple[str, str]] = set()
    for window in _windows(segments, s.analysis_window_chars):
        for item in analyzer.extract(window):
            if item.kind not in KINDS:
                rejected += 1
                continue
            seg = locate_quote(item.quote, segments, s.quote_min_score)
            if seg is None:
                rejected += 1  # cita no verificable: posible alucinación
                continue
            key = (item.kind, seg.id.__str__() + item.summary.lower()[:40])
            if key in seen:
                continue
            seen.add(key)
            req_id = None
            if item.requirement.strip() and item.kind != "open_question":
                req_id = _match_requirement(
                    session, meeting.project, item.requirement.strip(), s.requirement_match_score
                ).id
            session.add(
                RequirementEvent(
                    requirement_id=req_id,
                    meeting_id=meeting.id,
                    segment_id=seg.id,
                    kind=item.kind,
                    summary=item.summary,
                    quote=item.quote,
                    timestamp=seg.start,
                )
            )
            accepted += 1
    meeting.analysis_status = "done"
    meeting.analysis_error = None
    session.commit()
    log.info("Análisis reunión %s: %s aceptados, %s rechazados", meeting.id, accepted, rejected)
    return {"accepted": accepted, "rejected": rejected}
