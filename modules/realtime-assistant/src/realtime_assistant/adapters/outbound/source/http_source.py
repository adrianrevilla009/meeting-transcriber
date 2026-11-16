"""Lee la transcripción del módulo 1 por HTTP: GET /meetings/{id}/segments?after_id=N (sondeo incremental)."""

import httpx

from realtime_assistant.adapters.outbound.http_egress import EgressBlocked, make_client
from realtime_assistant.domain.entities import TranscriptSegment
from realtime_assistant.domain.errors import MeetingNotFound, TranscriberUnavailable


class HttpTranscriptSource:
    def __init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None, timeout: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = make_client(self._base_url, client, timeout)

    async def fetch_after(self, meeting_id: int, after_id: int) -> list[TranscriptSegment]:
        url = f"{self._base_url}/meetings/{meeting_id}/segments"
        try:
            response = await self._client.get(
                url, params={"after_id": after_id, "limit": 200}, headers={"Authorization": f"Bearer {self._token}"}
            )
        except (httpx.HTTPError, EgressBlocked) as exc:
            raise TranscriberUnavailable(f"No se alcanza el transcriber ({type(exc).__name__})") from exc
        if response.status_code == 404:
            raise MeetingNotFound(str(meeting_id))
        if response.status_code in (401, 403):
            raise TranscriberUnavailable("El transcriber rechazó el token del asistente")
        if response.status_code >= 400:
            raise TranscriberUnavailable(f"El transcriber respondió HTTP {response.status_code}")
        try:
            return [
                TranscriptSegment(int(s["id"]), str(s["source"]), float(s["start"]), float(s["end"]), str(s["text"]))
                for s in response.json()
            ]
        except (KeyError, ValueError, TypeError) as exc:
            raise TranscriberUnavailable("Respuesta del transcriber con formato inesperado") from exc
