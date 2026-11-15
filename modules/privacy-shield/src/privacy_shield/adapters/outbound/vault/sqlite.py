"""Vault persistente en SQLite (opcional). Mismo contrato que MemoryVault; sobrevive a reinicios.
El fichero contiene valores reales: debe estar en un disco cifrado y con permisos restringidos."""

import sqlite3
import threading
from collections.abc import Iterable
from datetime import timedelta

from privacy_shield.application.ports import ClockPort
from privacy_shield.application.textnorm import normalize_value
from privacy_shield.domain.entities import EntityType
from privacy_shield.domain.session import SessionId

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, last_used TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tokens (
    session TEXT NOT NULL, token TEXT NOT NULL, type TEXT NOT NULL, value TEXT NOT NULL,
    PRIMARY KEY (session, token));
CREATE TABLE IF NOT EXISTS keys (
    session TEXT NOT NULL, type TEXT NOT NULL, norm TEXT NOT NULL, token TEXT NOT NULL,
    PRIMARY KEY (session, type, norm));
CREATE TABLE IF NOT EXISTS aliases (session TEXT NOT NULL, token TEXT NOT NULL, alias TEXT NOT NULL);
"""
_DELETE_SESSION = (
    "DELETE FROM tokens WHERE session = ?",
    "DELETE FROM keys WHERE session = ?",
    "DELETE FROM aliases WHERE session = ?",
)


class SqliteVault:
    def __init__(self, path: str, clock: ClockPort, ttl_minutes: int = 240):
        self._clock = clock
        self._ttl = timedelta(minutes=ttl_minutes)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._db.commit()

    # ------------------------------------------------------------------ utilidades
    def _touch(self, session: SessionId, *, create: bool) -> bool:
        now = self._clock.now()
        cutoff = (now - self._ttl).isoformat()
        for sid in [r[0] for r in self._db.execute("SELECT id FROM sessions WHERE last_used < ?", (cutoff,))]:
            self._drop(sid)
        exists = self._db.execute("SELECT 1 FROM sessions WHERE id = ?", (session,)).fetchone() is not None
        if exists or create:
            self._db.execute(
                "INSERT INTO sessions (id, last_used) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET last_used = ?",
                (session, now.isoformat(), now.isoformat()),
            )
        self._db.commit()
        return exists or create

    def _drop(self, session: str) -> None:
        for statement in _DELETE_SESSION:
            self._db.execute(statement, (session,))
        self._db.execute("DELETE FROM sessions WHERE id = ?", (session,))

    def _type_of(self, session: SessionId, token: str) -> EntityType | None:
        row = self._db.execute("SELECT type FROM tokens WHERE session = ? AND token = ?", (session, token)).fetchone()
        return EntityType(row[0]) if row else None

    # ------------------------------------------------------------------ puerto
    def ensure_session(self, session: SessionId) -> None:
        with self._lock:
            self._touch(session, create=True)

    def session_exists(self, session: SessionId) -> bool:
        with self._lock:
            return self._touch(session, create=False)

    def find_token(self, session: SessionId, type: EntityType, value: str) -> str | None:
        with self._lock:
            if not self._touch(session, create=False):
                return None
            row = self._db.execute(
                "SELECT token FROM keys WHERE session = ? AND type = ? AND norm = ?",
                (session, type.value, normalize_value(type, value)),
            ).fetchone()
            return str(row[0]) if row else None

    def get_or_create_token(self, session: SessionId, type: EntityType, value: str) -> str:
        with self._lock:
            self._touch(session, create=True)
            existing = self.find_token(session, type, value)
            if existing:
                return existing
            n = self._db.execute(
                "SELECT COUNT(*) FROM tokens WHERE session = ? AND type = ?", (session, type.value)
            ).fetchone()[0]
            token = f"[{type.value}_{n + 1}]"
            self._db.execute("INSERT INTO tokens VALUES (?, ?, ?, ?)", (session, token, type.value, value))
            self._db.execute(
                "INSERT INTO keys VALUES (?, ?, ?, ?)", (session, type.value, normalize_value(type, value), token)
            )
            self._db.commit()
            return token

    def resolve(self, session: SessionId, token: str) -> str | None:
        with self._lock:
            if not self._touch(session, create=False):
                return None
            row = self._db.execute(
                "SELECT value FROM tokens WHERE session = ? AND token = ?", (session, token)
            ).fetchone()
            return str(row[0]) if row else None

    def known_values(self, session: SessionId) -> Iterable[tuple[EntityType, str]]:
        with self._lock:
            if not self._touch(session, create=False):
                return []
            out = [
                (EntityType(t), v)
                for t, v in self._db.execute("SELECT type, value FROM tokens WHERE session = ?", (session,))
            ]
            out += [
                (EntityType(t), a)
                for t, a in self._db.execute(
                    "SELECT t.type, a.alias FROM aliases a JOIN tokens t ON t.session = a.session AND t.token = a.token"
                    " WHERE a.session = ?",
                    (session,),
                )
            ]
            return out

    def add_alias(self, session: SessionId, token: str, alias: str) -> None:
        with self._lock:
            entity_type = self._type_of(session, token)
            if entity_type is None:
                return
            self._db.execute(
                "INSERT OR IGNORE INTO keys VALUES (?, ?, ?, ?)",
                (session, entity_type.value, normalize_value(entity_type, alias), token),
            )
            self._db.execute("INSERT INTO aliases VALUES (?, ?, ?)", (session, token, alias))
            self._db.commit()

    def delete_session(self, session: SessionId) -> None:
        with self._lock:
            self._drop(session)
            self._db.commit()

    def close(self) -> None:
        self._db.close()

