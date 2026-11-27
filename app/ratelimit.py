"""Basic in-memory rate limits per phone number and per IP (one process, no Redis)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self.lock:
            q = self.hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self.lock:
            self.hits.clear()

    def check(self, *keys: str) -> None:
        for key in keys:
            if key and not self.allow(key):
                raise HTTPException(429, "too many requests, please slow down")
