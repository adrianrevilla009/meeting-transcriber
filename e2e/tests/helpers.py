"""Utilidades de los E2E: URLs, clientes HTTP y esperas. Todo contra el stack real en Docker."""

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

WEB = os.environ.get("E2E_WEB", "http://127.0.0.1:3000")  # nginx: /api/ -> transcriber, /assistant/ -> asistente
SHIELD = os.environ.get("E2E_SHIELD", "http://127.0.0.1:8100")
STUB = os.environ.get("E2E_STUB", "http://127.0.0.1:11435")  # LLM falso: registra lo que recibe
MT_TOKEN = os.environ.get("MT_API_TOKEN", "e2e-mt-token-0123456789abcdef")
ANON_TOKEN = os.environ.get("ANON_API_TOKEN", "e2e-anon-token-0123456789abcdef")
COMPOSE = os.environ.get("E2E_COMPOSE", "")
PROJECT = "__e2e__"
ROOT = Path(__file__).resolve().parents[2]  # raíz del repo: los -f de COMPOSE son relativos a ella

T = TypeVar("T")


def wait_until(check: Callable[[], T | None], timeout: float = 60.0, interval: float = 0.4, what: str = "") -> T:
    """Repite `check` hasta que devuelva algo verdadero; si no, falla con `what`."""
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (httpx.HTTPError, AssertionError, KeyError) as exc:
            last = exc
        time.sleep(interval)
    raise AssertionError(f"Tiempo agotado esperando: {what}" + (f" (último error: {last})" if last else ""))


def bearer(token: str = MT_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def new_meeting(web: httpx.Client, title: str = "e2e", project: str = PROJECT) -> int:
    r = web.post("/api/meetings", json={"title": title, "project": project})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def upload(web: httpx.Client, meeting_id: int, seq: int, text: str, *, source: str = "system", offset: float = 0.0) -> None:
    """Sube un 'audio' de texto: el transcriptor falso devuelve una frase por línea ('?' al inicio = baja confianza)."""
    r = web.post(
        f"/api/meetings/{meeting_id}/chunks",
        files={"file": ("chunk.txt", text.encode("utf-8"), "text/plain")},
        data={"seq": str(seq), "offset_seconds": str(offset), "source": source},
    )
    assert r.status_code == 202, r.text


def wait_transcribed(web: httpx.Client, meeting_id: int, segments: int, timeout: float = 60.0) -> list[dict[str, Any]]:
    def check() -> list[dict[str, Any]] | None:
        found: list[dict[str, Any]] = web.get(f"/api/meetings/{meeting_id}/segments").json()
        return found if len(found) >= segments else None

    return wait_until(check, timeout, what=f"{segments} segmentos de la reunión {meeting_id}")


def wait_done(web: httpx.Client, meeting_id: int, timeout: float = 90.0) -> dict[str, Any]:
    """Espera a que la reunión esté procesada del todo (transcrita y con el análisis terminado)."""

    def check() -> dict[str, Any] | None:
        meeting: dict[str, Any] = web.get(f"/api/meetings/{meeting_id}").json()
        return meeting if meeting["status"] == "done" and meeting["analysis_status"] != "pending" else None

    return wait_until(check, timeout, what=f"reunión {meeting_id} procesada")


def events(web: httpx.Client, meeting_id: int, after: int = 0) -> list[dict[str, Any]]:
    """Histórico de eventos del asistente (SSE con once=true)."""
    r = web.get(f"/assistant/v1/meetings/{meeting_id}/events", params={"after": after, "once": "true"})
    assert r.status_code == 200, r.text
    frames = [f for f in r.text.split("\n\n") if f.startswith("data: ")]
    return [json.loads(f[6:]) for f in frames]


def wait_event(web: httpx.Client, meeting_id: int, event_type: str, *, count: int = 1, timeout: float = 60.0) -> list[dict[str, Any]]:
    def check() -> list[dict[str, Any]] | None:
        found = events(web, meeting_id)
        return found if sum(e["type"] == event_type for e in found) >= count else None

    try:
        return wait_until(check, timeout, what=f"evento '{event_type}' x{count} en la reunión {meeting_id}")
    except AssertionError as exc:
        raise AssertionError(f"{exc}. Eventos recibidos: {events(web, meeting_id)}") from None


def captured(stub: httpx.Client, kind: str | None = None) -> list[dict[str, Any]]:
    """Lo que ha recibido el LLM falso. kind: chat (lo que sale por privacy-shield), classifier, summary."""
    r = stub.get("/_captured", params={"kind": kind} if kind else {})
    return list(r.json())


def compose(*args: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    """Ejecuta `docker compose ...` con los mismos ficheros con los que se levantó el stack."""
    assert COMPOSE, "Define E2E_COMPOSE (en CI lo hace el workflow)"
    cmd = [*shlex.split(COMPOSE), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, cwd=ROOT)  # noqa: S603
