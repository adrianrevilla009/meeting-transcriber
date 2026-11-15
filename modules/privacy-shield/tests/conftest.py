import pytest

from privacy_shield.adapters.outbound.detectors.spacy_ner import SpacyNerDetector
from privacy_shield.adapters.outbound.vault.memory import MemoryVault
from privacy_shield.application.ports import VaultPort
from privacy_shield.domain.errors import DetectorUnavailable
from privacy_shield.domain.session import SessionId
from tests.helpers import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def vault(clock: FakeClock) -> VaultPort:
    return MemoryVault(clock)


@pytest.fixture
def session(vault: VaultPort) -> SessionId:
    sid = SessionId("sesion-de-prueba")
    vault.ensure_session(sid)
    return sid


@pytest.fixture(scope="session")
def ner_detector() -> SpacyNerDetector:
    """spaCy y el modelo español: se salta si no están instalados (en CI sí lo están)."""
    pytest.importorskip("spacy")
    try:
        return SpacyNerDetector("es_core_news_md")
    except DetectorUnavailable:
        pytest.skip("Falta el modelo es_core_news_md")
