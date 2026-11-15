"""Casos de uso: AnonymizeText, DeanonymizeText y ProtectedChat (el principal)."""

import asyncio
import hashlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from privacy_shield.application.deanonymizer import Deanonymizer, StreamingDeanonymizer
from privacy_shield.application.leak_guard import LeakGuard
from privacy_shield.application.ports import (
    AuditPort,
    ClockPort,
    DetectorPort,
    LLMPort,
    ProviderRegistryPort,
    VaultPort,
)
from privacy_shield.application.pseudonymizer import AnonymizedText, Pseudonymizer, Replacement
from privacy_shield.domain.audit import AuditEvent
from privacy_shield.domain.entities import EntityType
from privacy_shield.domain.errors import (
    BlockedByPolicy,
    DetectorUnavailable,
    LeakDetected,
    PrivacyShieldError,
    ProviderError,
    ProviderNotAllowed,
    ProviderNotConfigured,
    SessionNotFound,
)
from privacy_shield.domain.messages import ChatChunk, ChatMessage, ChatRequest, ChatResponse
from privacy_shield.domain.policy import Policy
from privacy_shield.domain.session import SessionId, new_session_id


def session_hash(session: SessionId) -> str:
    return hashlib.sha256(session.encode()).hexdigest()[:12]


def _counts(replacements: Sequence[Replacement]) -> tuple[dict[str, int], dict[str, int]]:
    by_type: dict[str, int] = {}
    by_strategy: dict[str, int] = {}
    for r in replacements:
        by_type[r.type.value] = by_type.get(r.type.value, 0) + 1
        by_strategy[r.strategy.value] = by_strategy.get(r.strategy.value, 0) + 1
    return by_type, by_strategy


class Anonymizer:
    """Detecta y pseudonimiza un texto. Si el detector falla, falla cerrado (DetectorUnavailable)."""

    def __init__(self, detector: DetectorPort, pseudonymizer: Pseudonymizer):
        self._detector = detector
        self._pseudonymizer = pseudonymizer

    def anonymize(self, session: SessionId, text: str, language: str = "es") -> AnonymizedText:
        if not text.strip():
            return AnonymizedText(text, ())
        try:
            entities = self._detector.detect(text, language=language)
        except PrivacyShieldError:
            raise
        except Exception as exc:
            raise DetectorUnavailable(f"El detector falló ({type(exc).__name__})") from exc
        return self._pseudonymizer.apply(session, text, entities)


@dataclass(frozen=True)
class AnonymizeResult:
    session_id: SessionId
    text: str
    replacements: tuple[Replacement, ...]


class AnonymizeText:
    def __init__(self, anonymizer: Anonymizer, vault: VaultPort, audit: AuditPort, clock: ClockPort):
        self._anonymizer = anonymizer
        self._vault = vault
        self._audit = audit
        self._clock = clock

    def execute(self, text: str, session_id: SessionId | None = None, language: str = "es") -> AnonymizeResult:
        session = session_id or new_session_id()
        self._vault.ensure_session(session)
        t0 = self._clock.perf_ms()
        try:
            result = self._anonymizer.anonymize(session, text, language)
        except BlockedByPolicy:
            self._record(session, "policy_blocked", (), t0)
            raise
        except DetectorUnavailable:
            self._record(session, "detector_unavailable", (), t0)
            raise
        self._record(session, "ok", result.replacements, t0)
        return AnonymizeResult(session, result.text, result.replacements)

    def _record(self, session: SessionId, outcome: str, reps: Sequence[Replacement], t0: float) -> None:
        by_type, by_strategy = _counts(reps)
        elapsed = self._clock.perf_ms() - t0
        self._audit.record(
            AuditEvent(
                timestamp=self._clock.now(),
                operation="anonymize",
                session_hash=session_hash(session),
                entity_counts=by_type,
                strategy_counts=by_strategy,
                outcome=outcome,
                detect_ms=elapsed,
                total_ms=elapsed,
            )
        )


class DeanonymizeText:
    def __init__(self, deanonymizer: Deanonymizer, vault: VaultPort, audit: AuditPort, clock: ClockPort):
        self._deanonymizer = deanonymizer
        self._vault = vault
        self._audit = audit
        self._clock = clock

    def execute(self, session_id: SessionId, text: str) -> str:
        if not self._vault.session_exists(session_id):
            raise SessionNotFound("Sesión desconocida o caducada")
        result = self._deanonymizer.deanonymize(session_id, text)
        self._audit.record(
            AuditEvent(
                timestamp=self._clock.now(),
                operation="deanonymize",
                session_hash=session_hash(session_id),
                unknown_tokens=result.unknown_tokens,
            )
        )
        return result.text


@dataclass(frozen=True)
class ChatSettings:
    default_provider: str
    skip_local: bool = True  # los proveedores locales (que no salen de la máquina) no necesitan pseudonimizar


@dataclass(frozen=True)
class PreparedChat:
    """Petición ya anonimizada y comprobada por el leak guard, lista para salir."""

    session_id: SessionId
    provider: LLMPort
    request: ChatRequest
    replacements: tuple[Replacement, ...]
    skipped_local: bool
    detect_ms: float
    started_ms: float


@dataclass(frozen=True)
class ChatResult:
    session_id: SessionId
    provider: str
    response: ChatResponse
    replacements: tuple[Replacement, ...]
    unknown_tokens: int


class ProtectedChat:
    """mensajes -> detectar -> pseudonimizar -> LEAK GUARD -> proveedor -> des-pseudonimizar."""

    def __init__(
        self,
        anonymizer: Anonymizer,
        deanonymizer: Deanonymizer,
        guard: LeakGuard,
        vault: VaultPort,
        registry: ProviderRegistryPort,
        audit: AuditPort,
        clock: ClockPort,
        policy: Policy,
        settings: ChatSettings,
    ):
        self._anonymizer = anonymizer
        self._deanonymizer = deanonymizer
        self._guard = guard
        self._vault = vault
        self._registry = registry
        self._audit = audit
        self._clock = clock
        self._policy = policy
        self._settings = settings

    # ------------------------------------------------------------------ preparación
    async def prepare(
        self, request: ChatRequest, session_id: SessionId | None = None, provider: str | None = None
    ) -> PreparedChat:
        started = self._clock.perf_ms()
        session = session_id or new_session_id()
        llm = self._registry.get(provider or self._settings.default_provider)
        if not llm.is_configured():
            raise ProviderNotConfigured(f"El proveedor '{llm.name}' no está configurado")
        if self._policy.local_only and llm.leaves_machine:
            raise ProviderNotAllowed(f"La política local_only no admite el proveedor '{llm.name}'")
        if not llm.leaves_machine and self._settings.skip_local:
            return PreparedChat(session, llm, request, (), True, 0.0, started)

        self._vault.ensure_session(session)
        try:
            anonymized, replacements, detect_ms = await asyncio.to_thread(self._protect, session, request)
        except LeakDetected as exc:
            self._audit_failure(session, llm, request, "leak_blocked", started, leak=True, counts=exc.counts)
            raise
        except BlockedByPolicy:
            self._audit_failure(session, llm, request, "policy_blocked", started)
            raise
        except DetectorUnavailable:
            self._audit_failure(session, llm, request, "detector_unavailable", started)
            raise
        return PreparedChat(session, llm, anonymized, replacements, False, detect_ms, started)

    def _protect(self, session: SessionId, request: ChatRequest) -> tuple[ChatRequest, tuple[Replacement, ...], float]:
        t0 = self._clock.perf_ms()
        replacements: list[Replacement] = []
        messages: list[ChatMessage] = []
        for m in request.messages:
            content = self._anonymizer.anonymize(session, m.content)
            replacements.extend(content.replacements)
            name = m.name
            if name:
                anon_name = self._anonymizer.anonymize(session, name)
                replacements.extend(anon_name.replacements)
                name = anon_name.text
            messages.append(ChatMessage(m.role, content.text, name))
        metadata: dict[str, str] = {}
        for key, value in request.metadata.items():
            anon_value = self._anonymizer.anonymize(session, value)
            replacements.extend(anon_value.replacements)
            metadata[key] = anon_value.text
        outgoing = ChatRequest(tuple(messages), request.model, request.temperature, request.max_tokens, metadata)
        detect_ms = self._clock.perf_ms() - t0
        # Segunda barrera sobre TODO lo que sale (contenidos, nombres, modelo y metadatos).
        payload = [m.content for m in messages] + [m.name or "" for m in messages]
        payload += [request.model or "", *metadata.keys(), *metadata.values()]
        self._guard.check(session, payload)
        return outgoing, tuple(replacements), detect_ms

    # ------------------------------------------------------------------ ejecución
    async def complete(self, prepared: PreparedChat) -> ChatResult:
        t0 = self._clock.perf_ms()
        try:
            response = await prepared.provider.complete(prepared.request)
        except PrivacyShieldError:
            self._audit_chat(prepared, "provider_error", 0, t0)
            raise
        except Exception as exc:
            self._audit_chat(prepared, "provider_error", 0, t0)
            raise ProviderError(f"El proveedor falló ({type(exc).__name__})") from exc
        unknown = 0
        if not prepared.skipped_local:
            result = self._deanonymizer.deanonymize(prepared.session_id, response.content)
            response = ChatResponse(result.text, response.model, response.finish_reason)
            unknown = result.unknown_tokens
        self._audit_chat(prepared, "ok", unknown, t0)
        return ChatResult(prepared.session_id, prepared.provider.name, response, prepared.replacements, unknown)

    async def stream(self, prepared: PreparedChat) -> AsyncIterator[ChatChunk]:
        t0 = self._clock.perf_ms()
        deano = None if prepared.skipped_local else StreamingDeanonymizer(self._deanonymizer, prepared.session_id)
        outcome = "ok"
        finish: str | None = None
        try:
            async for chunk in prepared.provider.stream(prepared.request):
                if chunk.finish_reason:
                    finish = chunk.finish_reason
                text = deano.feed(chunk.content) if deano else chunk.content
                if text:
                    yield ChatChunk(text)
            tail = deano.flush() if deano else ""
            if tail or finish:
                yield ChatChunk(tail, finish)
        except PrivacyShieldError:
            outcome = "provider_error"
            raise
        except Exception as exc:
            outcome = "provider_error"
            raise ProviderError(f"El proveedor falló ({type(exc).__name__})") from exc
        finally:
            self._audit_chat(prepared, outcome, deano.unknown_tokens if deano else 0, t0, operation="chat_stream")

    # ------------------------------------------------------------------ auditoría
    def _audit_chat(
        self, p: PreparedChat, outcome: str, unknown: int, provider_t0: float, operation: str = "chat"
    ) -> None:
        by_type, by_strategy = _counts(p.replacements)
        now_ms = self._clock.perf_ms()
        self._audit.record(
            AuditEvent(
                timestamp=self._clock.now(),
                operation=operation,
                session_hash=session_hash(p.session_id),
                provider=p.provider.name,
                model=p.request.model or "",
                entity_counts=by_type,
                strategy_counts=by_strategy,
                outcome=outcome,
                unknown_tokens=unknown,
                skipped_local=p.skipped_local,
                detect_ms=p.detect_ms,
                provider_ms=now_ms - provider_t0,
                total_ms=now_ms - p.started_ms,
            )
        )

    def _audit_failure(
        self,
        session: SessionId,
        llm: LLMPort,
        request: ChatRequest,
        outcome: str,
        started: float,
        *,
        leak: bool = False,
        counts: dict[EntityType, int] | None = None,
    ) -> None:
        entity_counts = {k.value: v for k, v in (counts or {}).items()}
        elapsed = self._clock.perf_ms() - started
        self._audit.record(
            AuditEvent(
                timestamp=self._clock.now(),
                operation="chat",
                session_hash=session_hash(session),
                provider=llm.name,
                model=request.model or "",
                entity_counts=entity_counts,
                outcome=outcome,
                leak_blocked=leak,
                detect_ms=elapsed,
                total_ms=elapsed,
            )
        )
