"""Confirma con un LLM local pequeño que un candidato es una pregunta que merece respuesta. No sale de la máquina."""

import json
from typing import Any

import httpx

from realtime_assistant.adapters.outbound.http_egress import EgressBlocked, make_client
from realtime_assistant.domain.entities import Verdict
from realtime_assistant.domain.errors import ClassifierUnavailable

SYSTEM_PROMPT = """Decides si la FRASE es una pregunta real, hecha por otra persona durante una reunión, que el usuario
o el grupo deberían contestar. No lo es si es retórica, una muletilla ("¿verdad?", "¿vale?"), una pregunta que se
contesta ella misma o algo dirigido a otra persona concreta. Responde SOLO con JSON:
{"is_question": true|false, "directed_at_me": true|false}
"directed_at_me" es true si la pregunta va al usuario o a todo el grupo (incluido él)."""


class OllamaQuestionClassifier:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        user_names: tuple[str, ...] = (),
        client: httpx.AsyncClient | None = None,
        timeout: float = 8.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._names = ", ".join(n for n in user_names if n.strip())
        self._client = make_client(self._base_url, client, timeout)

    async def classify(self, question: str, context: str) -> Verdict:
        names = f"Nombres del usuario: {self._names}\n" if self._names else ""
        user = f"{names}Conversación reciente:\n{context}\n\nFRASE: {question}"
        body: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        }
        try:
            response = await self._client.post(f"{self._base_url}/api/chat", json=body)
        except (httpx.HTTPError, EgressBlocked) as exc:
            raise ClassifierUnavailable(f"Ollama no responde ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            raise ClassifierUnavailable(f"Ollama respondió HTTP {response.status_code}")
        try:
            data = json.loads(response.json()["message"]["content"])
            return Verdict(bool(data["is_question"]), bool(data.get("directed_at_me", True)))
        except (KeyError, ValueError, TypeError) as exc:
            raise ClassifierUnavailable("Respuesta del clasificador con formato inesperado") from exc
