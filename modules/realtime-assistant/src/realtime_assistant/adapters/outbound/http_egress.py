"""Salida HTTP restringida: cada cliente solo puede hablar con el host de su servicio.

El asistente NO tiene acceso directo a ningún LLM externo: solo al módulo 1 (transcripción), a privacy-shield y a un
Ollama local. Cualquier otro destino se rechaza aquí, aunque alguien cambiara una URL por error.
"""

from collections.abc import Iterable
from urllib.parse import urlparse

import httpx


class EgressBlocked(Exception):
    """Destino no permitido por la allowlist de salida."""


class AllowlistTransport(httpx.AsyncBaseTransport):
    def __init__(self, allowed_hosts: Iterable[str], inner: httpx.AsyncBaseTransport | None = None):
        self._allowed = {h.lower() for h in allowed_hosts}
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host.lower()
        if host not in self._allowed:
            raise EgressBlocked(f"Destino no permitido: {host}")
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def make_client(base_url: str, client: httpx.AsyncClient | None, timeout: float) -> httpx.AsyncClient:
    """Cliente cuyo transporte solo permite el host de `base_url` (salvo que se inyecte uno, p. ej. en tests)."""
    host = urlparse(base_url).hostname or ""
    return client or httpx.AsyncClient(transport=AllowlistTransport([host]), timeout=timeout)
