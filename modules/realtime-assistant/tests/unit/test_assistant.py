"""Caso de uso principal con piezas falsas: seguir la reunión, detectar preguntas y responderlas."""

import asyncio

import pytest

from realtime_assistant.application.runtime import Runtime
from realtime_assistant.domain.entities import Verdict
from realtime_assistant.domain.errors import (
    ClassifierUnavailable,
    MeetingNotFound,
    QuestionNotFound,
    ShieldBlocked,
    ShieldUnavailable,
    TranscriberUnavailable,
)
from tests.helpers import FakeClassifier, FakeGenerator, make_runtime, seg

QUESTION = "¿Cuándo podemos tener el informe?"
OTHER = "¿Quién se encarga de la presentación?"


def types(rt: Runtime, meeting_id: int = 1) -> list[str]:
    return [e.type for e in rt.store.after(meeting_id, 0)]


async def test_detects_a_question_and_answers_it() -> None:
    rt, source, _, _ = make_runtime(classifier=FakeClassifier())
    source.add(seg(1, "Buenos días a todos."), seg(2, QUESTION))
    assert await rt.assistant.step(1) == 2
    await rt.assistant.wait_idle(1)

    events = rt.store.after(1, 0)
    assert [e.type for e in events] == ["question", "answer_start", "answer_chunk", "answer_chunk", "answer_done"]
    assert events[0].data == {"question_id": "q1", "text": QUESTION, "ts": 5.0, "origin": "detected", "score": 0.85}
    assert events[-1].data == {"question_id": "q1", "content": "Respuesta corta."}
    assert [e.id for e in events] == [1, 2, 3, 4, 5]


async def test_the_answer_gets_the_recent_conversation_with_speakers() -> None:
    rt, source, generator, _ = make_runtime()
    source.add(seg(1, "Yo reviso el presupuesto.", source="mic"), seg(2, "Buenos días.", start=30.0), seg(3, QUESTION, start=34.5))
    await rt.assistant.step(1)
    await rt.assistant.wait_idle(1)
    [(meeting_id, question, context)] = generator.calls
    assert (meeting_id, question) == (1, QUESTION)
    assert context == f"Yo: Yo reviso el presupuesto.\nOtros: Buenos días.\nOtros: {QUESTION}"


async def test_classifier_can_reject_a_candidate() -> None:
    rt, source, generator, _ = make_runtime(classifier=FakeClassifier(Verdict(False)))
    source.add(seg(1, QUESTION))
    await rt.assistant.step(1)
    assert types(rt) == [] and generator.calls == []


async def test_questions_not_directed_at_the_user_are_ignored() -> None:
    rt, source, _, _ = make_runtime(classifier=FakeClassifier(Verdict(True, directed_at_me=False)))
    source.add(seg(1, QUESTION))
    await rt.assistant.step(1)
    assert types(rt) == []


async def test_falls_back_to_the_rules_when_the_local_llm_is_down() -> None:
    rt, source, _, _ = make_runtime(classifier=FakeClassifier(error=ClassifierUnavailable("caído")))
    source.add(seg(1, QUESTION))
    await rt.assistant.step(1)
    await rt.assistant.wait_idle(1)
    assert types(rt)[0] == "question" and types(rt)[-1] == "answer_done"


async def test_the_classifier_sees_the_candidate_and_its_context() -> None:
    classifier = FakeClassifier()
    rt, source, _, _ = make_runtime(classifier=classifier)
    source.add(seg(1, "Empezamos ya.", start=0.0), seg(2, QUESTION, start=4.5))
    await rt.assistant.step(1)
    [(candidate, context)] = classifier.calls
    assert candidate == QUESTION and "Otros: Empezamos ya." in context


async def test_questions_from_the_user_are_not_answered() -> None:
    rt, source, generator, _ = make_runtime()
    source.add(seg(1, QUESTION, source="mic"))
    await rt.assistant.step(1)
    assert types(rt) == [] and generator.calls == []


async def test_the_same_question_is_not_asked_twice() -> None:
    rt, source, generator, _ = make_runtime()
    source.add(seg(1, QUESTION))
    await rt.assistant.step(1)
    source.add(seg(2, "Gracias.", start=60.0))
    await rt.assistant.step(1)
    source.add(seg(3, QUESTION.lower(), start=120.0))  # repetida con otras mayúsculas
    await rt.assistant.step(1)
    await rt.assistant.wait_idle(1)
    assert types(rt).count("question") == 1 and len(generator.calls) == 1


async def test_steps_only_fetch_new_segments() -> None:
    rt, source, _, _ = make_runtime()
    source.add(seg(1, "uno"), seg(2, "dos"))
    assert await rt.assistant.step(1) == 2
    assert await rt.assistant.step(1) == 0
    source.add(seg(3, "tres"))
    assert await rt.assistant.step(1) == 1
    assert source.calls == [(1, 0), (1, 2), (1, 2)]


async def test_automatic_answers_respect_the_cooldown_and_can_be_requested_later() -> None:
    rt, source, generator, clock = make_runtime(answer_cooldown_seconds=15)
    source.add(seg(1, QUESTION, start=0.0))
    await rt.assistant.step(1)
    await rt.assistant.wait_idle(1)
    clock.advance(5)
    source.add(seg(2, OTHER, start=100.0))
    await rt.assistant.step(1)
    await rt.assistant.wait_idle(1)
    assert types(rt)[-1] == "question" and len(generator.calls) == 1  # detectada, pero sin respuesta automática

    await rt.assistant.answer(1, "q2")
    await rt.assistant.wait_idle(1)
    assert types(rt)[-1] == "answer_done" and len(generator.calls) == 2
    assert rt.assistant.status(1) == {"following": False, "questions": 2, "answers": 2}

    clock.advance(30)  # pasado el enfriamiento vuelve a responder solo
    source.add(seg(3, "¿Dónde es la reunión del jueves?", start=200.0))
    await rt.assistant.step(1)
    await rt.assistant.wait_idle(1)
    assert len(generator.calls) == 3


async def test_auto_answer_can_be_turned_off() -> None:
    rt, source, generator, _ = make_runtime(auto_answer=False)
    source.add(seg(1, QUESTION))
    await rt.assistant.step(1)
    assert types(rt) == ["question"] and generator.calls == []
    await rt.assistant.answer(1, "q1")
    await rt.assistant.wait_idle(1)
    assert types(rt)[-1] == "answer_done"


async def test_manual_questions_are_always_answered() -> None:
    rt, _, generator, _ = make_runtime(answer_cooldown_seconds=9999)
    first = await rt.assistant.ask(1, "  ¿Qué opinas del plan?  ")
    second = await rt.assistant.ask(1, "¿Y del presupuesto?")
    await rt.assistant.wait_idle(1)
    assert (first, second) == ("q1", "q2")
    questions = [e for e in rt.store.after(1, 0) if e.type == "question"]
    assert [q.data["origin"] for q in questions] == ["manual", "manual"]
    assert questions[0].data["text"] == "¿Qué opinas del plan?"
    assert len(generator.calls) == 2


async def test_answers_are_generated_one_at_a_time_per_meeting() -> None:
    rt, _, _, _ = make_runtime()
    await rt.assistant.ask(1, "primera pregunta")
    await rt.assistant.ask(1, "segunda pregunta")
    await rt.assistant.wait_idle(1)
    order = [e.type for e in rt.store.after(1, 0) if e.type.startswith("answer")]
    assert order == ["answer_start", "answer_chunk", "answer_chunk", "answer_done"] * 2


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ShieldBlocked("leak_detected"), "leak_detected"),
        (ShieldBlocked("policy_blocked"), "policy_blocked"),
        (ShieldUnavailable("shield_unavailable"), "shield_unavailable"),
        (RuntimeError("raro"), "provider_error"),
    ],
)
async def test_answer_failures_become_error_events_and_can_be_retried(error: Exception, code: str) -> None:
    rt, _, _, _ = make_runtime(generator=FakeGenerator(error=error))
    qid = await rt.assistant.ask(1, "¿Qué opinas del plan?")
    await rt.assistant.wait_idle(1)
    assert types(rt) == ["question", "answer_start", "error"]
    assert rt.store.after(1, 0)[-1].data == {"question_id": qid, "error": code}
    assert rt.assistant.status(1)["answers"] == 0

    await rt.assistant.answer(1, qid)  # reintento
    await rt.assistant.wait_idle(1)
    assert types(rt).count("answer_start") == 2


async def test_answering_an_unknown_question_fails() -> None:
    rt, _, _, _ = make_runtime()
    with pytest.raises(QuestionNotFound):
        await rt.assistant.answer(1, "q99")


# ------------------------------------------------------------------ seguimiento en segundo plano
async def test_follow_checks_the_meeting_and_is_idempotent() -> None:
    rt, source, _, _ = make_runtime()
    source.error = MeetingNotFound("1")
    with pytest.raises(MeetingNotFound):
        await rt.assistant.follow(1)
    source.error = TranscriberUnavailable("caído")
    with pytest.raises(TranscriberUnavailable):
        await rt.assistant.follow(1)
    assert rt.assistant.status(1)["following"] is False

    source.error = None
    await rt.assistant.follow(1)
    await rt.assistant.follow(1)
    assert rt.assistant.status(1)["following"] is True
    assert types(rt) == ["status"]  # un solo "following"
    await rt.assistant.shutdown()


async def test_background_loop_picks_up_new_questions_and_stops_on_unfollow() -> None:
    rt, source, _, _ = make_runtime()
    await rt.assistant.follow(1)
    source.add(seg(1, QUESTION))
    for _ in range(100):
        if "answer_done" in types(rt):
            break
        await asyncio.sleep(0.02)
    assert types(rt)[:2] == ["status", "question"] and "answer_done" in types(rt)

    await rt.assistant.unfollow(1)
    assert rt.assistant.status(1)["following"] is False
    assert [e.data for e in rt.store.after(1, 0) if e.type == "status"] == [{"state": "following"}, {"state": "stopped"}]


async def test_loop_stops_when_the_meeting_disappears() -> None:
    rt, source, _, _ = make_runtime()
    await rt.assistant.follow(1)
    source.error = MeetingNotFound("1")
    for _ in range(100):
        if not rt.assistant.status(1)["following"]:
            break
        await asyncio.sleep(0.02)
    errors = [e.data for e in rt.store.after(1, 0) if e.type == "error"]
    assert errors == [{"error": "meeting_not_found"}] and rt.assistant.status(1)["following"] is False


async def test_transcriber_outage_is_reported_once_and_the_loop_survives() -> None:
    rt, source, _, _ = make_runtime()
    await rt.assistant.follow(1)
    source.error = TranscriberUnavailable("caído")
    await asyncio.sleep(0.15)
    assert [e.data for e in rt.store.after(1, 0) if e.type == "error"] == [{"error": "transcriber_unavailable"}]
    source.error = None
    source.add(seg(1, QUESTION))
    for _ in range(100):
        if "answer_done" in types(rt):
            break
        await asyncio.sleep(0.02)
    assert "answer_done" in types(rt)
    await rt.assistant.shutdown()


async def test_follow_gives_up_after_the_idle_timeout() -> None:
    rt, _, _, clock = make_runtime(idle_timeout_seconds=100)
    await rt.assistant.follow(1)
    clock.advance(500)
    for _ in range(100):
        if not rt.assistant.status(1)["following"]:
            break
        await asyncio.sleep(0.02)
    assert rt.assistant.status(1)["following"] is False


async def test_shutdown_cancels_everything() -> None:
    rt, _, _, _ = make_runtime(generator=FakeGenerator())
    await rt.assistant.follow(1)
    await rt.assistant.ask(1, "una pregunta")
    await rt.assistant.shutdown()
    assert rt.assistant.status(1)["following"] is False
