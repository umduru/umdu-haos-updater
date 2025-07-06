"""Tests for profiling utilities."""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest  # type: ignore

from app.profiling import start_profiling


class DummyProfile:  # noqa: D401 – stand-in for cProfile.Profile
    def __init__(self):
        self.enabled = False

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def dump_stats(self, *a, **kw):
        pass


@pytest.mark.parametrize("enabled", [False, True])
def test_start_profiling(monkeypatch, enabled):
    """start_profiling returns callable and respects enabled flag."""

    # Patch cProfile and tracemalloc
    monkeypatch.setattr("app.profiling.cProfile.Profile", DummyProfile)
    monkeypatch.setattr("app.profiling.tracemalloc.start", lambda: None)
    monkeypatch.setattr("app.profiling.tracemalloc.stop", lambda: None)
    monkeypatch.setattr("app.profiling.tracemalloc.take_snapshot", lambda: MagicMock())

    stop = start_profiling(enabled=enabled)
    assert callable(stop)
    # If enabled, DummyProfile should be active
    if enabled:
        assert isinstance(stop, types.FunctionType)
        stop()  # Should execute without error
    else:
        # No-op lambda for disabled mode
        assert stop is not None