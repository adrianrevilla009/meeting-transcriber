"""Une detectores y resuelve solapes: gana el span más largo, luego el de mayor score, luego el más específico."""

from collections.abc import Sequence

from privacy_shield.application.ports import DetectorPort
from privacy_shield.domain.entities import DetectedEntity

# regex > glosario > lista de nombres > NER
_PRIORITY = {"regex": 0, "glossary": 1, "names": 2, "orgs": 2, "ner": 3}


class CompositeDetector:
    def __init__(self, detectors: Sequence[DetectorPort]):
        self._detectors = list(detectors)

    def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
        candidates: list[DetectedEntity] = []
        for detector in self._detectors:
            candidates.extend(detector.detect(text, language=language))  # un fallo se propaga: fail closed
        return resolve_overlaps(candidates)


def resolve_overlaps(candidates: Sequence[DetectedEntity]) -> list[DetectedEntity]:
    ordered = sorted(candidates, key=lambda e: (-e.length, -e.score, _PRIORITY.get(e.source, 9), e.start))
    chosen: list[DetectedEntity] = []
    for e in ordered:
        if all(e.end <= c.start or e.start >= c.end for c in chosen):
            chosen.append(e)
    return sorted(chosen, key=lambda e: e.start)
