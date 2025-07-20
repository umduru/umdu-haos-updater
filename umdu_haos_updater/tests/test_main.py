"""Тесты для некоторых функций модуля main.py"""
import pytest
from unittest.mock import Mock, patch
from pathlib import Path
import asyncio

from app.main import build_mqtt_params
from app.config import AddonConfig


class TestBuildMqttParams:
    """Тесты для функции build_mqtt_params"""

    def test_mqtt_params_from_config(self):
        """Тест получения параметров из конфига"""
        cfg = AddonConfig(
            mqtt_host="test.local",
            mqtt_port=8883,
            mqtt_user="user",
            mqtt_password="pass"
        )
        
        host, port, user, password = build_mqtt_params(cfg)
        
        assert host == "test.local"
        assert port == 8883
        assert user == "user"
        assert password == "pass"

    def test_mqtt_params_fallback_to_supervisor(self):
        """Тест fallback к Supervisor API"""
        cfg = AddonConfig()  # Пустой конфиг
        
        supervisor_data = {
            "host": "supervisor.mqtt",
            "port": 1883,
            "username": "supervisor_user",
            "password": "supervisor_pass"
        }
        
        with patch("app.main.get_mqtt_service", return_value=supervisor_data):
            host, port, user, password = build_mqtt_params(cfg)
        
        assert host == "supervisor.mqtt"
        assert port == 1883
        assert user == "supervisor_user"
        assert password == "supervisor_pass"

    def test_mqtt_params_supervisor_exception(self):
        """Тест обработки исключения при обращении к Supervisor API"""
        cfg = AddonConfig()  # Пустой конфиг
        
        with patch("app.main.get_mqtt_service", side_effect=Exception("API error")):
            host, port, user, password = build_mqtt_params(cfg)
        
        assert host is None
        assert port == 1883
        assert user is None
        assert password is None


@pytest.mark.asyncio
async def test_try_initialize_mqtt_success(mocker):
    """Тест успешной инициализации MQTT."""
    # Мокируем get_running_loop, чтобы получить контроль над event loop
    mock_loop = mocker.patch("asyncio.get_running_loop").return_value

    # Создаем фьючер, который будет возвращать результат
    future = asyncio.Future()
    future.set_result(("host", 1883, "user", "pass"))
    mock_loop.run_in_executor.return_value = future

    mock_mqtt_service_cls = mocker.patch("app.main.MqttService")

    from app.main import try_initialize_mqtt, AddonConfig
    cfg = AddonConfig()

    result = await try_initialize_mqtt(cfg, mock_loop)

    mock_mqtt_service_cls.assert_called_once()
    mock_mqtt_service_cls.return_value.start.assert_called_once()
    assert result is not None


@pytest.mark.asyncio
async def test_try_initialize_mqtt_failure(mocker):
    """Тест неудачной инициализации MQTT (нет хоста)."""
    mock_loop = mocker.patch("asyncio.get_running_loop").return_value
    
    future = asyncio.Future()
    future.set_result((None, 1883, "user", "pass"))
    mock_loop.run_in_executor.return_value = future

    mock_mqtt_service_cls = mocker.patch("app.main.MqttService")
    mock_logger_warning = mocker.patch("app.main.logger.warning")

    from app.main import try_initialize_mqtt, AddonConfig
    cfg = AddonConfig()

    result = await try_initialize_mqtt(cfg, mock_loop)

    mock_mqtt_service_cls.assert_not_called()
    assert result is None
    mock_logger_warning.assert_called_once_with(
        "Не удалось инициализировать MQTT. Следующая попытка будет в следующем цикле."
    )


@pytest.mark.asyncio
async def test_main_loop_reconnect_logic(mocker):
    """
    Тест логики переподключения в главном цикле.
    - Первый вызов try_initialize_mqtt возвращает None.
    - Второй вызов возвращает mock service.
    """
    # Патчим все зависимости, чтобы изолировать цикл
    mocker.patch("app.main.AddonConfig.load")
    mocker.patch("app.main.TOKEN", "fake-token")
    mocker.patch("app.main.NotificationService")
    mock_orchestrator = mocker.patch("app.main.UpdateOrchestrator")
    mocker.patch("app.main.fetch_available_update")
    mocker.patch("app.main.get_current_haos_version")

    # Управляем вызовами try_initialize_mqtt
    mock_try_init_mqtt = mocker.patch(
        "app.main.try_initialize_mqtt",
        side_effect=[None, mocker.MagicMock(spec_set=["on_install_cmd", "clear_retained_messages"])]
    )

    # Патчим sleep, чтобы цикл не ждал и прерывался после 2 итераций
    async def sleep_breaker(delay):
        if mock_try_init_mqtt.call_count >= 2:
            raise asyncio.CancelledError  # Прерываем цикл
        await asyncio.sleep(0)

    mocker.patch("asyncio.sleep", side_effect=sleep_breaker)

    from app.main import main
    with pytest.raises(asyncio.CancelledError):
        await main()

    # Проверяем, что была попытка подключения дважды
    assert mock_try_init_mqtt.call_count == 2


class TestHandleInstallCmd:
    """Тесты для функции handle_install_cmd"""

    def test_handle_install_cmd_success(self, mocker):
        """Тест успешной обработки команды установки"""
        mock_cfg = mocker.Mock()
        mock_orchestrator = mocker.Mock()
        
        mock_fetch = mocker.patch("app.main.fetch_available_update")
        mock_fetch.return_value.version = "1.2.3"
        
        mock_check_download = mocker.patch("app.main.check_for_update_and_download")
        mock_check_download.return_value = Path("/fake/bundle.raucb")
        
        from app.main import handle_install_cmd
        handle_install_cmd(mock_cfg, mock_orchestrator)
        
        mock_check_download.assert_called_once_with(auto_download=True)
        mock_orchestrator.run_install.assert_called_once_with(Path("/fake/bundle.raucb"), "1.2.3")

    def test_handle_install_cmd_fetch_exception(self, mocker):
        """Тест обработки исключения при получении информации об обновлении"""
        mock_cfg = mocker.Mock()
        mock_orchestrator = mocker.Mock()
        
        mock_fetch = mocker.patch("app.main.fetch_available_update", side_effect=Exception("Network error"))
        mock_check_download = mocker.patch("app.main.check_for_update_and_download")
        mock_check_download.return_value = Path("/fake/bundle.raucb")
        
        from app.main import handle_install_cmd
        handle_install_cmd(mock_cfg, mock_orchestrator)
        
        mock_orchestrator.run_install.assert_called_once_with(Path("/fake/bundle.raucb"), None)

    def test_handle_install_cmd_no_bundle(self, mocker):
        """Тест случая, когда не удалось получить бандл"""
        mock_cfg = mocker.Mock()
        mock_orchestrator = mocker.Mock()
        
        mock_fetch = mocker.patch("app.main.fetch_available_update")
        mock_fetch.return_value.version = "1.2.3"
        
        mock_check_download = mocker.patch("app.main.check_for_update_and_download")
        mock_check_download.return_value = None
        
        from app.main import handle_install_cmd
        handle_install_cmd(mock_cfg, mock_orchestrator)
        
        mock_orchestrator.publish_state.assert_called_once_with(latest="1.2.3")
        mock_orchestrator.run_install.assert_not_called()

    def test_handle_install_cmd_no_orchestrator(self, mocker):
        """Тест случая, когда orchestrator не предоставлен"""
        mock_cfg = mocker.Mock()
        mock_logger = mocker.patch("app.main.logger")
        
        from app.main import handle_install_cmd
        handle_install_cmd(mock_cfg, None)
        
        mock_logger.error.assert_called_once_with("Orchestrator not provided for install command")


class TestMainFunction:
    """Тесты для функции main"""

    @pytest.mark.asyncio
    async def test_main_no_token(self, mocker):
        """Тест выхода из программы при отсутствии TOKEN"""
        mocker.patch("app.main.AddonConfig.load")
        mocker.patch("app.main.TOKEN", None)  # Нет токена
        # Мокируем все возможные вызовы get_current_haos_version
        mocker.patch("app.supervisor_api.get_current_haos_version", return_value="1.0.0")
        mocker.patch("app.orchestrator.get_current_haos_version", return_value="1.0.0")
        mocker.patch("app.updater.get_current_haos_version", return_value="1.0.0")
        
        # Мокируем sys.exit чтобы он вызывал исключение вместо реального выхода
        mock_sys_exit = mocker.patch("sys.exit", side_effect=SystemExit(1))
        mock_logger = mocker.patch("app.main.logger")
        
        from app.main import main
        
        # Ожидаем SystemExit исключение
        with pytest.raises(SystemExit) as exc_info:
            await main()
        
        assert exc_info.value.code == 1
        mock_logger.error.assert_called_with("SUPERVISOR_TOKEN отсутствует — работа невозможна")
        mock_sys_exit.assert_called_once_with(1)