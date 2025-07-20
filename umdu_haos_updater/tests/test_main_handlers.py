"""Тесты для MQTT command handlers"""
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from umdu_haos_updater.app.main import handle_install_cmd, build_mqtt_params
from umdu_haos_updater.app.config import AddonConfig
from umdu_haos_updater.app.orchestrator import UpdateOrchestrator


def cfg():
    """Fixture конфигурации для тестов."""
    with patch('builtins.open'), patch('umdu_haos_updater.app.config.json.load', return_value={}):
        return AddonConfig()


def _mock_update_info():
    class Dummy:
        version = "15.3.0"
    return Dummy()


def test_handle_install_cmd_success():
    """Проверяем успешный сценарий установки через MQTT."""
    orchestrator_mock = MagicMock(spec=UpdateOrchestrator)

    with patch("umdu_haos_updater.app.main.fetch_available_update", return_value=_mock_update_info()), \
         patch("umdu_haos_updater.app.main.check_for_update_and_download", return_value=Path("/tmp/bundle.raucb")), \
         patch("umdu_haos_updater.app.updater.get_current_haos_version", return_value="15.2.0"):

        handle_install_cmd(orchestrator_mock)

    # Проверяем, что orchestrator.run_install был вызван
    orchestrator_mock.run_install.assert_called_once()


def test_handle_install_cmd_no_bundle():
    """Проверяем сценарий когда бандл не удалось получить."""
    orchestrator_mock = MagicMock(spec=UpdateOrchestrator)

    with patch("umdu_haos_updater.app.main.fetch_available_update", return_value=_mock_update_info()), \
         patch("umdu_haos_updater.app.main.check_for_update_and_download", return_value=None), \
         patch("umdu_haos_updater.app.updater.get_current_haos_version", return_value="15.2.0"):

        handle_install_cmd(orchestrator_mock)

    # Проверяем, что run_install НЕ был вызван
    orchestrator_mock.run_install.assert_not_called()

    # Проверяем, что publish_state был вызван
    orchestrator_mock.publish_state.assert_called_once()


def test_handle_install_cmd_no_orchestrator():
    """Проверяем сценарий когда orchestrator не передан."""
    with pytest.raises(TypeError):
        handle_install_cmd()  # Вызов без параметров должен вызвать ошибку