FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
RUN pip install ".[whisper]" && useradd -r -u 10001 mt && mkdir -p /data && chown mt /data
USER mt
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
