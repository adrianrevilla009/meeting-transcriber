FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install "fastapi>=0.115" "uvicorn>=0.30"
COPY app.py .
RUN useradd --system --uid 10001 --no-create-home stub
USER 10001
EXPOSE 11434
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "11434"]
