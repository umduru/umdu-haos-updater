import os
import sys
from pathlib import Path


# Ensure `app` package is importable (it lives in umdu_haos_updater/app)
ROOT = Path(__file__).resolve().parents[1]
PKG_PARENT = ROOT / "umdu_haos_updater"
if str(PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(PKG_PARENT))


def pytest_configure(config):
    # Keep environment predictable for tests
    os.environ.pop("SUPERVISOR_TOKEN", None)
