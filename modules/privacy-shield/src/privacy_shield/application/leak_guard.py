"""Segunda barrera: comprueba lo que va a SALIR, de forma independiente del detector principal."""

import re
from collections.abc import Sequence

from privacy_shield.application.ports import DetectorPort, VaultPort
from privacy_shield.application.pseudonymizer import TOKEN_RE
from privacy_shield.application.textnorm import fold
from privacy_shield.domain.entities import EntityType
from privacy_shield.domain.errors import LeakDetected
from privacy_shield.domain.session import SessionId

FUZZY_MIN_LEN = 6  # tolerancia de 1 edición solo para valores de al menos esta longitud
_MIN_VALUE_LEN = 3


class LeakGuard:
    def __init__(self, vault: VaultPort, regex_detector: DetectorPort):
        self._vault = vault
        self._regex = regex_detector

    def check(self, session: SessionId, payload_texts: Sequence[str]) -> None:
        """Lanza LeakDetected si algún valor real de la sesión (o un dato con formato sensible) sigue en el payload."""
        cleaned = [TOKEN_RE.sub(" ", t) for t in payload_texts if t]
        counts: dict[EntityType, int] = {}

        haystack = fold("\n".join(cleaned))
        for entity_type, value in self._vault.known_values(session):
            needle = " ".join(fold(value).split())
            if len(needle) < _MIN_VALUE_LEN:
                continue
            if contains_value(haystack, needle):
                counts[entity_type] = counts.get(entity_type, 0) + 1

        for text in cleaned:
            for e in self._regex.detect(text):
                counts[e.type] = counts.get(e.type, 0) + 1

        if counts:
            raise LeakDetected(counts)


def contains_value(haystack: str, needle: str) -> bool:
    """¿Aparece `needle` en `haystack` como palabra(s) completa(s)? Con tolerancia de 1 edición si es largo."""
    if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
        return True
    if len(needle) < FUZZY_MIN_LEN:
        return False
    return _fuzzy_contains(haystack, needle)


def _fuzzy_contains(haystack: str, needle: str) -> bool:
    n = len(needle)
    for length in (n - 1, n, n + 1):
        for i in range(len(haystack) - length + 1):
            if i > 0 and (haystack[i - 1].isalnum() or haystack[i - 1] == "_"):
                continue  # la ventana debe empezar en inicio de palabra
            end = i + length
            if end < len(haystack) and (haystack[end].isalnum() or haystack[end] == "_"):
                continue  # y terminar en fin de palabra
            if _near_first_char(haystack, i, needle) and within_one_edit(haystack[i:end], needle):
                return True
    return False


def _near_first_char(haystack: str, i: int, needle: str) -> bool:
    """Filtro barato: las dos primeras letras de la ventana deben parecerse al inicio del valor."""
    window = haystack[i : i + 3]
    return needle[0] in window or needle[1] in window


def within_one_edit(a: str, b: str) -> bool:
    """Distancia de edición (inserción, borrado o sustitución) <= 1."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    i = 0
    while i < min(la, lb) and a[i] == b[i]:
        i += 1
    if la == lb:
        return a[i + 1 :] == b[i + 1 :]
    if la < lb:
        a, b = b, a
    return a[i + 1 :] == b[i:]
