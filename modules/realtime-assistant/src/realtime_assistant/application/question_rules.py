"""Reglas rápidas para encontrar preguntas en español sobre la transcripción (sin LLM, sin red).

Solo escucha lo que dicen los demás (`system`/`mix`): lo que dice el usuario (`mic`) no necesita respuesta.
Whisper pone signos de interrogación y tildes la mayoría de las veces, y las reglas se apoyan en ello.
"""

import re
import unicodedata
from collections.abc import Iterator, Sequence

from realtime_assistant.domain.entities import Candidate, TranscriptSegment

MIN_WORDS = 3
MAX_GAP_SECONDS = 3.0  # silencio máximo entre segmentos para considerarlos la misma intervención
DEFAULT_THRESHOLD = 0.55

_FILLERS = {
    "oye", "y", "bueno", "pues", "entonces", "mira", "perdona", "perdone", "disculpa", "disculpe", "vale",
    "ok", "hola", "venga", "dime", "a", "ver",
}  # fmt: skip
_INTERROGATIVES = {
    "qué", "cómo", "cuándo", "dónde", "quién", "quiénes", "cuál", "cuáles", "cuánto", "cuánta", "cuántos",
    "cuántas", "adónde",
}  # fmt: skip
_VERB_STARTS = {
    "puedes", "podrías", "podría", "puede", "pueden", "podéis", "podemos", "sabes", "sabéis", "tienes", "tenéis",
    "has", "habéis", "hay", "crees", "opinas", "piensas", "estás", "estáis", "es", "son", "era", "fue", "será",
    "vais", "vas", "quieres", "queréis", "necesitas", "dirías", "harías", "conoces", "recuerdas", "entiendes",
    "deberíamos", "debemos", "tenemos", "hacemos",
}  # fmt: skip
_DIRECTED = re.compile(
    r"\b(?:tú|tu|te|ti|contigo|usted|ustedes|vosotros|puedes|podrías|sabes|sabéis|crees|piensas|opinas|tienes|"
    r"tenéis|has|estás|vas|quieres|necesitas|eres|harías|dirías|dime|cuéntame|dinos)\b",
    re.IGNORECASE,
)
_TAG_END = re.compile(r",\s*¿?\s*(?:verdad|no|vale|eh|ok|sí|si|cierto|de acuerdo)\s*\?\s*$", re.IGNORECASE)
# Una frase acaba en . ! ? o … SEGUIDOS de un espacio: así "marta@empresa.es" o "2.5" no la parten.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_WORDS = re.compile(r"\w+")


def fold(text: str) -> str:
    """Minúsculas y sin tildes, carácter a carácter."""
    out: list[str] = []
    for ch in text:
        base = unicodedata.normalize("NFD", ch)[:1].lower()
        out.append(base if len(base) == 1 else ch)
    return "".join(out)


class RuleQuestionDetector:
    def __init__(
        self,
        user_names: Sequence[str] = (),
        *,
        threshold: float = DEFAULT_THRESHOLD,
        listen_sources: frozenset[str] = frozenset({"system", "mix"}),
    ):
        names = [re.escape(fold(n.strip())) for n in user_names if n.strip()]
        self._names = re.compile(rf"(?<!\w)(?:{'|'.join(names)})(?!\w)") if names else None
        self._threshold = threshold
        self._listen = listen_sources

    def detect(self, segments: Sequence[TranscriptSegment]) -> list[Candidate]:
        found: list[Candidate] = []
        for text, ts, source in _utterances(segments):
            if source not in self._listen:
                continue
            for sentence in _SENTENCE_END.split(text):
                score = self.score(sentence)
                if score >= self._threshold:
                    found.append(Candidate(sentence.strip(), ts, source, round(score, 2)))
        return found

    def score(self, sentence: str) -> float:
        text = sentence.strip()
        if len(_WORDS.findall(text)) < MIN_WORDS:
            return 0.0
        has_question_mark = text.endswith("?")
        first = _first_content_words(text)
        interrogative = bool(first) and (
            first[0] in _INTERROGATIVES or (first[0] in {"por", "para"} and len(first) > 1 and first[1] == "qué")
        )
        if has_question_mark and _TAG_END.search(text) and not interrogative:
            return 0.0  # "¿verdad?", "¿no?"... al final de una afirmación
        score = 0.0
        if has_question_mark:
            score += 0.5
        if "¿" in text:
            score += 0.1
        if interrogative:
            score += 0.25 if has_question_mark else 0.3
        elif has_question_mark and first and first[0] in _VERB_STARTS:
            score += 0.2
        if _DIRECTED.search(text) or (self._names and self._names.search(fold(text))):
            score += 0.2
        if len(_WORDS.findall(text)) >= 6:
            score += 0.05
        return min(score, 1.0)


def _utterances(segments: Sequence[TranscriptSegment]) -> Iterator[tuple[str, float, str]]:
    """Une segmentos seguidos de la misma fuente con poca pausa entre ellos: (texto, inicio, fuente)."""
    current: list[TranscriptSegment] = []
    for seg in sorted(segments, key=lambda s: (s.start, s.id)):
        if current and (seg.source != current[-1].source or seg.start - current[-1].end > MAX_GAP_SECONDS):
            yield _join(current)
            current = []
        current.append(seg)
    if current:
        yield _join(current)


def _join(parts: list[TranscriptSegment]) -> tuple[str, float, str]:
    return " ".join(p.text.strip() for p in parts), parts[0].start, parts[0].source


def _first_content_words(text: str) -> list[str]:
    tokens = re.findall(r"[\wáéíóúüñ]+", text.lower().replace("¿", " "))[:6]
    skip = 0
    while skip < 3 and skip < len(tokens) and tokens[skip] in _FILLERS:
        skip += 1
    return tokens[skip:]
