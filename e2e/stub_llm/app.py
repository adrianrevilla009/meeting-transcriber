"""LLM falso con la API de Ollama para los E2E: determinista y con registro de TODO lo que recibe.

Sirve a tres clientes a la vez (se distinguen por el prompt de sistema):
- "summary":    el resumen de reuniones del transcriber        -> "RESUMEN-STUB (N líneas): <primera línea>"
- "classifier": el clasificador de preguntas del asistente      -> JSON con el veredicto
- "chat":       privacy-shield (proveedor ollama)               -> "ECO-STUB: <último mensaje>"

`GET /_captured?kind=chat` devuelve lo que "salió" hacia el LLM: así los tests comprueban que no hay datos personales.
"""

import json
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="stub-llm")
CAPTURED: list[dict[str, Any]] = []


def kind_of(messages: list[dict[str, str]]) -> str:
    system = messages[0]["content"] if messages else ""
    if system.startswith("Decides si la FRASE"):
        return "classifier"
    if system.startswith(("Eres un asistente que resume reuniones", "Recibirás las notas de resumen")):
        return "summary"
    return "chat"


def reply(kind: str, user: str) -> str:
    if kind == "classifier":
        phrase = user.split("FRASE:", 1)[-1].strip()
        return json.dumps({"is_question": "?" in phrase, "directed_at_me": "NO-PARA-MI" not in phrase})
    if kind == "summary":
        lines = [line for line in user.splitlines() if line.strip()][1:]  # sin la cabecera "Transcripción:"
        return f"RESUMEN-STUB ({len(lines)} líneas): {lines[0] if lines else ''}"
    return "ECO-STUB: " + user


def ndjson(content: str) -> Iterator[str]:
    for i in range(0, len(content), 12):
        yield json.dumps({"message": {"role": "assistant", "content": content[i : i + 12]}, "done": False}) + "\n"
    yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"}) + "\n"


@app.post("/api/chat")
async def chat(request: Request) -> Any:
    body = await request.json()
    messages = body.get("messages", [])
    kind = kind_of(messages)
    CAPTURED.append({"kind": kind, "body": body})
    content = reply(kind, messages[-1]["content"] if messages else "")
    if body.get("stream"):
        return StreamingResponse(ndjson(content), media_type="application/x-ndjson")
    return {
        "model": body.get("model", "stub"),
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
    }


@app.get("/api/tags")
def tags() -> dict[str, Any]:
    return {"models": [{"name": "qwen2.5:7b"}, {"name": "qwen2.5:3b"}]}


@app.get("/_captured")
def captured(kind: str | None = None) -> list[dict[str, Any]]:
    return [c for c in CAPTURED if kind is None or c["kind"] == kind]


@app.delete("/_captured", status_code=204)
def clear() -> None:
    CAPTURED.clear()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
