# syntax=docker/dockerfile:1.7
# ---- build: instala dependencias en un venv aislado ----
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml ./
COPY app ./app
RUN pip install "pip==26.3" && pip install ".[whisper]"

# ---- runtime: solo el venv y el código, sin herramientas de build, usuario sin privilegios ----
FROM python:3.12-slim
LABEL org.opencontainers.image.title="meeting-transcriber-api" \
      org.opencontainers.image.description="API y worker de transcripción local (FastAPI + faster-whisper)" \
      org.opencontainers.image.source="https://github.com/adrianrevilla009/meeting-transcriber"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH"
WORKDIR /srv
RUN useradd --system --uid 10001 --no-create-home mt && mkdir -p /data && chown mt /data
COPY --from=build /opt/venv /opt/venv
COPY --chown=mt app ./app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
