"""Тесты для MQTT command handlers"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.main import handle_install_cmd, build_mqtt_params
from app.config import AddonConfig
from app.orchestrator import UpdateOrchestrator


def cfg():
    """Fixture конфигурации для тестов."""
    return AddonConfig()


def _mock_update_info():
    class Dummy:
        version = "15.3.0"
    return Dummy()


def test_handle_install_cmd_success():
    """Проверяем успешный сценарий установки через MQTT."""
    cfg = AddonConfig()
    mqtt_mock = MagicMock()
    orchestrator_mock = MagicMock(spec=UpdateOrchestrator)

    with patch("app.main.fetch_available_update", return_value=_mock_update_info()), \
         patch("app.main.check_for_update_and_download", return_value=Path("/tmp/bundle.raucb")), \
         patch("app.main.get_current_haos_version", return_value="15.2.0"):

        handle_install_cmd(cfg, orchestrator_mock)

    # Проверяем, что orchestrator.run_install был вызван
    orchestrator_mock.run_install.assert_called_once()


def test_handle_install_cmd_no_bundle():
    """Проверяем сценарий когда бандл не удалось получить."""
    cfg = AddonConfig()
    mqtt_mock = MagicMock()
    orchestrator_mock = MagicMock(spec=UpdateOrchestrator)

    with patch("app.main.fetch_available_update", return_value=_mock_update_info()), \
         patch("app.main.check_for_update_and_download", return_value=None), \
         patch("app.main.get_current_haos_version", return_value="15.2.0"):

        handle_install_cmd(cfg, orchestrator_mock)

    # Проверяем, что run_install НЕ был вызван
    orchestrator_mock.run_install.assert_not_called()


def test_handle_install_cmd_no_orchestrator():
    """Проверяем сценарий когда orchestrator не передан."""
    cfg = AddonConfig()

    with patch("app.main.logger") as mock_logger:
        handle_install_cmd(cfg, None)
        mock_logger.error.assert_called_once() 