"""Tests for ttl_cache decorator.

Property-based tests assure that function is evaluated once within TTL and again after expiry.
"""

from __future__ import annotations

import time
from app.cache_utils import ttl_cache


class _Counter:
    def __init__(self):
        self.value = 0

    def inc(self):
        self.value += 1
        return self.value


def test_ttl_cache_basic(monkeypatch):
    """Function should be executed once within TTL window."""
    counter = _Counter()

    @ttl_cache(ttl=5.0)
    def fn():  # noqa: D401
        return counter.inc()

    # First call executes underlying function
    assert fn() == 1
    # Second call within ttl returns cached result
    assert fn() == 1
    assert counter.value == 1

    # Simulate time passage beyond TTL
    orig_time = time.time
    monkeypatch.setattr(time, "time", lambda: orig_time() + 10)
    assert fn() == 2
    assert counter.value == 2


def test_ttl_cache_with_args(monkeypatch):
    """Caching should be argument-sensitive."""
    calls: dict[tuple[int, int], int] = {}

    @ttl_cache(ttl=5)
    def add(a: int, b: int) -> int:  # noqa: D401
        calls[(a, b)] = calls.get((a, b), 0) + 1
        return a + b

    assert add(1, 2) == 3
    assert add(1, 2) == 3
    assert calls[(1, 2)] == 1

    assert add(2, 3) == 5
    assert calls[(2, 3)] == 1

    # Expire cache
    orig_time2 = time.time
    monkeypatch.setattr(time, "time", lambda: orig_time2() + 6)
    assert add(1, 2) == 3
    assert calls[(1, 2)] == 2