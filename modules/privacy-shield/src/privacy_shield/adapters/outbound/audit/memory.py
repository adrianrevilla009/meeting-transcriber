from privacy_shield.domain.audit import AuditEvent


class MemoryAuditAdapter:
    """Para tests: guarda los eventos en una lista."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class NullAuditAdapter:
    def record(self, event: AuditEvent) -> None:
        return None
