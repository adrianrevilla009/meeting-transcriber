"""E2E de resiliencia (se ejecuta el último: para y arranca un contenedor)."""

import httpx
from helpers import compose, wait_until


def test_the_web_and_the_transcriber_keep_working_when_the_assistant_is_down(anon: httpx.Client, web: httpx.Client) -> None:
    assert compose("stop", "assistant", timeout=120).returncode == 0
    try:
        assert anon.get("/healthz").status_code == 200
        assert anon.get("/").status_code == 200  # la web carga igual
        assert web.get("/api/meetings").status_code == 200  # y el transcriber sigue en pie
        down = web.get("/assistant/v1/meetings/1/status")
        assert down.status_code in (502, 503, 504)  # la UI lo muestra como "Asistente no disponible"
    finally:
        assert compose("start", "assistant", timeout=120).returncode == 0
        wait_until(lambda: anon.get("/assistant/health").status_code == 200, timeout=90, interval=2, what="que el asistente vuelva")


def test_the_assistant_recovers_and_serves_again(web: httpx.Client) -> None:
    r = web.get("/assistant/v1/meetings/1/status")
    assert r.status_code == 200 and r.json()["following"] is False
