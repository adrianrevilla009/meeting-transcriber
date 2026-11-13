"""Verificación de citas: una cita del LLM solo se acepta si aparece en la transcripción cruda."""
import re
import unicodedata

from rapidfuzz import fuzz

from app.models import Segment


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def locate_quote(quote: str, segments: list[Segment], min_score: float) -> Segment | None:
    """Devuelve el segmento donde está la cita, o None si no se puede verificar.

    Se prueba cada segmento solo y cada par de segmentos consecutivos (citas que cruzan el corte).
    """
    q = normalize(quote)
    if len(q) < 8:
        return None
    norm = [normalize(s.text) for s in segments]

    best: tuple[float, int] = (0.0, -1)
    for i, n in enumerate(norm):
        if q in n:
            return segments[i]
        score = fuzz.partial_ratio(q, n) if len(n) >= len(q) * 0.5 else 0.0
        if score > best[0]:
            best = (score, i)
        if i + 1 < len(norm):
            pair = f"{n} {norm[i + 1]}"
            if q in pair:
                return segments[i]
            score = fuzz.partial_ratio(q, pair)
            if score > best[0]:
                best = (score, i)
    if best[1] >= 0 and best[0] >= min_score:
        return segments[best[1]]
    return None
