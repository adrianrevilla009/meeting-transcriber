"""Utilidades HTTP compartidas por los adaptadores de LLM: allowlist de destinos y manejo de errores."""

from collections.abc import Iterable
from urllib.parse import urlparse

import httpx

from privacy_shield.domain.errors import ProviderError


class AllowlistTransport(httpx.AsyncBaseTransport):
    """Solo deja salir peticiones hacia hosts concretos: cualquier otro destino lanza ProviderError."""

    def __init__(self, allowed_hosts: Iterable[str], inner: httpx.AsyncBaseTransport | None = None):
        self._allowed = {h.lower() for h in allowed_hosts}
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host.lower()
        if host not in self._allowed:
            raise ProviderError(f"Destino no permitido por la allowlist de salida: {host}")
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def host_of(url: str) -> str:
    return urlparse(url).hostname or ""


def make_client(base_url: str, client: httpx.AsyncClient | None, timeout: float) -> httpx.AsyncClient:
    """Cliente cuyo transporte solo permite el host del proveedor (salvo que se inyecte uno, p. ej. en tests)."""
    return client or httpx.AsyncClient(transport=AllowlistTransport([host_of(base_url)]), timeout=timeout)


def check_status(response: httpx.Response, provider: str) -> None:
    """Falla con un mensaje seguro: nunca incluye el cuerpo (podría eco de datos)."""
    if response.status_code >= 400:
        raise ProviderError(f"{provider} respondió con HTTP {response.status_code}")
