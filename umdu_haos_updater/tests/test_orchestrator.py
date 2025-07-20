import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from app.orchestrator import UpdateOrchestrator
from app.config import AddonConfig
from app.errors import InstallError
from app.updater import UpdateInfo


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

    def test_auto_cycle_once_in_progress(self):
        """Тест пропуска цикла когда установка уже в процессе"""
        orch, _ = self._make_orchestrator()
        orch._in_progress = True
        with patch.object(orch, "check_and_download") as mock_check:
            orch.auto_cycle_once()
        mock_check.assert_not_called()

    # ------------------------------------------------------------------
    # set_mqtt_service
    # ------------------------------------------------------------------
    def test_set_mqtt_service(self):
        """Тест установки MQTT сервиса"""
        orch, _ = self._make_orchestrator()
        mqtt_service = Mock()
        orch.set_mqtt_service(mqtt_service)
        assert orch._mqtt_service == mqtt_service

    def test_set_mqtt_service_none(self):
        """Тест установки None для MQTT сервиса"""
        orch, _ = self._make_orchestrator()
        orch.set_mqtt_service(None)
        assert orch._mqtt_service is None

    # ------------------------------------------------------------------
    # publish_state
    # ------------------------------------------------------------------
    def test_publish_state_no_mqtt(self):
        """Тест публикации состояния без MQTT сервиса"""
        orch, _ = self._make_orchestrator()
        # Не должно вызывать ошибок
        orch.publish_state("15.2.0", "15.2.1")

    @patch('app.orchestrator.get_current_haos_version')
    def test_publish_state_with_mqtt(self, mock_current_version):
        """Тест публикации состояния с MQTT сервисом"""
        mock_current_version.return_value = "15.2.0"
        orch, _ = self._make_orchestrator()
        mqtt_service = Mock()
        orch.set_mqtt_service(mqtt_service)
        
        orch.publish_state("15.2.0", "15.2.1")
        
        mqtt_service.publish_update_state.assert_called_once_with("15.2.0", "15.2.1", False)

    @patch('app.orchestrator.get_current_haos_version')
    @patch('app.orchestrator.fetch_available_update')
    def test_publish_state_fetch_latest(self, mock_fetch, mock_current_version):
        """Тест публикации состояния с получением latest версии"""
        mock_current_version.return_value = "15.2.0"
        mock_fetch.return_value = UpdateInfo("15.2.1")
        
        orch, _ = self._make_orchestrator()
        mqtt_service = Mock()
        orch.set_mqtt_service(mqtt_service)
        
        orch.publish_state()
        
        mqtt_service.publish_update_state.assert_called_once_with("15.2.0", "15.2.1", False)

    @patch('app.orchestrator.get_current_haos_version')
    @patch('app.orchestrator.fetch_available_update')
    def test_publish_state_fetch_error(self, mock_fetch, mock_current_version):
        """Тест публикации состояния при ошибке получения latest версии"""
        mock_current_version.return_value = "15.2.0"
        mock_fetch.side_effect = Exception("Network error")
        
        orch, _ = self._make_orchestrator()
        mqtt_service = Mock()
        orch.set_mqtt_service(mqtt_service)
        
        orch.publish_state()
        
        mqtt_service.publish_update_state.assert_called_once_with("15.2.0", "15.2.0", False)

    # ------------------------------------------------------------------
    # run_install
    # ------------------------------------------------------------------
    def test_run_install_success(self):
        """Тест успешной установки через run_install"""
        orch, notifier = self._make_orchestrator()
        mqtt_service = Mock()
        orch.set_mqtt_service(mqtt_service)
        bundle_path = Path("/tmp/bundle.raucb")
        
        with patch.object(orch, "install_if_ready", return_value=True) as mock_install, \
             patch.object(orch, "publish_state") as mock_publish:
            orch.run_install(bundle_path, "15.2.1")
        
        mock_install.assert_called_once_with(bundle_path)
        mqtt_service.deactivate_update_entity.assert_called_once()
        notifier.send.assert_called_once()
        mock_publish.assert_called_once_with(latest="15.2.1")
        assert orch._in_progress is False

    def test_run_install_failure(self):
        """Тест неудачной установки через run_install"""
        orch, notifier = self._make_orchestrator()
        mqtt_service = Mock()
        orch.set_mqtt_service(mqtt_service)
        bundle_path = Path("/tmp/bundle.raucb")
        
        with patch.object(orch, "install_if_ready", return_value=False) as mock_install, \
             patch.object(orch, "publish_state") as mock_publish:
            orch.run_install(bundle_path, "15.2.1")
        
        mock_install.assert_called_once_with(bundle_path)
        mqtt_service.deactivate_update_entity.assert_not_called()
        # publish_state вызывается дважды: в начале и в конце при неудаче
        assert mock_publish.call_count == 2
        notifier.send.assert_not_called()
        assert orch._in_progress is False

    def test_run_install_no_mqtt(self):
        """Тест установки без MQTT сервиса"""
        orch, notifier = self._make_orchestrator()
        bundle_path = Path("/tmp/bundle.raucb")
        
        with patch.object(orch, "install_if_ready", return_value=True) as mock_install, \
             patch.object(orch, "publish_state") as mock_publish:
            orch.run_install(bundle_path)
        
        mock_install.assert_called_once_with(bundle_path)
        notifier.send.assert_called_once()
        mock_publish.assert_called_once_with(latest=None)
        assert orch._in_progress is False

    # ------------------------------------------------------------------
    # _touch_reboot_flag
    # ------------------------------------------------------------------
    def test_touch_reboot_flag(self):
        """Тест создания флага перезагрузки"""
        with patch.object(Path, "touch") as mock_touch:
            UpdateOrchestrator._touch_reboot_flag()
        mock_touch.assert_called_once_with(exist_ok=True)