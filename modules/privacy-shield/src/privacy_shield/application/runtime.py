"""Dependencias ya cableadas que reciben los adaptadores de entrada (API, CLI). Se construye en bootstrap."""

from collections.abc import Callable
from dataclasses import dataclass

from privacy_shield.application.ports import ClockPort, ProviderRegistryPort, VaultPort
from privacy_shield.application.use_cases import AnonymizeText, DeanonymizeText, ProtectedChat


@dataclass
class Runtime:
    anonymize: AnonymizeText
    deanonymize: DeanonymizeText
    chat: ProtectedChat
    vault: VaultPort
    registry: ProviderRegistryPort
    clock: ClockPort
    health: Callable[[], dict[str, object]]
