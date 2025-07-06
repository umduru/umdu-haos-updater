"""Light-weight TTL cache helpers (no external deps)."""

from __future__ import annotations

import time
import functools
from typing import Callable, TypeVar, Any, Dict, Tuple

_T = TypeVar("_T")


def ttl_cache(ttl: float = 300.0):
    """Decorator that caches function result for *ttl* seconds (per arguments).*"""

    def decorator(fn: Callable[..., _T]) -> Callable[..., _T]:
        cache: Dict[Tuple[Tuple[Any, ...], Tuple[Tuple[str, Any], ...]], Tuple[_T, float]] = {}

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> _T:  # type: ignore[override]
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            if key in cache:
                result, timestamp = cache[key]
                if now - timestamp < ttl:
                    return result
            result = fn(*args, **kwargs)
            cache[key] = (result, now)
            return result

        return wrapper

    return decorator