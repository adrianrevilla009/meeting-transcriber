"""Reversión tolerante de tokens, normal y en streaming (con buffer para tokens partidos en varios chunks)."""

import re
from dataclasses import dataclass

from privacy_shield.application.ports import VaultPort
from privacy_shield.application.textnorm import fold
from privacy_shield.domain.entities import EntityType
from privacy_shield.domain.session import SessionId

# Los tipos se aceptan con o sin tildes (el LLM puede escribir [ORGANIZACIÓN_1]).
_TYPE_ALT = "|".join(re.escape(t.value).replace("ION", "I[OÓ]N") for t in EntityType)
_BRACKETED = rf"\[\s*(?P<t1>{_TYPE_ALT})[\s_]*(?P<n1>\d+)\s*\]"
_BARE = rf"(?<![A-Za-z0-9_])(?P<t2>{_TYPE_ALT})_(?P<n2>\d+)(?!\d)"
TOKEN_PATTERN = re.compile(f"{_BRACKETED}|{_BARE}", re.IGNORECASE)

MAX_TOKEN_LEN = 40  # un token de verdad nunca es más largo; si no cierra antes, se vuelca tal cual

_BARE_PREFIXES = {
    (t.value + "_")[:i].lower() for t in EntityType for i in range(1, len(t.value) + 2)
} | {(t.value.replace("ION", "IÓN") + "_")[:i].lower() for t in EntityType for i in range(1, len(t.value) + 2)}
_BARE_PARTIAL = re.compile(rf"(?:{_TYPE_ALT})_\d*", re.IGNORECASE)


@dataclass(frozen=True)
class DeanonymizeResult:
    text: str
    unknown_tokens: int


def canonical_token(type_text: str, number: str) -> str:
    return f"[{fold(type_text).upper()}_{int(number)}]"


class Deanonymizer:
    def __init__(self, vault: VaultPort):
        self._vault = vault

    def deanonymize(self, session: SessionId, text: str) -> DeanonymizeResult:
        unknown = 0

        def repl(m: re.Match[str]) -> str:
            nonlocal unknown
            type_text = m.group("t1") or m.group("t2")
            number = m.group("n1") or m.group("n2")
            value = self._vault.resolve(session, canonical_token(type_text, number))
            if value is None:
                unknown += 1  # el LLM inventó un token: se deja tal cual
                return m.group(0)
            return value

        return DeanonymizeResult(TOKEN_PATTERN.sub(repl, text), unknown)


class StreamingDeanonymizer:
    """Equivalente a `Deanonymizer.deanonymize` sobre el texto completo, pero alimentado por trozos."""

    def __init__(self, deanonymizer: Deanonymizer, session: SessionId):
        self._d = deanonymizer
        self._session = session
        self._buf = ""
        self.unknown_tokens = 0

    def _convert(self, text: str) -> str:
        if not text:
            return ""
        result = self._d.deanonymize(self._session, text)
        self.unknown_tokens += result.unknown_tokens
        return result.text

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out: list[str] = []
        while True:
            i = self._buf.find("[")
            if i == -1:
                hold = _tail_to_hold(self._buf)
                cut = len(self._buf) - hold
                out.append(self._convert(self._buf[:cut]))
                self._buf = self._buf[cut:]
                break
            if i > 0:
                out.append(self._convert(self._buf[:i]))
                self._buf = self._buf[i:]
            j = self._buf.find("]")
            if j != -1 and j < MAX_TOKEN_LEN:
                out.append(self._convert(self._buf[: j + 1]))
                self._buf = self._buf[j + 1 :]
                continue
            if j != -1 or len(self._buf) >= MAX_TOKEN_LEN:
                out.append("[")  # no es un token: se vuelca el corchete y se sigue
                self._buf = self._buf[1:]
                continue
            break  # token posiblemente incompleto: esperar más datos
        return "".join(out)

    def flush(self) -> str:
        out = self._convert(self._buf)
        self._buf = ""
        return out


def _tail_to_hold(text: str) -> int:
    """Longitud del sufijo que podría ser el principio de un token sin corchetes (PERSONA_1 partido)."""
    for k in range(min(len(text), MAX_TOKEN_LEN), 0, -1):
        suffix = text[-k:]
        before = text[-k - 1] if len(text) > k else ""
        if before and (before.isalnum() or before == "_"):
            continue
        if suffix.lower() in _BARE_PREFIXES or _BARE_PARTIAL.fullmatch(suffix):
            return k
    return 0
