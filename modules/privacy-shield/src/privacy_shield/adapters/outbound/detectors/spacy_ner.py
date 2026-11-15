"""NER en español con spaCy (PER, ORG, LOC). El modelo se carga UNA vez al arrancar."""

import re
import threading
from typing import Any

from privacy_shield.application.textnorm import fold
from privacy_shield.domain.entities import DetectedEntity, EntityType
from privacy_shield.domain.errors import DetectorUnavailable

SOURCE = "ner"

_LABELS: dict[str, tuple[EntityType, float]] = {
    "PER": (EntityType.PERSONA, 0.8),
    "PERSON": (EntityType.PERSONA, 0.8),
    "LOC": (EntityType.UBICACION, 0.75),
    "GPE": (EntityType.UBICACION, 0.75),
    "ORG": (EntityType.ORGANIZACION, 0.7),
}


# Entidades que spaCy confunde a menudo (saludos, tratamientos familiares, verbos en mayúsculas).
_NOISE = {
    "buenos dias", "buenas tardes", "buenas noches", "buenas", "mama", "papa",
    "estamos", "gracias", "hola", "adios", "llamara",
}  # fmt: skip
_UPPER_WORD = re.compile(r"\b[A-ZÁÉÍÓÚÑÜ]{3,}\b")


def recase(text: str) -> str:
    """Si el texto está casi todo en MAYÚSCULAS, capitaliza sus palabras: el NER no reconoce nombres gritados."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 6 or sum(c.isupper() for c in letters) / len(letters) < 0.6:
        return text
    out = _UPPER_WORD.sub(lambda m: m.group(0).capitalize(), text)
    return out if len(out) == len(text) else text  # los offsets deben conservarse


class SpacyNerDetector:
    def __init__(self, model: str = "es_core_news_md"):
        try:
            import spacy
        except ImportError as exc:
            raise DetectorUnavailable("spaCy no está instalado (pip install 'privacy-shield[ner]')") from exc
        try:
            nlp = spacy.load(model)
        except OSError as exc:
            raise DetectorUnavailable(
                f"Falta el modelo spaCy '{model}' (python -m spacy download {model})"
            ) from exc
        # Solo hace falta el NER: se desactiva lo que no aporta y cuesta latencia.
        nlp.select_pipes(disable=[n for n in ("parser", "lemmatizer") if n in nlp.pipe_names])
        self._nlp: Any = nlp
        self._lock = threading.Lock()
        self.model = model

    def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
        with self._lock:
            doc = self._nlp(recase(text))
        out: list[DetectedEntity] = []
        for ent in doc.ents:
            mapped = _LABELS.get(ent.label_)
            if mapped is None:
                continue
            entity_type, score = mapped
            raw = ent.text
            start = ent.start_char + (len(raw) - len(raw.lstrip()))
            end = ent.end_char - (len(raw) - len(raw.rstrip()))
            value = text[start:end]
            if len(value) < 3 or fold(value) in _NOISE:
                continue
            if " " not in value and value.islower():  # una sola palabra en minúsculas: casi siempre ruido
                continue
            out.append(DetectedEntity(entity_type, start, end, value, score, SOURCE))
        return out
