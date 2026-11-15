"""Utilidades compartidas por los tests: reloj falso, detector sin NER y construcción del runtime con proveedor falso."""

from datetime import UTC, datetime, timedelta

from privacy_shield.adapters.outbound.audit.memory import MemoryAuditAdapter
from privacy_shield.adapters.outbound.detectors.composite import CompositeDetector
from privacy_shield.adapters.outbound.detectors.glossary import GlossaryDetector
from privacy_shield.adapters.outbound.detectors.names import NameListDetector
from privacy_shield.adapters.outbound.detectors.regex_es import RegexDetector
from privacy_shield.adapters.outbound.llm.fake_adapter import FakeLLMAdapter
from privacy_shield.adapters.outbound.llm.registry import ProviderRegistry
from privacy_shield.adapters.outbound.vault.memory import MemoryVault
from privacy_shield.application.normalizer import NormalizingDetector
from privacy_shield.application.ports import DetectorPort, LLMPort
from privacy_shield.application.runtime import Runtime
from privacy_shield.bootstrap import build_runtime
from privacy_shield.config import Settings
from privacy_shield.domain.entities import EntityType
from privacy_shield.domain.glossary import GlossaryTerm
from privacy_shield.domain.policy import Policy

CANARY_NAME = "Zoltrabek Quillfeather"
GLOSSARY = [
    GlossaryTerm(CANARY_NAME, EntityType.PERSONA),
    GlossaryTerm("Proyecto Quimera", EntityType.GLOSARIO, ("Quimera",)),
]


class FakeClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)
        self._perf = 0.0

    def now(self) -> datetime:
        return self._now

    def perf_ms(self) -> float:
        self._perf += 1.0
        return self._perf

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)


def make_detector() -> DetectorPort:
    """Regex + glosario + lista de nombres (sin spaCy), con normalizador de ASR."""
    return NormalizingDetector(CompositeDetector([RegexDetector(), GlossaryDetector(GLOSSARY), NameListDetector()]))


def make_runtime(
    *,
    adapters: list[LLMPort] | None = None,
    detector: DetectorPort | None = None,
    policy: Policy | None = None,
    skip_local: bool = True,
    default_provider: str = "fake",
) -> tuple[Runtime, MemoryAuditAdapter, FakeClock]:
    clock = FakeClock()
    audit = MemoryAuditAdapter()
    settings = Settings(ner_enabled=False, default_provider=default_provider, skip_local=skip_local)
    rt = build_runtime(
        settings,
        detector=detector or make_detector(),
        registry=ProviderRegistry(adapters if adapters is not None else [FakeLLMAdapter()]),
        audit=audit,
        vault=MemoryVault(clock),
        clock=clock,
        policy=policy,
    )
    return rt, audit, clock
