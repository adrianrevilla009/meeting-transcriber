"""Raíz de composición: el ÚNICO sitio que conoce los adaptadores concretos y los cablea."""

from realtime_assistant.adapters.outbound.answers.shield_client import ShieldAnswerGenerator
from realtime_assistant.adapters.outbound.classifier.ollama import OllamaQuestionClassifier
from realtime_assistant.adapters.outbound.clock import SystemClock
from realtime_assistant.adapters.outbound.events.memory import MemoryEventStore
from realtime_assistant.adapters.outbound.source.http_source import HttpTranscriptSource
from realtime_assistant.application.assistant import AssistantSettings, MeetingAssistant
from realtime_assistant.application.ports import (
    AnswerGeneratorPort,
    ClockPort,
    EventStorePort,
    QuestionClassifierPort,
    TranscriptSourcePort,
)
from realtime_assistant.application.question_rules import RuleQuestionDetector
from realtime_assistant.application.runtime import Runtime
from realtime_assistant.config import Settings


def build_runtime(
    settings: Settings,
    *,
    source: TranscriptSourcePort | None = None,
    classifier: QuestionClassifierPort | None = None,
    rules_only: bool = False,
    generator: AnswerGeneratorPort | None = None,
    store: EventStorePort | None = None,
    clock: ClockPort | None = None,
) -> Runtime:
    """Cablea todo. Los parámetros opcionales permiten inyectar piezas (tests)."""
    clock = clock or SystemClock()
    store = store or MemoryEventStore()
    source = source or HttpTranscriptSource(settings.transcriber_url, settings.api_token)
    generator = generator or ShieldAnswerGenerator(
        settings.shield_url,
        settings.shield_token,
        provider=settings.shield_provider,
        model=settings.shield_model,
        profile=settings.profile,
    )
    if classifier is None and not rules_only and settings.classifier == "ollama":
        classifier = OllamaQuestionClassifier(
            settings.ollama_url, settings.ollama_model, user_names=settings.user_name_list
        )
    detector = RuleQuestionDetector(
        settings.user_name_list, threshold=settings.min_question_score, listen_sources=settings.listen_source_set
    )
    assistant = MeetingAssistant(
        source,
        detector,
        classifier,
        generator,
        store,
        clock,
        AssistantSettings(
            poll_seconds=settings.poll_seconds,
            context_chars=settings.context_chars,
            auto_answer=settings.auto_answer,
            answer_cooldown_seconds=settings.answer_cooldown_seconds,
            idle_timeout_seconds=settings.idle_timeout_seconds,
            own_source=settings.own_source,
        ),
    )

    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "classifier": "ollama" if classifier is not None else "rules",
            "auto_answer": settings.auto_answer,
        }

    return Runtime(assistant=assistant, store=store, health=health)
