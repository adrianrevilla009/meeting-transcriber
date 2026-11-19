"""E2E del módulo 3: transcripción real (módulo 1) -> asistente -> privacy-shield -> LLM, todo a través de nginx."""

import time

import httpx
from helpers import captured, events, new_meeting, upload, wait_event, wait_until

QUESTION = "¿Puedes enviar el contrato a Marta García (marta@empresa.es) esta semana?"
FORBIDDEN = ["Marta", "García", "marta@empresa.es"]


def follow(web: httpx.Client, meeting_id: int) -> None:
    r = web.post(f"/assistant/v1/meetings/{meeting_id}/follow")
    assert r.status_code == 200 and r.json() == {"meeting_id": meeting_id, "following": True}


def types(web: httpx.Client, meeting_id: int) -> list[str]:
    return [e["type"] for e in events(web, meeting_id)]


def test_a_question_in_the_meeting_is_detected_and_answered_privately(
    web: httpx.Client, stub: httpx.Client, meetings: list[int]
) -> None:
    mid = new_meeting(web, "E2E asistente")
    meetings.append(mid)
    follow(web, mid)
    upload(web, mid, 0, f"Buenos días a todos.\n{QUESTION}", source="system")

    evs = wait_event(web, mid, "answer_done")
    kinds = [e["type"] for e in evs]
    assert kinds[:2] == ["status", "question"] and kinds[-1] == "answer_done"
    assert "answer_start" in kinds and "answer_chunk" in kinds

    # La pregunta se muestra tal cual (es local); la respuesta llega con los datos reales ya restaurados.
    question = evs[1]
    assert question["text"] == QUESTION and question["origin"] == "detected" and question["score"] >= 0.55
    answer = evs[-1]["content"]
    assert answer.startswith("ECO-STUB:") and "Marta García" in answer and "marta@empresa.es" in answer
    assert "".join(e["content"] for e in evs if e["type"] == "answer_chunk") == answer

    # Lo que SALIÓ hacia el LLM (vía privacy-shield) no lleva datos personales, solo tokens.
    sent = captured(stub, "chat")
    assert len(sent) == 1
    dump = str(sent[0]["body"])
    for secret in FORBIDDEN:
        assert secret not in dump, f"Se filtró {secret!r} hacia el LLM"
    assert "[PERSONA_1]" in dump and "[EMAIL_1]" in dump
    assert "Conversación reciente" in dump  # viaja también el contexto de la conversación, ya sin datos personales

    # El clasificador local (que no sale de la máquina) sí vio la pregunta real.
    assert any(QUESTION in str(c["body"]) for c in captured(stub, "classifier"))

    status = web.get(f"/assistant/v1/meetings/{mid}/status").json()
    assert status == {"following": True, "questions": 1, "answers": 1}


def test_only_questions_from_others_directed_at_the_user_are_answered(web: httpx.Client, stub: httpx.Client, meetings: list[int]) -> None:
    mid = new_meeting(web, "E2E filtros")
    meetings.append(mid)
    follow(web, mid)
    upload(web, mid, 0, "¿Tú qué opinas del plazo de entrega?", source="mic")  # lo dice el usuario: se ignora
    upload(web, mid, 1, "¿Marta, puedes revisar esto NO-PARA-MI por favor?", source="system", offset=20)  # no va con él
    wait_until(lambda: len(captured(stub, "classifier")) >= 1, 30, what="que el clasificador vea la pregunta de otros")
    time.sleep(2.5)  # margen para que un falso positivo llegara a emitirse
    assert [t for t in types(web, mid) if t != "status"] == []
    assert captured(stub, "chat") == []


def test_manual_questions_are_answered_through_the_shield(web: httpx.Client, stub: httpx.Client, meetings: list[int]) -> None:
    mid = new_meeting(web, "E2E manual")
    meetings.append(mid)
    r = web.post(f"/assistant/v1/meetings/{mid}/ask", json={"text": "¿Qué le digo a Luis Pérez (luis@empresa.es)?"})
    assert r.status_code == 202 and r.json() == {"question_id": "q1"}
    evs = wait_event(web, mid, "answer_done")
    assert evs[0]["origin"] == "manual"
    assert "luis@empresa.es" in evs[-1]["content"]
    dump = str(captured(stub, "chat"))
    assert "luis@empresa.es" not in dump and "Luis Pérez" not in dump


def test_blocked_data_never_leaves_and_the_ui_gets_a_code(web: httpx.Client, stub: httpx.Client, meetings: list[int]) -> None:
    mid = new_meeting(web, "E2E bloqueo")
    meetings.append(mid)
    follow(web, mid)
    upload(web, mid, 0, "¿Puedes cobrar con la tarjeta 4111 1111 1111 1111 hoy mismo?", source="system")
    evs = wait_event(web, mid, "error")
    error = next(e for e in evs if e["type"] == "error")
    assert error == {"id": error["id"], "type": "error", "question_id": "q1", "error": "policy_blocked"}
    assert not any(e["type"] in ("answer_chunk", "answer_done") for e in evs)
    assert captured(stub, "chat") == []  # nada salió hacia el LLM


def test_detected_questions_can_also_be_answered_on_demand(
    web: httpx.Client, meetings: list[int]
) -> None:
    mid = new_meeting(web, "E2E enfriamiento")
    meetings.append(mid)
    follow(web, mid)
    upload(web, mid, 0, "¿Cuándo podemos tener el informe final?", source="system")
    wait_event(web, mid, "answer_done")
    upload(web, mid, 1, "¿Quién se encarga de la presentación del jueves?", source="system", offset=40)
    wait_event(web, mid, "question", count=2)
    r = web.post(f"/assistant/v1/meetings/{mid}/questions/q2/answer")  # por si el enfriamiento no la contestó
    assert r.status_code == 202
    wait_event(web, mid, "answer_done", count=2)
    assert web.post(f"/assistant/v1/meetings/{mid}/questions/q99/answer").status_code == 404


def test_unfollow_stops_listening(web: httpx.Client, meetings: list[int]) -> None:
    mid = new_meeting(web, "E2E dejar de seguir")
    meetings.append(mid)
    follow(web, mid)
    assert web.get(f"/assistant/v1/meetings/{mid}/status").json()["following"] is True
    assert web.delete(f"/assistant/v1/meetings/{mid}/follow").status_code == 204
    assert web.get(f"/assistant/v1/meetings/{mid}/status").json()["following"] is False
    assert [e["state"] for e in events(web, mid) if e["type"] == "status"] == ["following", "stopped"]
    upload(web, mid, 0, QUESTION, source="system")
    time.sleep(2.5)
    assert "question" not in types(web, mid)  # ya no escucha


def test_unknown_meeting_is_reported(web: httpx.Client) -> None:
    r = web.post("/assistant/v1/meetings/999999/follow")
    assert r.status_code == 404 and r.json() == {"error": "meeting_not_found"}
