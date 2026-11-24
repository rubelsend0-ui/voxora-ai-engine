"""Rate limiting: in-memory sliding window by default, Redis fixed window when configured."""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import Callable
from functools import lru_cache

from app.core.errors import RateLimited


class RateLimiter(ABC):
    @abstractmethod
    def hit(self, key: str, limit: int, window_seconds: int = 60) -> None:
        """Register one request. Raises :class:`RateLimited` when the limit is exceeded."""


class InMemoryRateLimiter(RateLimiter):
    """Sliding-window limiter. Per-process only - use Redis for multi-worker deployments."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> None:
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_seconds:
                q.popleft()
            if len(q) >= limit:
                retry_after = max(1, int(q[0] + window_seconds - now) + 1)
                raise RateLimited(
                    "Rate limit exceeded. Try again later.",
                    details={"retry_after_seconds": retry_after},
                    headers={"Retry-After": str(retry_after)},
                )
            q.append(now)


class RedisRateLimiter(RateLimiter):
    """Fixed-window counter shared between all API workers."""

    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url, socket_timeout=2)

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> None:
        bucket = int(time.time() // window_seconds)
        rkey = f"voxora:rl:{key}:{bucket}"
        try:
            pipe = self._r.pipeline()
            pipe.incr(rkey)
            pipe.expire(rkey, window_seconds + 1)
            count, _ = pipe.execute()
        except Exception:  # A Redis outage must not take the API down: fail open, but log it.
            logging.getLogger("voxora.ratelimit").warning("Redis rate limiter unavailable; allowing request")
            return
        if int(count) > limit:
            retry_after = window_seconds - int(time.time() % window_seconds) + 1
            raise RateLimited(
                "Rate limit exceeded. Try again later.",
                details={"retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after)},
            )


@lru_cache
def get_rate_limiter() -> RateLimiter:
    from app.core.config import get_settings

    s = get_settings()
    if s.redis_url:
        return RedisRateLimiter(s.redis_url)
    return InMemoryRateLimiter()
