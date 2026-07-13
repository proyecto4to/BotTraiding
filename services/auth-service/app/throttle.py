"""In-memory brute-force protection for login, keyed by client IP.

After LOGIN_MAX_ATTEMPTS failed logins within LOGIN_ATTEMPT_WINDOW seconds an
IP is blocked for LOGIN_BLOCK_SECONDS. This is process-local (a first line of
defence); a Redis-backed store is the multi-replica upgrade (see the plan's
P3/P15). Passwords are never touched here — only success/failure per IP.
"""

from __future__ import annotations

import os
import threading
import time


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class LoginThrottle:
    def __init__(
        self,
        max_attempts: int | None = None,
        window_seconds: int | None = None,
        block_seconds: int | None = None,
    ) -> None:
        self.max_attempts = max_attempts if max_attempts is not None else _int_env(
            "LOGIN_MAX_ATTEMPTS", 5
        )
        self.window_seconds = window_seconds if window_seconds is not None else _int_env(
            "LOGIN_ATTEMPT_WINDOW", 600
        )
        self.block_seconds = block_seconds if block_seconds is not None else _int_env(
            "LOGIN_BLOCK_SECONDS", 1800
        )
        self._failures: dict[str, list[float]] = {}
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        return time.monotonic()

    def retry_after(self, ip: str) -> int:
        """Seconds until `ip` may try again, or 0 if not blocked."""
        with self._lock:
            until = self._blocked_until.get(ip)
            if until is None:
                return 0
            remaining = until - self._now()
            if remaining <= 0:
                self._blocked_until.pop(ip, None)
                return 0
            return int(remaining) + 1

    def is_blocked(self, ip: str) -> bool:
        return self.retry_after(ip) > 0

    def record_failure(self, ip: str) -> None:
        with self._lock:
            now = self._now()
            window_start = now - self.window_seconds
            recent = [t for t in self._failures.get(ip, []) if t >= window_start]
            recent.append(now)
            self._failures[ip] = recent
            if len(recent) >= self.max_attempts:
                self._blocked_until[ip] = now + self.block_seconds
                self._failures[ip] = []

    def reset(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)
            self._blocked_until.pop(ip, None)


# Module-level singleton used by the login endpoint.
throttle = LoginThrottle()
