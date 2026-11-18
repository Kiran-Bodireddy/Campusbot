"""
Thread-safe sliding-window rate limiter for governed FastAPI endpoints.
Tunable limits (max_requests, window_seconds) are loaded from matching_config.yaml.
"""
import math
import time
import threading
from collections import deque
from typing import Dict, Deque, Tuple

from campus_knowledge_server.config.matching_config import load_matching_config


class SlidingWindowRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: Dict[str, Deque[float]] = {}

    def _limits(self) -> Tuple[int, int]:
        cfg = load_matching_config().get("rate_limiting", {})
        return int(cfg.get("max_requests", 20)), int(cfg.get("window_seconds", 60))

    def check(self, key: str) -> Tuple[bool, int, int]:
        """
        Records a request for `key` if allowed.
        Returns (allowed: bool, retry_after_seconds: int, remaining: int).
        """
        max_req, window_s = self._limits()
        now = time.monotonic()
        cutoff = now - window_s
        with self._lock:
            q = self._buckets.setdefault(key, deque())
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= max_req:
                oldest = q[0]
                retry_after = max(1, int(math.ceil(window_s - (now - oldest))))
                return False, retry_after, 0
            q.append(now)
            return True, 0, max_req - len(q)

    def reset(self):
        with self._lock:
            self._buckets.clear()


_RATE_LIMITER = SlidingWindowRateLimiter()


def get_rate_limiter() -> SlidingWindowRateLimiter:
    return _RATE_LIMITER
