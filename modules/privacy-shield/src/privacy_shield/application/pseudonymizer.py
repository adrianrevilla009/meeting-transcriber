"""Aplica la política y el vault de sesión sobre los spans detectados."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from privacy_shield.application.ports import VaultPort
from privacy_shield.application.textnorm import fold, normalize_value
from privacy_shield.domain.entities import DetectedEntity, EntityType
from privacy_shield.domain.errors import BlockedByPolicy
from privacy_shield.domain.policy import Policy, Strategy
from privacy_shield.domain.session import SessionId

TOKEN_RE = re.compile(r"\[[A-Z_]+(?:_\d+)?\]")


@dataclass(frozen=True)
class Replacement:
    type: EntityType
    token: str
    strategy: Strategy


@dataclass(frozen=True)
class AnonymizedText:
    text: str
    replacements: tuple[Replacement, ...]


class Pseudonymizer:
    def __init__(self, vault: VaultPort, policy: Policy):
        self._vault = vault
        self._policy = policy

    def apply(self, session: SessionId, text: str, entities: Sequence[DetectedEntity]) -> AnonymizedText:
        kept = [
            e
            for e in sorted(entities, key=lambda e: e.start)
            if e.score >= self._policy.min_score_for(e.type) and self._policy.strategy_for(e.type) != Strategy.ALLOW
        ]
        blocked = [e.type for e in kept if self._policy.strategy_for(e.type) == Strategy.BLOCK]
        if blocked:
            raise BlockedByPolicy(blocked)

        # Los tokens se asignan en orden de aparición; el reemplazo se hace de final a principio.
        planned: list[tuple[DetectedEntity, Replacement]] = []
        for e in kept:
            strategy = self._policy.strategy_for(e.type)
            planned.append((e, Replacement(e.type, self._token_for(session, e, strategy), strategy)))
        out = text
        for e, rep in reversed(planned):
            out = out[: e.start] + rep.token + out[e.end :]
        out = self._sweep_known(session, out)
        return AnonymizedText(out, tuple(rep for _, rep in planned))

    # ------------------------------------------------------------------ tokens
    def _token_for(self, session: SessionId, e: DetectedEntity, strategy: Strategy) -> str:
        if strategy == Strategy.MASK:
            return f"[{e.type.value}]"
        if e.type == EntityType.PERSONA:
            return self._persona_token(session, e.text)
        return self._vault.get_or_create_token(session, e.type, e.text)

    def _persona_token(self, session: SessionId, value: str) -> str:
        """Reutiliza el token de 'Marta García' para 'Marta' si el alias no es ambiguo en la sesión."""
        existing = self._vault.find_token(session, EntityType.PERSONA, value)
        if existing:
            return existing
        words = normalize_value(EntityType.PERSONA, value).split()
        by_token: dict[str, set[str]] = {}
        for t, known in self._vault.known_values(session):
            if t != EntityType.PERSONA:
                continue
            tok = self._vault.find_token(session, EntityType.PERSONA, known)
            if tok:
                by_token.setdefault(tok, set()).add(normalize_value(EntityType.PERSONA, known))
        same_first_full = [
            tok
            for tok, values in by_token.items()
            if any(len(v.split()) > 1 and v.split()[0] == words[0] for v in values)
        ]
        if len(words) == 1:  # solo nombre de pila: debe haber exactamente una persona con ese nombre completo
            if len(same_first_full) == 1:
                self._vault.add_alias(session, same_first_full[0], value)
                return same_first_full[0]
        else:  # nombre completo: ¿existe una persona conocida solo por su nombre de pila?
            first_only = [tok for tok, values in by_token.items() if values == {words[0]}]
            if len(first_only) == 1 and not same_first_full:
                self._vault.add_alias(session, first_only[0], value)
                return first_only[0]
        return self._vault.get_or_create_token(session, EntityType.PERSONA, value)

    # ------------------------------------------------------------------ barrido
    def _sweep_known(self, session: SessionId, text: str) -> str:
        """Sustituye apariciones que el detector no marcó de valores ya conocidos en la sesión."""
        pairs: list[tuple[str, str]] = []
        for t, value in self._vault.known_values(session):
            if self._policy.strategy_for(t) != Strategy.PSEUDONYMIZE or len(value.strip()) < 3:
                continue
            token = self._vault.find_token(session, t, value)
            if token:
                pairs.append((value, token))
        if not pairs:
            return text
        pairs.sort(key=lambda p: len(p[0]), reverse=True)  # primero los valores más largos
        parts: list[str] = []
        last = 0
        for m in TOKEN_RE.finditer(text):
            parts.append(_sweep_segment(text[last : m.start()], pairs))
            parts.append(m.group(0))
            last = m.end()
        parts.append(_sweep_segment(text[last:], pairs))
        return "".join(parts)


def _sweep_segment(segment: str, pairs: list[tuple[str, str]]) -> str:
    if not segment.strip():
        return segment
    folded = fold(segment)
    spans: list[tuple[int, int, str]] = []
    taken = [False] * len(segment)
    for value, token in pairs:
        needle = fold(value)
        for m in re.finditer(rf"(?<!\w){re.escape(needle)}(?!\w)", folded):
            if any(taken[m.start() : m.end()]):
                continue
            for i in range(m.start(), m.end()):
                taken[i] = True
            spans.append((m.start(), m.end(), token))
    for start, end, token in sorted(spans, reverse=True):
        segment = segment[:start] + token + segment[end:]
    return segment
