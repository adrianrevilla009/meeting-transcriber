"""Punto de entrada HTTP: `uvicorn --factory realtime_assistant.bootstrap.api:create`."""

from fastapi import FastAPI

from realtime_assistant.adapters.inbound.api.app import create_app
from realtime_assistant.bootstrap import build_runtime
from realtime_assistant.config import get_settings


def create() -> FastAPI:
    settings = get_settings()
    return create_app(build_runtime(settings), api_token=settings.api_token)
