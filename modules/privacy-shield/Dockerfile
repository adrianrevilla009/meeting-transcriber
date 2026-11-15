# syntax=docker/dockerfile:1.7
# ---- build: dependencias (incluido spaCy y el modelo español) en un venv aislado ----
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml ./
COPY src ./src
RUN pip install "pip==26.3" \
 && pip install ".[ner]" \
 && pip install "https://github.com/explosion/spacy-models/releases/download/es_core_news_md-3.8.0/es_core_news_md-3.8.0-py3-none-any.whl"

# ---- runtime: solo el venv y la configuración, usuario sin privilegios ----
FROM python:3.12-slim
LABEL org.opencontainers.image.title="privacy-shield" \
      org.opencontainers.image.description="Proxy de ofuscacion de datos personales para LLMs externos" \
      org.opencontainers.image.source="https://github.com/adrianrevilla009/meeting-transcriber"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH"
WORKDIR /app
RUN useradd --system --uid 10001 --no-create-home shield && mkdir -p /data && chown shield /data
COPY --from=build /opt/venv /opt/venv
COPY --chown=shield config ./config
ENV ANON_AUDIT_PATH=/data/audit.jsonl ANON_VAULT_SQLITE_PATH=/data/vault.sqlite3
USER 10001
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "--factory", "privacy_shield.bootstrap.api:create", "--host", "0.0.0.0", "--port", "8100"]
