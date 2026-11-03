"""Background job worker: `python -m app.jobs.worker` (plan §10, D10).

Claiming jobs from `job_runs` with FOR UPDATE SKIP LOCKED is implemented in P1-T9.
"""

import logging
import signal
import time
from types import FrameType

from app.config import get_settings

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
        time.sleep(poll)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
