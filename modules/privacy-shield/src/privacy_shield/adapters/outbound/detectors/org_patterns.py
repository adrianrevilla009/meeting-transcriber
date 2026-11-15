"""Organizaciones por patrón: palabras típicas de empresa ("Grupo X", "Fundación de la X") y formas legales ("X S.L.").
El NER de spaCy reconoce pocas organizaciones; estas reglas cubren las construcciones más habituales en español."""

import re

from privacy_shield.domain.entities import DetectedEntity, EntityType

SOURCE = "orgs"

_CAP = r"[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñü]+"
_PREFIXES = (
    "Grupo|Fundación|Asociación|Consultora|Industrias|Talleres|Soluciones|Logística|Editorial|Clínica|Hospital"
    "|Universidad|Ayuntamiento|Banco|Cooperativa|Restaurante|Hotel|Colegio|Instituto|Laboratorios|Transportes"
)
_PREFIXED = re.compile(rf"(?<!\w)(?:{_PREFIXES})(?:\s+(?:de|del)(?:\s+(?:la|los|las|el))?)?\s+{_CAP}(?:\s+{_CAP})*")
_LEGAL_FORM = r"(?:S\.?\s?L\.?U?|S\.?\s?A\.?|S\.?\s?C\.?)"
_LEGAL = re.compile(rf"(?<!\w){_CAP}(?:\s+(?:y|de|del|la)\s+{_CAP}|\s+{_CAP})*,?\s+{_LEGAL_FORM}(?![\w])")


class OrgPatternDetector:
    def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
        out = []
        for pattern in (_PREFIXED, _LEGAL):
            for m in pattern.finditer(text):
                out.append(DetectedEntity(EntityType.ORGANIZACION, m.start(), m.end(), m.group(0), 0.7, SOURCE))
        return out
