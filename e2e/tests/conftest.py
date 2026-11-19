from collections.abc import Iterator

import httpx
import pytest
from helpers import ANON_TOKEN, MT_TOKEN, SHIELD, STUB, WEB, bearer, wait_until


@pytest.fixture(scope="session", autouse=True)
def stack_ready() -> None:
    """El stack debe estar entero arriba antes de empezar (en CI lo levanta el workflow)."""

    def ready() -> bool:
        with httpx.Client(timeout=5) as c:
            urls = [f"{WEB}/healthz", f"{WEB}/api/health", f"{WEB}/assistant/health", f"{SHIELD}/health", f"{STUB}/health"]
            return all(c.get(u).status_code == 200 for u in urls)

    wait_until(ready, timeout=240, interval=2, what="que el stack responda (web, api, asistente, shield, stub)")


@pytest.fixture(scope="session")
def web() -> Iterator[httpx.Client]:
    """Cliente de la web (nginx) con el token del transcriber: /api/... y /assistant/..."""
    with httpx.Client(base_url=WEB, headers=bearer(MT_TOKEN), timeout=30) as client:
        yield client


@pytest.fixture(scope="session")
def anon() -> Iterator[httpx.Client]:
    """Cliente sin token, para comprobar que todo lo protegido se rechaza."""
    with httpx.Client(base_url=WEB, timeout=30) as client:
        yield client


@pytest.fixture(scope="session")
def shield() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=SHIELD, headers=bearer(ANON_TOKEN), timeout=60) as client:
        yield client


@pytest.fixture(scope="session")
def stub() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=STUB, timeout=10) as client:
        yield client


@pytest.fixture(autouse=True)
def clean_stub(stub: httpx.Client) -> None:
    stub.delete("/_captured")


@pytest.fixture
def meetings(web: httpx.Client) -> Iterator[list[int]]:
    """Reuniones creadas por el test: se dejan de seguir y se borran al terminar."""
    created: list[int] = []
    yield created
    for meeting_id in created:
        web.delete(f"/assistant/v1/meetings/{meeting_id}/follow")
        web.delete(f"/api/meetings/{meeting_id}")
