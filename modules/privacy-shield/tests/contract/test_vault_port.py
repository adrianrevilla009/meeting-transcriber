"""Contrato de VaultPort: lo cumplen el vault en memoria y el de SQLite."""

from collections.abc import Callable
from pathlib import Path

import pytest

from privacy_shield.adapters.outbound.vault.memory import MemoryVault
from privacy_shield.adapters.outbound.vault.sqlite import SqliteVault
from privacy_shield.application.ports import VaultPort
from privacy_shield.domain.entities import EntityType
from privacy_shield.domain.session import SessionId
from tests.helpers import FakeClock

S = SessionId("s1")


@pytest.fixture(params=["memory", "sqlite"])
def make_vault(request: pytest.FixtureRequest, tmp_path: Path) -> Callable[[FakeClock], VaultPort]:
    def factory(clock: FakeClock) -> VaultPort:
        if request.param == "memory":
            return MemoryVault(clock, ttl_minutes=240)
        return SqliteVault(str(tmp_path / "vault.sqlite3"), clock, ttl_minutes=240)

    return factory


def test_tokens_are_numbered_per_type(make_vault: Callable[[FakeClock], VaultPort]) -> None:
    v = make_vault(FakeClock())
    assert v.get_or_create_token(S, EntityType.PERSONA, "Marta García") == "[PERSONA_1]"
    assert v.get_or_create_token(S, EntityType.PERSONA, "Luis Pérez") == "[PERSONA_2]"
    assert v.get_or_create_token(S, EntityType.EMAIL, "a@b.es") == "[EMAIL_1]"


def test_same_value_same_token_across_formats(make_vault: Callable[[FakeClock], VaultPort]) -> None:
    v = make_vault(FakeClock())
    assert v.get_or_create_token(S, EntityType.PERSONA, "Marta García") == "[PERSONA_1]"
    assert v.get_or_create_token(S, EntityType.PERSONA, "  MARTA   garcia ") == "[PERSONA_1]"
    assert v.get_or_create_token(S, EntityType.TELEFONO, "612 345 678") == "[TELEFONO_1]"
    assert v.get_or_create_token(S, EntityType.TELEFONO, "+34 612345678") == "[TELEFONO_1]"


def test_sessions_are_isolated(make_vault: Callable[[FakeClock], VaultPort]) -> None:
    v = make_vault(FakeClock())
    v.get_or_create_token(SessionId("a"), EntityType.PERSONA, "Marta")
    assert v.get_or_create_token(SessionId("b"), EntityType.PERSONA, "Luis") == "[PERSONA_1]"
    assert v.find_token(SessionId("b"), EntityType.PERSONA, "Marta") is None


def test_resolve_returns_the_first_seen_form(make_vault: Callable[[FakeClock], VaultPort]) -> None:
    v = make_vault(FakeClock())
    token = v.get_or_create_token(S, EntityType.PERSONA, "Marta García")
    v.get_or_create_token(S, EntityType.PERSONA, "marta garcia")
    assert v.resolve(S, token) == "Marta García"
    assert v.resolve(S, "[PERSONA_9]") is None
    assert v.resolve(SessionId("desconocida"), token) is None


def test_find_token_does_not_create(make_vault: Callable[[FakeClock], VaultPort]) -> None:
    v = make_vault(FakeClock())
    v.ensure_session(S)
    assert v.find_token(S, EntityType.PERSONA, "Nadie") is None
    assert list(v.known_values(S)) == []


def test_known_values_include_aliases(make_vault: Callable[[FakeClock], VaultPort]) -> None:
    v = make_vault(FakeClock())
    token = v.get_or_create_token(S, EntityType.PERSONA, "Marta García")
    v.add_alias(S, token, "Marta")
    assert v.find_token(S, EntityType.PERSONA, "marta") == token
    assert set(v.known_values(S)) == {(EntityType.PERSONA, "Marta García"), (EntityType.PERSONA, "Marta")}


def test_alias_of_unknown_token_is_ignored(make_vault: Callable[[FakeClock], VaultPort]) -> None:
    v = make_vault(FakeClock())
    v.ensure_session(S)
    v.add_alias(S, "[PERSONA_7]", "Nadie")
    assert list(v.known_values(S)) == []


def test_delete_session(make_vault: Callable[[FakeClock], VaultPort]) -> None:
    v = make_vault(FakeClock())
    v.get_or_create_token(S, EntityType.PERSONA, "Marta")
    assert v.session_exists(S)
    v.delete_session(S)
    assert not v.session_exists(S)
    assert v.get_or_create_token(S, EntityType.PERSONA, "Luis") == "[PERSONA_1]"  # contador reiniciado


def test_sessions_expire_after_the_ttl(make_vault: Callable[[FakeClock], VaultPort]) -> None:
    clock = FakeClock()
    v = make_vault(clock)
    token = v.get_or_create_token(S, EntityType.PERSONA, "Marta")
    clock.advance(minutes=239)
    assert v.resolve(S, token) == "Marta"  # usar la sesión renueva el plazo
    clock.advance(minutes=239)
    assert v.session_exists(S)
    clock.advance(minutes=241)
    assert not v.session_exists(S)
    assert v.resolve(S, token) is None


def test_sqlite_vault_survives_a_restart(tmp_path: Path) -> None:
    clock = FakeClock()
    path = str(tmp_path / "persist.sqlite3")
    first = SqliteVault(path, clock)
    token = first.get_or_create_token(S, EntityType.EMAIL, "ana@example.org")
    first.close()
    second = SqliteVault(path, clock)
    assert second.resolve(S, token) == "ana@example.org"
    assert second.get_or_create_token(S, EntityType.EMAIL, "ANA@example.org") == token
