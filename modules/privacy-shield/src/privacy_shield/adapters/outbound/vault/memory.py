"""Vault en memoria con TTL: nunca toca el disco. Lo usa el servicio por defecto."""

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from privacy_shield.application.ports import ClockPort
from privacy_shield.application.textnorm import normalize_value
from privacy_shield.domain.entities import EntityType
from privacy_shield.domain.session import SessionId


@dataclass
class _Session:
    last_used: datetime
    counters: dict[EntityType, int] = field(default_factory=dict)
    by_key: dict[tuple[EntityType, str], str] = field(default_factory=dict)
    values: dict[str, str] = field(default_factory=dict)  # token -> valor tal como se vio por primera vez
    types: dict[str, EntityType] = field(default_factory=dict)
    aliases: dict[str, list[str]] = field(default_factory=dict)


class MemoryVault:
    def __init__(self, clock: ClockPort, ttl_minutes: int = 240):
        self._clock = clock
        self._ttl = timedelta(minutes=ttl_minutes)
        self._sessions: dict[SessionId, _Session] = {}
        self._lock = threading.RLock()

    def _purge(self, now: datetime) -> None:
        expired = [sid for sid, s in self._sessions.items() if now - s.last_used > self._ttl]
        for sid in expired:
            del self._sessions[sid]

    def _get(self, session: SessionId, *, create: bool = False) -> _Session | None:
        now = self._clock.now()
        self._purge(now)
        found = self._sessions.get(session)
        if found is None and create:
            found = _Session(last_used=now)
            self._sessions[session] = found
        if found is not None:
            found.last_used = now
        return found

    def ensure_session(self, session: SessionId) -> None:
        with self._lock:
            self._get(session, create=True)

    def session_exists(self, session: SessionId) -> bool:
        with self._lock:
            return self._get(session) is not None

    def find_token(self, session: SessionId, type: EntityType, value: str) -> str | None:
        with self._lock:
            s = self._get(session)
            return s.by_key.get((type, normalize_value(type, value))) if s else None

    def get_or_create_token(self, session: SessionId, type: EntityType, value: str) -> str:
        with self._lock:
            s = self._get(session, create=True)
            if s is None:  # no ocurre con create=True; satisface al tipado
                raise RuntimeError("sesión no creada")
            key = (type, normalize_value(type, value))
            token = s.by_key.get(key)
            if token is None:
                s.counters[type] = s.counters.get(type, 0) + 1
                token = f"[{type.value}_{s.counters[type]}]"
                s.by_key[key] = token
                s.values[token] = value
                s.types[token] = type
            return token

    def resolve(self, session: SessionId, token: str) -> str | None:
        with self._lock:
            s = self._get(session)
            return s.values.get(token) if s else None

    def known_values(self, session: SessionId) -> Iterable[tuple[EntityType, str]]:
        with self._lock:
            s = self._get(session)
            if s is None:
                return []
            out = [(s.types[token], value) for token, value in s.values.items()]
            for token, aliases in s.aliases.items():
                out.extend((s.types[token], alias) for alias in aliases)
            return out

    def add_alias(self, session: SessionId, token: str, alias: str) -> None:
        with self._lock:
            s = self._get(session)
            if s is None or token not in s.types:
                return
            entity_type = s.types[token]
            s.by_key.setdefault((entity_type, normalize_value(entity_type, alias)), token)
            s.aliases.setdefault(token, []).append(alias)

    def delete_session(self, session: SessionId) -> None:
        with self._lock:
            self._sessions.pop(session, None)
