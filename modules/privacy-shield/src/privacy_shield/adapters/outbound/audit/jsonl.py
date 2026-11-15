"""Auditoría en JSONL. Cada línea es un AuditEvent: recuentos, hashes y latencias; nunca texto ni valores."""

import json
import threading
from dataclasses import asdict
from pathlib import Path

from privacy_shield.domain.audit import AuditEvent


class JsonlAuditAdapter:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: AuditEvent) -> None:
        data = asdict(event)
        data["timestamp"] = event.timestamp.isoformat()
        line = json.dumps(data, ensure_ascii=False)
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
