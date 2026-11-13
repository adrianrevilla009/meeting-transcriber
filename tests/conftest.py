import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.services import transcriber


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MT_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("MT_AUDIO_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("MT_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("MT_TRANSCRIBER", "fake")
    monkeypatch.setenv("MT_ANALYZER", "fake")
    monkeypatch.setenv("MT_API_TOKEN", "tok")
    config.get_settings.cache_clear()
    db.reset_engine()
    transcriber.reset_transcriber()
    db.init_db()
    yield tmp_path
    config.get_settings.cache_clear()
    db.reset_engine()


@pytest.fixture
def client(env):
    from app.api.main import app

    with TestClient(app, headers={"Authorization": "Bearer tok"}) as c:
        yield c
