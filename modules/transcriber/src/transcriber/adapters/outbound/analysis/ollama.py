"""Adaptador de LLM local: Ollama (/api/chat). Para otro proveedor, otro adaptador que implemente AnalyzerPort."""

import httpx

from transcriber.application.ports import LlmStatus
from transcriber.application.prompts import MERGE_PROMPT, SYSTEM_PROMPT, with_glossary
from transcriber.config import get_settings


class OllamaAnalyzer:
    def __init__(self):
        self.s = get_settings()

    def _chat(self, system: str, user: str) -> str:
        resp = httpx.post(
            f"{self.s.ollama_url}/api/chat",
            json={
                "model": self.s.ollama_model,
                "stream": False,
                "options": {"temperature": 0, "num_ctx": self.s.ollama_num_ctx},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=self.s.ollama_timeout,
        )
        resp.raise_for_status()
        return str(resp.json()["message"]["content"]).strip()

    def summarize(self, transcript_window: str) -> str:
        return self._chat(with_glossary(SYSTEM_PROMPT), f"Transcripción:\n\n{transcript_window}")

    def merge(self, partial_summaries: list[str]) -> str:
        parts = "\n\n".join(f"--- Parte {i} ---\n{p}" for i, p in enumerate(partial_summaries, 1))
        return self._chat(with_glossary(MERGE_PROMPT), parts)


def ollama_status() -> LlmStatus:
    """¿Responde Ollama y está instalado el modelo configurado? (para el panel de estado)."""
    s = get_settings()
    try:
        r = httpx.get(f"{s.ollama_url}/api/tags", timeout=3)
        r.raise_for_status()
        names = {m["name"] for m in r.json().get("models", [])}
    except (httpx.HTTPError, ValueError, KeyError):
        return LlmStatus(reachable=False, model_installed=False)
    return LlmStatus(reachable=True, model_installed=s.ollama_model in names or f"{s.ollama_model}:latest" in names)
