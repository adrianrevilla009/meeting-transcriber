from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class AuditEvent:
    """Registro de una operación. NO contiene texto ni valores reales: solo recuentos, hashes y latencias."""

    timestamp: datetime
    operation: str  # anonymize | deanonymize | chat | chat_stream
    session_hash: str
    provider: str = ""
    model: str = ""
    entity_counts: dict[str, int] = field(default_factory=dict)
    strategy_counts: dict[str, int] = field(default_factory=dict)
    outcome: str = "ok"  # ok | leak_blocked | policy_blocked | detector_unavailable | provider_error
    leak_blocked: bool = False
    unknown_tokens: int = 0
    skipped_local: bool = False
    detect_ms: float = 0.0
    provider_ms: float = 0.0
    total_ms: float = 0.0
