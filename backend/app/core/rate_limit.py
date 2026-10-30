"""
A small in-memory rate limiter (SDD 10.4).

Stops one account from flooding the staff queues or using up the free AI
quota. Requests are counted per user over a sliding time window. The counts
live in this server process, which is enough for a single-server deployment.
"""
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Depends, HTTPException

from app.core.security import get_current_user
from app.models.models import User


def rate_limit(name: str, max_calls: int, per_seconds: int):
    """Dependency factory: each user may make `max_calls` requests every `per_seconds` seconds."""
    calls: dict[int, deque] = defaultdict(deque)
    lock = Lock()

    def checker(user: User = Depends(get_current_user)) -> None:
        now = time.monotonic()
        with lock:
            history = calls[user.user_id]
            while history and now - history[0] > per_seconds:
                history.popleft()
            if len(history) >= max_calls:
                wait = int(per_seconds - (now - history[0])) + 1
                raise HTTPException(status_code=429,
                                    detail=f"Too many {name} requests. Please try again in {wait} seconds.")
            history.append(now)

    return checker