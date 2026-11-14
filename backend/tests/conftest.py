import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.db import session_factory
from app.services import transcriber
from app.services.analyzer import FakeAnalyzer


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MT_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("MT_AUDIO_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("MT_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("MT_TRANSCRIBER", "fake")
    monkeypatch.setenv("MT_ANALYZER", "fake")
    monkeypatch.setenv("MT_API_TOKEN", "tok")
    monkeypatch.setenv("MT_AUDIO_RETENTION_DAYS", "0")
    config.get_settings.cache_clear()
    db.reset_engine()
    transcriber.reset_transcriber()
    db.init_db()
    yield tmp_path
    config.get_settings.cache_clear()
    db.reset_engine()
    transcriber.reset_transcriber()


@pytest.fixture
def client(env):
    from app.api.main import app

    with TestClient(app, headers={"Authorization": "Bearer tok"}) as c:
        yield c


@pytest.fixture
def anon(env):
    """Cliente sin cabecera de autorización."""
    from app.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def session(env):
    with session_factory()() as s:
        yield s


@pytest.fixture(autouse=True)
def _reset_fake_analyzer():
    FakeAnalyzer.script = ""
    yield
    FakeAnalyzer.script = ""


@pytest.fixture
def set_env(monkeypatch):
    """Cambia una variable MT_* y recarga la configuración."""

    def _set(name: str, value: str) -> None:
        monkeypatch.setenv(name, value)
        config.get_settings.cache_clear()

    return _set
