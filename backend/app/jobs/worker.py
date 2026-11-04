"""Background job worker: `python -m app.jobs.worker` (plan §10, D10)."""

import logging
import signal
import time
from types import FrameType

import app.jobs.ingest  # noqa: F401  (registers the INGEST handler)
from app.config import get_settings
from app.db.session import SessionLocal
from app.jobs.queue import run_next_job

log = logging.getLogger("revrec.worker")
_running = True


def _stop(signum: int, frame: FrameType | None) -> None:
    global _running
    _running = False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    poll = get_settings().worker_poll_seconds
    log.info("worker started (poll every %ss)", poll)
    while _running:
        try:
            if not run_next_job(SessionLocal):
                time.sleep(poll)
        except Exception:  # e.g. the database is restarting: keep the worker alive
            log.exception("could not reach the job queue; retrying")
            time.sleep(poll)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
