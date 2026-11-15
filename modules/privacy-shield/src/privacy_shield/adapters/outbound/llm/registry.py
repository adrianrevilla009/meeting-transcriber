"""Registro de proveedores: nombre -> adaptador. Añadir un proveedor = un archivo nuevo + registrarlo en bootstrap."""

from collections.abc import Iterable

from privacy_shield.application.ports import LLMPort
from privacy_shield.domain.errors import ProviderNotFound


class ProviderRegistry:
    def __init__(self, adapters: Iterable[LLMPort] = ()):
        self._adapters: dict[str, LLMPort] = {a.name: a for a in adapters}

    def register(self, adapter: LLMPort) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> LLMPort:
        try:
            return self._adapters[name]
        except KeyError:
            raise ProviderNotFound(f"Proveedor '{name}' no registrado") from None

    def names(self) -> list[str]:
        return sorted(self._adapters)
