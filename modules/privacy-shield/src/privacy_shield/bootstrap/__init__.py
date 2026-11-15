"""Raíz de composición: el ÚNICO sitio que conoce los adaptadores concretos y los cablea.

Cambiar de proveedor de LLM, de detector o de vault = escribir un adaptador y tocar aquí.
"""

from collections.abc import Sequence

from privacy_shield.adapters.outbound.audit.jsonl import JsonlAuditAdapter
from privacy_shield.adapters.outbound.clock import SystemClock
from privacy_shield.adapters.outbound.detectors.composite import CompositeDetector
from privacy_shield.adapters.outbound.detectors.glossary import GlossaryDetector
from privacy_shield.adapters.outbound.detectors.names import NameListDetector
from privacy_shield.adapters.outbound.detectors.org_patterns import OrgPatternDetector
from privacy_shield.adapters.outbound.detectors.regex_es import RegexDetector
from privacy_shield.adapters.outbound.detectors.spacy_ner import SpacyNerDetector
from privacy_shield.adapters.outbound.files.loaders import load_glossary, load_policy
from privacy_shield.adapters.outbound.llm.anthropic_adapter import AnthropicAdapter
from privacy_shield.adapters.outbound.llm.ollama_adapter import OllamaAdapter
from privacy_shield.adapters.outbound.llm.openai_adapter import OpenAIAdapter
from privacy_shield.adapters.outbound.llm.registry import ProviderRegistry
from privacy_shield.adapters.outbound.vault.memory import MemoryVault
from privacy_shield.adapters.outbound.vault.sqlite import SqliteVault
from privacy_shield.application.deanonymizer import Deanonymizer
from privacy_shield.application.leak_guard import LeakGuard
from privacy_shield.application.normalizer import NormalizingDetector
from privacy_shield.application.ports import AuditPort, ClockPort, DetectorPort, ProviderRegistryPort, VaultPort
from privacy_shield.application.pseudonymizer import Pseudonymizer
from privacy_shield.application.runtime import Runtime
from privacy_shield.application.use_cases import (
    Anonymizer,
    AnonymizeText,
    ChatSettings,
    DeanonymizeText,
    ProtectedChat,
)
from privacy_shield.config import Settings
from privacy_shield.domain.glossary import GlossaryTerm
from privacy_shield.domain.policy import Policy


def build_detector(settings: Settings, glossary: Sequence[GlossaryTerm] | None = None) -> DetectorPort:
    """Detector compuesto. `glossary` permite inyectar términos (el evaluador); si no, se leen del YAML."""
    terms = list(glossary) if glossary is not None else load_glossary(settings.glossary_path)
    detectors: list[DetectorPort] = [RegexDetector(), GlossaryDetector(terms)]
    if settings.names_enabled:
        detectors.append(NameListDetector())
        detectors.append(OrgPatternDetector())
    if settings.ner_enabled:
        detectors.append(SpacyNerDetector(settings.spacy_model))  # se carga una sola vez, al arrancar
    return NormalizingDetector(CompositeDetector(detectors))


def build_registry(settings: Settings) -> ProviderRegistry:
    return ProviderRegistry(
        [
            OpenAIAdapter(settings.openai_api_key, default_model=settings.openai_model),
            AnthropicAdapter(settings.anthropic_api_key, default_model=settings.anthropic_model),
            OllamaAdapter(settings.ollama_url, default_model=settings.ollama_model),
        ]
    )


def build_vault(settings: Settings, clock: ClockPort) -> VaultPort:
    if settings.vault == "sqlite":
        return SqliteVault(str(settings.vault_sqlite_path), clock, settings.vault_ttl_minutes)
    return MemoryVault(clock, settings.vault_ttl_minutes)


def build_runtime(
    settings: Settings,
    *,
    detector: DetectorPort | None = None,
    registry: ProviderRegistryPort | None = None,
    audit: AuditPort | None = None,
    vault: VaultPort | None = None,
    clock: ClockPort | None = None,
    policy: Policy | None = None,
) -> Runtime:
    """Cablea todo. Los parámetros opcionales permiten inyectar piezas (tests, evaluador)."""
    clock = clock or SystemClock()
    policy = policy or load_policy(settings.policy_path)
    detector = detector or build_detector(settings)
    registry = registry or build_registry(settings)
    audit = audit or JsonlAuditAdapter(settings.audit_path)
    vault = vault or build_vault(settings, clock)

    anonymizer = Anonymizer(detector, Pseudonymizer(vault, policy))
    deanonymizer = Deanonymizer(vault)
    guard = LeakGuard(vault, RegexDetector())  # detector independiente del principal
    chat = ProtectedChat(
        anonymizer,
        deanonymizer,
        guard,
        vault,
        registry,
        audit,
        clock,
        policy,
        ChatSettings(settings.default_provider, settings.skip_local),
    )
    registry_ref = registry

    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "ner": settings.ner_enabled,
            "spacy_model": settings.spacy_model if settings.ner_enabled else None,
            "vault": settings.vault,
            "providers": registry_ref.names(),
        }

    return Runtime(
        anonymize=AnonymizeText(anonymizer, vault, audit, clock),
        deanonymize=DeanonymizeText(deanonymizer, vault, audit, clock),
        chat=chat,
        vault=vault,
        registry=registry,
        clock=clock,
        health=health,
    )
