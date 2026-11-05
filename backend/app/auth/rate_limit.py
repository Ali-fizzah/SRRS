"""Slow down password guessing (task P6-T5).

Counted per email, not per address: every browser call reaches FastAPI through the Next.js rewrite
(D11), so all users share one client address. The count lives in memory, which suits the one API
process this system runs; a restart forgets it. Someone who knows an email can lock it for a few
minutes, which is an accepted cost: it stops guessing and never touches the account.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

_MAX_TRACKED = 10_000


@dataclass
class LoginLimiter:
    clock: Callable[[], float] = time.monotonic
    _failures: dict[str, list[float]] = field(default_factory=dict)

    def retry_after(self, email: str, max_failures: int, window_seconds: int) -> int:
        """Seconds this email must wait, or 0 if it may try now."""
        recent = self._recent(email, window_seconds)
        if len(recent) < max_failures:
            return 0
        return max(int(recent[0] + window_seconds - self.clock()) + 1, 1)

    def record_failure(self, email: str, max_failures: int, window_seconds: int) -> bool:
        """Count a wrong password. True if this failure is the one that locks the email."""
        if len(self._failures) >= _MAX_TRACKED:
            self._forget_expired(window_seconds)
        recent = self._recent(email, window_seconds)
        recent.append(self.clock())
        self._failures[email] = recent
        return len(recent) == max_failures

    def clear(self, email: str) -> None:
        self._failures.pop(email, None)

    def reset(self) -> None:
        self._failures.clear()

    def _recent(self, email: str, window_seconds: int) -> list[float]:
        cutoff = self.clock() - window_seconds
        return [at for at in self._failures.get(email, []) if at > cutoff]

    def _forget_expired(self, window_seconds: int) -> None:
        cutoff = self.clock() - window_seconds
        self._failures = {
            email: [at for at in times if at > cutoff]
            for email, times in self._failures.items()
            if any(at > cutoff for at in times)
        }
        if len(self._failures) >= _MAX_TRACKED:  # a flood of different emails: never grow forever
            self._failures.clear()


login_limiter = LoginLimiter()
