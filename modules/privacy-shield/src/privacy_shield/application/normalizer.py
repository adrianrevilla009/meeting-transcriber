"""Normalizador de texto de ASR (Whisper): dígitos hablados y emails/URLs deletreados.

Trabaja sobre una VISTA normalizada con mapa de offsets hacia el original. Los spans detectados sobre la vista
se reproyectan al texto original; si un span toca una zona reescrita se amplía a toda la zona (más vale tapar de más).
"""

import re
from dataclasses import dataclass

from privacy_shield.application.ports import DetectorPort
from privacy_shield.application.textnorm import fold
from privacy_shield.domain.entities import DetectedEntity

_UNITS = {
    "cero": 0,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
}
_TEENS = {
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
}
_TWENTIES = {
    "veinte": 20,
    "veintiuno": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
}
_TENS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90}
_MIN_RUN = 3  # cuántos números seguidos hacen falta para considerarlo un dato dictado

_WORD = re.compile(r"\w+")
_RUN_SEP = re.compile(r"^[ \t,]+$")
_LOCAL = r"\w+(?:\s+(?:punto|guion bajo|barra baja|guion)\s+\w+)*"
_DOMAIN = r"\w+(?:\s+punto\s+\w+)+"
_SPOKEN_EMAIL = re.compile(rf"(?<!\w)(?P<local>{_LOCAL})\s+arroba\s+(?P<domain>{_DOMAIN})(?!\w)", re.IGNORECASE)
_SPOKEN_URL = re.compile(rf"(?<!\w)(?P<url>www\s+punto\s+{_DOMAIN}|www\s+punto\s+\w+)(?!\w)", re.IGNORECASE)
@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: str


@dataclass(frozen=True)
class NormalizedText:
    text: str
    _origin: tuple[tuple[int, int], ...]  # por cada carácter de `text`: (inicio, fin) en el original

    def project(self, start: int, end: int) -> tuple[int, int]:
        """Span de la vista -> span del original (ampliado si toca una zona reescrita)."""
        spans = self._origin[start:end]
        if not spans:
            return start, end
        return min(s for s, _ in spans), max(e for _, e in spans)


def normalize(text: str) -> NormalizedText:
    edits = _find_edits(text)
    out: list[str] = []
    origin: list[tuple[int, int]] = []
    pos = 0
    for edit in edits:
        for i in range(pos, edit.start):
            out.append(text[i])
            origin.append((i, i + 1))
        for ch in edit.replacement:
            out.append(ch)
            origin.append((edit.start, edit.end))
        pos = edit.end
    for i in range(pos, len(text)):
        out.append(text[i])
        origin.append((i, i + 1))
    return NormalizedText("".join(out), tuple(origin))


def _find_edits(text: str) -> list[_Edit]:
    edits: list[_Edit] = []
    for m in _SPOKEN_EMAIL.finditer(text):
        edits.append(_Edit(m.start(), m.end(), _spoken_to_symbols(m.group(0))))
    for m in _SPOKEN_URL.finditer(text):
        edits.append(_Edit(m.start(), m.end(), _spoken_to_symbols(m.group(0))))
    edits = _drop_overlaps(edits)
    for run in _digit_runs(text):
        if not any(run.start < e.end and e.start < run.end for e in edits):
            edits.append(run)
    return sorted(_drop_overlaps(edits), key=lambda e: e.start)


def _spoken_to_symbols(spoken: str) -> str:
    """'marta punto garcia arroba gmail punto com' -> 'marta.garcia@gmail.com'."""
    out = re.sub(r"\s+arroba\s+", "@", spoken, flags=re.IGNORECASE)
    out = re.sub(r"\s+(?:guion bajo|barra baja)\s+", "_", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+guion\s+", "-", out, flags=re.IGNORECASE)
    return re.sub(r"\s+punto\s+", ".", out, flags=re.IGNORECASE)


def _drop_overlaps(edits: list[_Edit]) -> list[_Edit]:
    kept: list[_Edit] = []
    for e in sorted(edits, key=lambda e: (e.start, -(e.end - e.start))):
        if not kept or e.start >= kept[-1].end:
            kept.append(e)
    return kept


def _digit_runs(text: str) -> list[_Edit]:
    """Secuencias de números hablados ('seis cuatro cinco treinta y dos') -> dígitos ('645' '32')."""
    words = list(_WORD.finditer(text))
    runs: list[_Edit] = []
    i = 0
    while i < len(words):
        group = _read_group(words, i)
        if group is None:
            i += 1
            continue
        digits, first, nxt = [group[0]], i, group[1]
        while nxt < len(words) and _RUN_SEP.match(text[words[nxt - 1].end() : words[nxt].start()] or " "):
            more = _read_group(words, nxt)
            if more is None:
                break
            digits.append(more[0])
            nxt = more[1]
        if len(digits) >= _MIN_RUN:
            runs.append(_Edit(words[first].start(), words[nxt - 1].end(), "".join(digits)))
        i = max(nxt, i + 1)
    return runs


def _read_group(words: list[re.Match[str]], i: int) -> tuple[str, int] | None:
    """Lee un número a partir de words[i]: devuelve (dígitos, índice de la siguiente palabra)."""
    w = fold(words[i].group(0))
    if w.isdigit():
        return w, i + 1
    if w in _UNITS:
        return str(_UNITS[w]), i + 1
    if w in _TEENS:
        return str(_TEENS[w]), i + 1
    if w in _TWENTIES:
        return str(_TWENTIES[w]), i + 1
    if w in _TENS:
        if i + 2 < len(words) and fold(words[i + 1].group(0)) == "y" and fold(words[i + 2].group(0)) in _UNITS:
            unit = _UNITS[fold(words[i + 2].group(0))]
            if unit > 0:
                return str(_TENS[w] + unit), i + 3
        return str(_TENS[w]), i + 1
    return None


class NormalizingDetector:
    """Decorador de detectores: detecta sobre la vista normalizada y reproyecta los spans al texto original."""

    def __init__(self, inner: DetectorPort):
        self._inner = inner

    def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
        view = normalize(text)
        if view.text == text:
            return self._inner.detect(text, language=language)
        found = self._inner.detect(view.text, language=language)
        out: list[DetectedEntity] = []
        for e in found:
            start, end = view.project(e.start, e.end)
            out.append(DetectedEntity(e.type, start, end, text[start:end], e.score, e.source))
        return out
