import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from app.orchestrator import UpdateOrchestrator
from app.config import AddonConfig
from app.errors import InstallError


class TestUpdateOrchestrator:
    """Юнит-тесты для класса UpdateOrchestrator"""

    def _make_orchestrator(self, **cfg_kwargs):
        cfg = AddonConfig(**cfg_kwargs)
        notifier = Mock()  # NotificationService mock (send attr will be spy)
        return UpdateOrchestrator(cfg, notifier), notifier

    # ------------------------------------------------------------------
    # check_and_download
    # ------------------------------------------------------------------
    def test_check_and_download_delegates(self):
        orch, _ = self._make_orchestrator()
        expected_path = Path("/tmp/bundle.raucb")
        with patch("app.orchestrator.check_for_update_and_download", return_value=expected_path) as mock_fn:
            result = orch.check_and_download()
        assert result == expected_path
        mock_fn.assert_called_once()

    # ------------------------------------------------------------------
    # install_if_ready
    # ------------------------------------------------------------------
    def test_install_success(self):
        orch, notifier = self._make_orchestrator()
        path = Path("/tmp/bundle.raucb")
        with patch("app.orchestrator.install_bundle", return_value=True) as mock_install, \
             patch.object(Path, "touch") as mock_touch:
            res = orch.install_if_ready(path)
        assert res is True
        mock_install.assert_called_once_with(path)
        mock_touch.assert_called_once()  # успех уведомляет

    def test_install_failure(self):
        orch, notifier = self._make_orchestrator()
        path = Path("/tmp/bundle.raucb")
        with patch("app.orchestrator.install_bundle", side_effect=InstallError("boom")) as mock_install, \
             patch.object(Path, "touch") as mock_touch:
            res = orch.install_if_ready(path)
        assert res is False
        mock_install.assert_called_once_with(path)
        mock_touch.assert_not_called()
        notifier.send.assert_called_once()  # уведомление об ошибке

    # ------------------------------------------------------------------
    # auto_cycle_once
    # ------------------------------------------------------------------
    def test_auto_cycle_once_with_update(self):
        # auto_update True — должен вызвать install
        orch, notifier = self._make_orchestrator(auto_update=True)
        bundle_path = Path("/tmp/bundle.raucb")
        with patch.object(orch, "check_and_download", return_value=bundle_path) as mock_check, \
             patch.object(orch, "install_if_ready", return_value=True) as mock_install, \
             patch("app.orchestrator.get_current_haos_version", return_value="15.2.0"):
            orch.auto_cycle_once()
        mock_check.assert_called_once()
        mock_install.assert_called_once_with(bundle_path)
        # Уведомление об успешной установке уже проверяется в install_if_ready

    def test_auto_cycle_once_no_update(self):
        orch, _ = self._make_orchestrator(auto_update=True)
        with patch.object(orch, "check_and_download", return_value=None) as mock_check, \
             patch.object(orch, "install_if_ready") as mock_install:
            orch.auto_cycle_once()
        mock_check.assert_called_once()
        mock_install.assert_not_called() 