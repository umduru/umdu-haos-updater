"""Lightweight CPU & memory profiling utilities.

This module wraps *cProfile* and *tracemalloc* in a simple API so that
profiling can be toggled at runtime without changing application logic.
Reports are written to the /share directory so they persist across HA
add-on restarts.
"""

from __future__ import annotations

import cProfile
import pstats
import tracemalloc
from pathlib import Path
from typing import Optional, Callable
import logging

__all__ = [
    "start_profiling",
]

logger = logging.getLogger(__name__)


SHARE_DIR = Path("/share/umdu-haos-updater")
SHARE_DIR.mkdir(parents=True, exist_ok=True)

PROFILE_PATH = SHARE_DIR / "cpu_profile.pstats"
MEM_SNAPSHOT_PATH = SHARE_DIR / "memory_snapshot.tsmem"
REPORT_PATH = SHARE_DIR / "profile_report.txt"


class _ProfilerContext:
    def __init__(self) -> None:
        self._prof: Optional[cProfile.Profile] = None

    # ------------------------------------------------------------------
    # Context manager helpers
    # ------------------------------------------------------------------
    def __enter__(self) -> "_ProfilerContext":  # noqa: D401
        self._prof = cProfile.Profile()
        self._prof.enable()
        tracemalloc.start()
        logger.info("Profiling started (cProfile + tracemalloc)")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):  # noqa: D401
        if self._prof is None:
            return False
        self._prof.disable()
        self._prof.dump_stats(str(PROFILE_PATH))

        snapshot = tracemalloc.take_snapshot()
        snapshot.dump(str(MEM_SNAPSHOT_PATH))

        self._render_report(self._prof, snapshot)
        tracemalloc.stop()
        logger.info("Profiling finished – report saved to %s", REPORT_PATH)
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _render_report(prof: cProfile.Profile, snapshot: tracemalloc.Snapshot) -> None:
        """Generate a human-friendly txt report combining CPU & memory data."""

        with REPORT_PATH.open("w", encoding="utf-8") as fp:
            fp.write("==== CPU: top 30 cumulative ====" + "\n")
            stats = pstats.Stats(prof, stream=fp)
            stats.sort_stats(pstats.SortKey.CUMULATIVE).print_stats(30)

            fp.write("\n==== MEMORY: top 20 lines ====" + "\n")
            top_stats = snapshot.statistics("lineno")
            for i, stat in enumerate(top_stats[:20], 1):
                fp.write(f"#{i}: {stat}\n")
                frame = stat.traceback[0]
                fp.write(f"    File \"{frame.filename}\", line {frame.lineno}\n")

            total = sum(stat.size for stat in top_stats)
            fp.write(f"\nTotal allocated size of top 20: {total / 1024 / 1024:.2f} MiB\n")


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

def start_profiling(enabled: bool = False) -> Callable[[], None]:
    """Start profiling if *enabled* is True; returns *stop* callable.

    Example::

        stop = start_profiling(cfg.debug)
        try:
            ...  # run app
        finally:
            stop()
    """

    if not enabled:
        return lambda: None

    ctx = _ProfilerContext()
    ctx.__enter__()

    def _stop() -> None:  # noqa: D401
        ctx.__exit__(None, None, None)

    return _stop