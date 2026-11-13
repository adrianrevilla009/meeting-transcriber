"""Verificación de citas: una cita del LLM solo se acepta si aparece en la transcripción cruda."""

import itertools
import re
import unicodedata
from collections.abc import Sequence

from rapidfuzz import fuzz

from app.models import Segment


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def locate_quote(quote: str, segments: Sequence[Segment], min_score: float) -> Segment | None:
    """Devuelve el segmento donde está la cita, o None si no se puede verificar.

    Se prueba cada segmento solo y cada par de segmentos consecutivos (citas que cruzan el corte).
    Un segmento solo tiene prioridad sobre un par: el par (i, i+1) también contiene todo el segmento i+1,
    y atribuirle la cita a i desplazaría la marca de tiempo a la frase anterior.
    """
    q = normalize(quote)
    if len(q) < 8:
        return None
    norm = [normalize(s.text) for s in segments]
    pairs = [f"{a} {b}" for a, b in itertools.pairwise(norm)]

    for i, n in enumerate(norm):
        if q in n:
            return segments[i]
    for i, pair in enumerate(pairs):
        if q in pair:
            return segments[i]

    best: tuple[float, int] = (0.0, -1)
    for i, n in enumerate(norm):
        score = fuzz.partial_ratio(q, n) if len(n) >= len(q) * 0.5 else 0.0
        if score > best[0]:
            best = (score, i)
    for i, pair in enumerate(pairs):
        score = fuzz.partial_ratio(q, pair)
        if score > best[0]:  # solo gana si mejora estrictamente a los segmentos sueltos
            best = (score, i)
    if best[1] >= 0 and best[0] >= min_score:
        return segments[best[1]]
    return None
