"""Punto de entrada HTTP: `uvicorn --factory privacy_shield.bootstrap.api:create`."""

from fastapi import FastAPI

from privacy_shield.adapters.inbound.api.app import create_app
from privacy_shield.bootstrap import build_runtime
from privacy_shield.config import get_settings


def create() -> FastAPI:
    settings = get_settings()
    return create_app(build_runtime(settings), api_token=settings.api_token, debug_mapping=settings.debug_mapping)
