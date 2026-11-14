"""Punto de entrada HTTP: `uvicorn transcriber.bootstrap.api:app`."""

from transcriber.adapters.inbound.api.app import create_app
from transcriber.bootstrap import get_runtime

app = create_app(get_runtime())
