import pytest
from fastapi.testclient import TestClient

from transcriber import bootstrap, config
from transcriber.adapters.outbound.analysis.fake import FakeAnalyzer
from transcriber.adapters.outbound.persistence import database


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
    bootstrap.reset()
    database.init_db()
    yield tmp_path
    config.get_settings.cache_clear()
    bootstrap.reset()


@pytest.fixture
def client(env):
    from transcriber.bootstrap.api import app

    with TestClient(app, headers={"Authorization": "Bearer tok"}) as c:
        yield c


@pytest.fixture
def anon(env):
    """Cliente sin cabecera de autorización."""
    from transcriber.bootstrap.api import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def session(env):
    with bootstrap.get_runtime().session() as s:
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
