from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor centinela: no es una credencial, marca que ANON_API_TOKEN no está configurado.
UNSET_TOKEN = "change-me"  # noqa: S105  # nosec B105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANON_", env_file=".env", extra="ignore")

    # Seguridad: token Bearer para toda la API (salvo /health). Sin configurar, la API rechaza todo.
    api_token: str = UNSET_TOKEN
    bind: str = "127.0.0.1"
    port: int = 8100

    # Proveedores de LLM
    default_provider: str = "anthropic"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    skip_local: bool = True  # los proveedores locales no necesitan pseudonimización

    # Detección
    spacy_model: str = "es_core_news_md"
    ner_enabled: bool = True
    names_enabled: bool = True
    glossary_path: Path | None = Path("config/glossary.yaml")
    policy_path: Path | None = Path("config/policy.yaml")

    # Vault de sesión
    vault: str = "memory"  # memory | sqlite
    vault_ttl_minutes: int = 240
    vault_sqlite_path: Path = Path("./vault.sqlite3")

    debug_mapping: bool = False  # expone GET /v1/sessions/{id}/mapping (solo depuración local)
    audit_path: Path = Path("./audit.jsonl")


@lru_cache
def get_settings() -> Settings:
    return Settings()
