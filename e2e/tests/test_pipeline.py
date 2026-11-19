"""E2E del módulo 1: subida de audio -> cola -> worker -> transcripción -> análisis -> resumen/exportación/búsqueda.

El 'audio' es texto (transcriptor falso) y el LLM es el stub: lo que se valida es el cableado real de web (nginx),
API, Postgres, worker y análisis, no la calidad de Whisper ni de Ollama.
"""

import httpx
from helpers import captured, new_meeting, upload, wait_done, wait_transcribed


def test_services_report_healthy_and_the_llm_is_reachable(web: httpx.Client) -> None:
    system = web.get("/api/system").json()
    assert system["analyzer"] == "ollama" and system["ollama_reachable"] is True
    assert system["ollama_model_installed"] is True and system["queue"] == 0


def test_full_meeting_pipeline(web: httpx.Client, stub: httpx.Client, meetings: list[int]) -> None:
    mid = new_meeting(web, "E2E pipeline")
    meetings.append(mid)
    assert web.get(f"/api/meetings/{mid}").json()["status"] == "recording"

    upload(web, mid, 0, "Buenos días a todos.\nHoy revisamos el presupuesto del proyecto Atlas.", source="system")
    upload(web, mid, 1, "Gracias, empiezo yo.\n?esto se oyó muy mal", source="mic", offset=20)
    assert web.post(f"/api/meetings/{mid}/finish").status_code == 200
    meeting = wait_done(web, mid)

    # Transcripción: orden temporal, quién habla y baja confianza marcada.
    segments = web.get(f"/api/meetings/{mid}/transcript", params={"format": "json"}).json()
    assert [(s["source"], s["text"]) for s in segments] == [
        ("system", "Buenos días a todos."),
        ("system", "Hoy revisamos el presupuesto del proyecto Atlas."),
        ("mic", "Gracias, empiezo yo."),
        ("mic", "esto se oyó muy mal"),
    ]
    assert [s["low_confidence"] for s in segments] == [False, False, False, True]
    assert [s["start"] for s in segments] == [0, 5, 20, 25]

    # Resumen: lo generó el LLM (stub) a partir de la transcripción completa.
    assert meeting["analysis_status"] == "done" and meeting["analysis_error"] is None
    assert meeting["summary"].startswith("RESUMEN-STUB (4 líneas): Buenos días a todos.")
    [summary_call] = captured(stub, "summary")
    assert "presupuesto del proyecto Atlas" in summary_call["body"]["messages"][1]["content"]

    # Exportación en Markdown: resumen + transcripción con quién habla y lo dudoso.
    markdown = web.get(f"/api/meetings/{mid}/transcript").text
    assert markdown.startswith("# E2E pipeline") and "## Resumen" in markdown and "RESUMEN-STUB" in markdown
    assert "**Otros:** Hoy revisamos el presupuesto" in markdown and "**Yo:** Gracias, empiezo yo." in markdown
    assert "esto se oyó muy mal `[?]`" in markdown

    # Búsqueda en todas las reuniones.
    hits = web.get("/api/search", params={"q": "presupuesto"}).json()
    assert any(h["meeting_id"] == mid and "Atlas" in h["text"] for h in hits)

    progress = web.get(f"/api/meetings/{mid}/progress").json()
    assert progress["chunks_total"] == 2 and progress["chunks_done"] == 2 and progress["chunks_failed"] == 0
    assert progress["segments"] == 4


def test_segments_endpoint_is_incremental(web: httpx.Client, meetings: list[int]) -> None:
    mid = new_meeting(web, "E2E incremental")
    meetings.append(mid)
    upload(web, mid, 0, "uno\ndos", source="system")
    first = wait_transcribed(web, mid, 2)
    assert [s["text"] for s in first] == ["uno", "dos"]
    upload(web, mid, 1, "tres", source="mic", offset=10)
    new = wait_transcribed(web, mid, 3)
    after = web.get(f"/api/meetings/{mid}/segments", params={"after_id": first[-1]["id"]}).json()
    assert [s["text"] for s in after] == ["tres"] and len(new) == 3
    assert web.get(f"/api/meetings/{mid}/segments", params={"after_id": after[-1]["id"]}).json() == []


def test_reanalysis_regenerates_the_summary(web: httpx.Client, meetings: list[int]) -> None:
    mid = new_meeting(web, "E2E reanálisis")
    meetings.append(mid)
    upload(web, mid, 0, "Primera frase.\nSegunda frase.", source="system")
    web.post(f"/api/meetings/{mid}/finish")
    wait_done(web, mid)
    assert web.post(f"/api/meetings/{mid}/analyze").status_code == 202
    meeting = wait_done(web, mid)
    assert meeting["summary"].startswith("RESUMEN-STUB (2 líneas): Primera frase.")


def test_a_meeting_can_be_deleted_with_all_its_data(web: httpx.Client) -> None:
    mid = new_meeting(web, "E2E borrar")
    upload(web, mid, 0, "texto para borrar", source="system")
    web.post(f"/api/meetings/{mid}/finish")
    wait_done(web, mid)
    assert web.delete(f"/api/meetings/{mid}").status_code == 204
    assert web.get(f"/api/meetings/{mid}").status_code == 404
    assert not any(h["meeting_id"] == mid for h in web.get("/api/search", params={"q": "borrar"}).json())


def test_unknown_meeting_and_bad_uploads_are_rejected(web: httpx.Client) -> None:
    assert web.get("/api/meetings/999999").status_code == 404
    mid = new_meeting(web, "E2E validaciones")
    try:
        files = {"file": ("c.txt", b"x", "text/plain")}
        bad_source = web.post(f"/api/meetings/{mid}/chunks", files=files, data={"seq": "0", "source": "webcam"})
        assert bad_source.status_code == 422
        web.post(f"/api/meetings/{mid}/finish")
        late = web.post(f"/api/meetings/{mid}/chunks", files=files, data={"seq": "1", "source": "mic"})
        assert late.status_code == 409  # la reunión ya no admite audio
    finally:
        web.delete(f"/api/meetings/{mid}")
