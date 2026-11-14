"""Adaptador de persistencia: motor y sesiones de SQLAlchemy (Postgres en producción, SQLite en tests)."""

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from transcriber.config import get_settings
from transcriber.domain.base import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        _engine = create_engine(url, pool_pre_ping=True, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def new_session() -> Session:
    get_engine()
    if _SessionLocal is None:  # get_engine() siempre lo inicializa
        raise RuntimeError("Base de datos no inicializada")
    return _SessionLocal()


def init_db() -> None:
    from transcriber.domain import models  # noqa: F401  (registra las tablas en Base.metadata)

    engine = get_engine()
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    """Bases creadas antes de existir `meetings.summary`: create_all no altera tablas existentes."""
    cols = {c["name"] for c in inspect(engine).get_columns("meetings")}
    if "summary" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE meetings ADD COLUMN summary TEXT"))


def reset_engine() -> None:
    """Solo para tests."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
