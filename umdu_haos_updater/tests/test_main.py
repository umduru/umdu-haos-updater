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


@pytest.mark.asyncio
async def test_try_initialize_mqtt_success(mocker):
    """Тест успешной инициализации MQTT с передачей Event."""
    mock_loop = asyncio.get_running_loop()
    mocker.patch("app.main.build_mqtt_params", return_value=("host", 1883, "user", "pass"))
    mock_mqtt_service_cls = mocker.patch("app.main.MqttService")
    
    from app.main import try_initialize_mqtt, AddonConfig
    
    cfg = AddonConfig(mqtt_discovery=True)
    connection_event = asyncio.Event()

    result = await try_initialize_mqtt(cfg, mock_loop, connection_event)

    mock_mqtt_service_cls.assert_called_once()
    # Проверяем, что event был передан в конструктор
    assert mock_mqtt_service_cls.call_args[1]['connection_event'] is connection_event
    mock_mqtt_service_cls.return_value.start.assert_called_once()
    assert result is not None


@pytest.mark.asyncio
async def test_main_loop_and_reconnect(mocker):
    """
    Тест основного цикла `main`:
    1. Первая попытка подключения MQTT фейлится.
    2. `auto_cycle_once` вызывается.
    3. Вторая попытка подключения успешна.
    4. `_configure_mqtt_service` вызывается для настройки.
    """
    # Патчи зависимостей
    mocker.patch("app.main.AddonConfig.load")
    mocker.patch("app.main.TOKEN", "fake-token")
    mocker.patch("app.main.NotificationService")
    mock_orchestrator = mocker.MagicMock()
    mocker.patch("app.main.UpdateOrchestrator", return_value=mock_orchestrator)
    
    # Мок MQTT сервиса
    mock_mqtt_service_instance = mocker.MagicMock()
    
    # Первая попытка - неудача, вторая - успех
    mock_try_init = mocker.patch(
        "app.main.try_initialize_mqtt", 
        side_effect=[None, mock_mqtt_service_instance]
    )
    
    # Мок `_configure_mqtt_service` чтобы проверить его вызов
    mock_configure_mqtt = mocker.patch("app.main._configure_mqtt_service")

    # Патчим sleep, чтобы цикл не ждал и прерывался после 2 итераций
    async def sleep_breaker(delay):
        if mock_try_init.call_count >= 2:
            raise asyncio.CancelledError
        await asyncio.sleep(0)
    mocker.patch("asyncio.sleep", side_effect=sleep_breaker)

    from app.main import main
    with pytest.raises(asyncio.CancelledError):
        await main()

    # Проверки
    assert mock_try_init.call_count == 2
    mock_orchestrator.auto_cycle_once.assert_called_once()
    # Проверяем что orchestrator получил None в первый раз
    mock_orchestrator.set_mqtt_service.assert_any_call(None)
    # Проверяем что после переподключения был вызван configure
    mock_configure_mqtt.assert_called_once_with(
        mock_mqtt_service_instance,
        mock_orchestrator,
        mocker.ANY,  # loop
        mocker.ANY,  # cfg
        mocker.ANY,  # event
        is_reconnect=True
    ) 