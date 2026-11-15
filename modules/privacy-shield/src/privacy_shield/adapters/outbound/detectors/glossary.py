"""Términos propios a proteger (clientes, proyectos, apodos), sin distinguir mayúsculas ni tildes."""

import re
from collections.abc import Sequence

from privacy_shield.application.textnorm import fold
from privacy_shield.domain.entities import DetectedEntity, EntityType
from privacy_shield.domain.glossary import GlossaryTerm

SOURCE = "glossary"


class GlossaryDetector:
    def __init__(self, terms: Sequence[GlossaryTerm]):
        self._patterns: list[tuple[re.Pattern[str], EntityType]] = []
        for term in terms:
            for form in (term.text, *term.aliases):
                needle = fold(form).strip()
                if len(needle) >= 2:
                    self._patterns.append((re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)"), term.entity_type))

    def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
        folded = fold(text)  # misma longitud que `text`, así los offsets coinciden
        out: list[DetectedEntity] = []
        for pattern, entity_type in self._patterns:
            for m in pattern.finditer(folded):
                out.append(DetectedEntity(entity_type, m.start(), m.end(), text[m.start() : m.end()], 0.97, SOURCE))
        return out
