import time
from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def perf_ms(self) -> float:
        return time.perf_counter() * 1000.0
