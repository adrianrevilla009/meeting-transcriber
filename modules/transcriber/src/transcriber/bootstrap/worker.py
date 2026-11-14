"""Punto de entrada del worker: `python -m transcriber.bootstrap.worker`."""

import logging
import time

from transcriber.application.pipeline import run_once
from transcriber.bootstrap import get_runtime
from transcriber.config import get_settings

log = logging.getLogger("worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    rt = get_runtime()
    rt.init_db()
    s = get_settings()
    log.info("Worker iniciado (transcriber=%s, modelo=%s)", s.transcriber, s.whisper_model)
    while True:
        with rt.session() as session:
            busy = run_once(session, rt)
        if not busy:
            time.sleep(s.worker_poll_seconds)


if __name__ == "__main__":
    main()
