"""Concurrency tests to ensure UpdateOrchestrator prevents double install."""

from __future__ import annotations

import threading
from pathlib import Path
from app.orchestrator import UpdateOrchestrator
from app.config import AddonConfig
from app.notification_service import NotificationService


def test_concurrent_run_install(monkeypatch):
    cfg = AddonConfig(auto_update=False)
    orchestrator = UpdateOrchestrator(cfg, notifier=NotificationService(enabled=False))

    # Avoid external HTTP in publish_state
    monkeypatch.setattr("app.orchestrator.get_current_haos_version", lambda: "15.0.0")

    install_calls: list[Path] = []

    def fake_install(bundle_path: Path) -> bool:  # noqa: D401
        install_calls.append(bundle_path)
        return True

    monkeypatch.setattr(orchestrator, "install_if_ready", fake_install)

    bundle = Path("/tmp/fake_bundle.raucb")

    # Fire two threads simultaneously
    t1 = threading.Thread(target=orchestrator.run_install, args=(bundle,))
    t2 = threading.Thread(target=orchestrator.run_install, args=(bundle,))

    t1.start(); t2.start()
    t1.join(); t2.join()

    # Only one installation should have occurred
    assert len(install_calls) == 1