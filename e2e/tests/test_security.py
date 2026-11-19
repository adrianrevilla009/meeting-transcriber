"""E2E de seguridad: autenticación en todos los servicios, cabeceras de la web y aislamiento de red de los contenedores."""

import json

import httpx
import pytest
from helpers import COMPOSE, SHIELD, compose

PROTECTED = [
    ("get", "/api/meetings"),
    ("post", "/api/meetings"),
    ("get", "/api/search?q=hola"),
    ("get", "/api/system"),
    ("get", "/assistant/v1/meetings/1/status"),
    ("post", "/assistant/v1/meetings/1/follow"),
    ("post", "/assistant/v1/meetings/1/ask"),
    ("get", "/assistant/v1/meetings/1/events"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_everything_protected_rejects_missing_or_wrong_tokens(anon: httpx.Client, method: str, path: str) -> None:
    assert getattr(anon, method)(path).status_code == 401
    assert getattr(anon, method)(path, headers={"Authorization": "Bearer token-incorrecto"}).status_code == 401


def test_the_shield_token_is_not_the_web_token(web: httpx.Client) -> None:
    """Cada servicio valida su propio token: el de la web no abre el filtro de privacidad."""
    with httpx.Client(base_url=SHIELD, headers=web.headers, timeout=10) as client:
        assert client.get("/v1/providers").status_code == 401


def test_public_endpoints_are_only_health_checks(anon: httpx.Client) -> None:
    assert anon.get("/healthz").status_code == 200
    assert anon.get("/api/health").json() == {"status": "ok"}
    assert anon.get("/assistant/health").json()["status"] == "ok"


@pytest.mark.parametrize("path", ["/", "/healthz", "/assistant/health"])
def test_web_sends_security_headers_also_through_the_assistant_proxy(anon: httpx.Client, path: str) -> None:
    headers = anon.get(path).headers
    csp = headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert headers["x-content-type-options"] == "nosniff"
    assert "microphone=(self)" in headers["permissions-policy"]


# ------------------------------------------------------------------ red
def published_ports() -> dict[str, list[dict[str, object]]]:
    out = compose("ps", "--format", "json").stdout.strip()
    rows = json.loads(out) if out.startswith("[") else [json.loads(line) for line in out.splitlines() if line.strip()]
    return {r["Service"]: [p for p in (r.get("Publishers") or []) if p.get("PublishedPort")] for r in rows}


def test_only_the_expected_ports_are_published_and_only_on_localhost() -> None:
    assert COMPOSE, "E2E_COMPOSE no definido"
    ports = published_ports()
    assert ports["assistant"] == [] and ports["db"] == [] and ports["worker"] == []  # al asistente solo se llega por la web
    assert {s for s, p in ports.items() if p} == {"api", "web", "privacy-shield", "stub-llm"}
    for service, published in ports.items():
        for port in published:
            assert port["URL"] in ("127.0.0.1", "::1"), f"{service} publica fuera de localhost: {port}"


def python_in(service: str, code: str) -> int:
    return compose("exec", "-T", service, "python", "-c", code, timeout=60).returncode


REACH = "import urllib.request; urllib.request.urlopen('{url}', timeout=5)"


@pytest.mark.parametrize("service", ["assistant", "worker"])
def test_containers_without_the_edge_network_cannot_reach_the_internet(service: str) -> None:
    assert python_in(service, REACH.format(url="https://example.com")) != 0
    assert python_in(service, REACH.format(url="http://1.1.1.1")) != 0


def test_the_assistant_reaches_exactly_what_it_needs() -> None:
    """Control positivo del método de prueba: lo permitido sí responde."""
    assert python_in("assistant", REACH.format(url="http://api:8000/health")) == 0
    assert python_in("assistant", REACH.format(url="http://privacy-shield:8100/health")) == 0
    assert python_in("assistant", REACH.format(url="http://stub-llm:11434/health")) == 0
