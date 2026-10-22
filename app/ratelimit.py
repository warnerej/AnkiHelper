"""In-memory sliding-window rate limits for the unauthenticated auth endpoints.

Per process, so it assumes a single instance. Keyed by client IP: behind a proxy uvicorn
must run with --proxy-headers and --forwarded-allow-ips, otherwise every caller shares the
proxy's address and one limit covers all users.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status

from app.dependencies import get_client_ip

MAX_TRACKED_KEYS = 10_000

_limiters: list["RateLimiter"] = []


def reset_all() -> None:
    """Forget every recorded hit (for tests)."""
    for limiter in _limiters:
        limiter._hits.clear()


class RateLimiter:
    def __init__(
        self, max_calls: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ):
        self._max = max_calls
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self._clock()
        if len(self._hits) > MAX_TRACKED_KEYS:
            self._evict(now)
        hits = self._hits[key]
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._max:
            return False
        hits.append(now)
        return True

    def _evict(self, now: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= self._window]:
            del self._hits[key]


def rate_limit(max_calls: int, window_seconds: float, name: str):
    """A FastAPI dependency answering 429 once an IP exceeds `max_calls` per window."""
    limiter = RateLimiter(max_calls, window_seconds)
    _limiters.append(limiter)

    def dependency(request: Request, ip: str = Depends(get_client_ip)) -> None:
        if not limiter.allow(f"{name}:{ip}"):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests; try again later",
                headers={"Retry-After": str(int(window_seconds))},
            )

    return dependency
