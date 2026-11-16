"""Genera respuestas llamando a privacy-shield (/v1/chat con streaming). Es la ÚNICA vía hacia un LLM externo."""

import json
from collections.abc import AsyncIterator

import httpx

from realtime_assistant.adapters.outbound.http_egress import EgressBlocked, make_client
from realtime_assistant.domain.errors import ShieldBlocked, ShieldUnavailable

SYSTEM_PROMPT = """Eres un asistente discreto que ayuda al usuario durante una reunión en directo.
Recibirás las últimas líneas de la conversación ("Yo" es el usuario, "Otros" son los demás) y una pregunta que
alguien ha hecho. Responde en español, en 2 a 4 frases, con lo que el usuario podría decir ahora mismo.
Reglas: usa solo lo que consta en la conversación o conocimiento general fiable; si no hay base suficiente, dilo
y sugiere qué preguntar o comprobar. Los textos entre corchetes como [PERSONA_1] son datos protegidos: úsalos tal
cual, sin inventarlos ni cambiarlos."""


class ShieldAnswerGenerator:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        provider: str = "",
        model: str = "",
        profile: str = "",
        client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._provider = provider
        self._model = model
        self._profile = profile.strip()
        self._client = make_client(self._base_url, client, timeout)

    def _body(self, meeting_id: int, question: str, context: str) -> dict[str, object]:
        system = SYSTEM_PROMPT + (f"\nContexto sobre el usuario: {self._profile}" if self._profile else "")
        body: dict[str, object] = {
            # Misma sesión para toda la reunión: el mismo dato lleva el mismo token en todas las consultas.
            "session_id": f"rta-{meeting_id}",
            "stream": True,
            "temperature": 0.3,
            "max_tokens": 400,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Conversación reciente:\n{context}\n\nPregunta a responder: {question}"},
            ],
        }
        if self._provider:
            body["provider"] = self._provider
        if self._model:
            body["model"] = self._model
        return body

    async def stream_answer(self, meeting_id: int, question: str, context: str) -> AsyncIterator[str]:
        body = self._body(meeting_id, question, context)
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with self._client.stream("POST", f"{self._base_url}/v1/chat", json=body, headers=headers) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise _error_for(response)
                event = ""
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if event == "error":
                        raise ShieldUnavailable("provider_error")
                    event = ""
                    if payload == "[DONE]":
                        return
                    content = _content(payload)
                    if content:
                        yield content
        except (httpx.HTTPError, EgressBlocked) as exc:
            raise ShieldUnavailable("shield_unavailable") from exc


def _content(payload: str) -> str:
    try:
        return str(json.loads(payload).get("content") or "")
    except (ValueError, AttributeError) as exc:
        raise ShieldUnavailable("bad_response") from exc


def _error_for(response: httpx.Response) -> ShieldBlocked | ShieldUnavailable:
    """Traduce el error de privacy-shield a un código (nunca se reenvía su cuerpo: podría contener datos)."""
    try:
        code = str(response.json().get("error", ""))
    except (ValueError, AttributeError):
        code = ""
    if response.status_code in (403, 422):
        return ShieldBlocked(code or f"http_{response.status_code}")
    if response.status_code in (401, 503) and not code:
        code = "shield_unauthorized" if response.status_code == 401 else "shield_unavailable"
    return ShieldUnavailable(code or f"http_{response.status_code}")
