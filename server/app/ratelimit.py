"""Per-user sliding-window rate limits (api-spec: 60 req/min, /agent/chat 10 req/min).

Keyed by Clerk user id, not IP: Hugging Face proxies every request. In-memory is
enough for a single-instance Space.
"""

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Depends

from .auth import User, current_user
from .errors import ApiError


class RateLimit:
    def __init__(self, per_minute: int, scope: str = "default"):
        self.per_minute = per_minute
        self.scope = scope
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - 60:
                q.popleft()
            if len(q) >= self.per_minute:
                raise ApiError(429, f"Rate limit exceeded ({self.per_minute} requests/min)")
            q.append(now)

    def __call__(self, user: User = Depends(current_user)) -> User:
        self.hit(user.id)
        return user


default_limit = RateLimit(60, "default")
chat_limit = RateLimit(10, "chat")
