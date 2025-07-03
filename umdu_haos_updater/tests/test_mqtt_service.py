"""Тесты для модуля mqtt_service.py"""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, ANY

import json

from app.mqtt_service import (
    MqttService,
    COMMAND_TOPIC,
    UPDATE_DISC_TOPIC,
    STATE_TOPIC,
    UPDATE_AVAIL_TOPIC,
)


class TestMqttService:
    """Юнит-тесты для класса MqttService (без реального брокера)."""

    @patch("app.mqtt_service.mqtt.Client")
    def test_publish_update_state(self, mock_client_cls):
        """Проверка публикации состояния обновления."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=True)
        # Симулируем успешное подключение
        service._on_connect(mock_client, None, None, 0)

        service.publish_update_state("15.2.0", "15.2.1", in_progress=True)

        # Проверяем, что вызван publish с правильными параметрами
        expected_payload = json.dumps(
            {
                "installed_version": "15.2.0",
                "latest_version": "15.2.1",
                "in_progress": True,
            }
        )
        mock_client.publish.assert_any_call(STATE_TOPIC, expected_payload, retain=True)

    @patch("app.mqtt_service.mqtt.Client")
    def test_discovery_messages_on_connect(self, mock_client_cls):
        """Проверяем, что при on_connect публикуются discovery-сообщения."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=True)

        # Эмулируем успешный коннект
        service._on_connect(mock_client, None, None, 0)

        # Должно публиковаться discovery update entity
        published_topics = [call.args[0] for call in mock_client.publish.call_args_list]
        assert UPDATE_DISC_TOPIC in published_topics

    @patch("app.mqtt_service.mqtt.Client")
    def test_handle_install_commands(self, mock_client_cls):
        """Проверяем обработку входящих MQTT-команд."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        called = {"install": False}

        def install_cb():
            called["install"] = True

        service = MqttService(
            host="localhost",
            discovery=True,
            on_install_cmd=install_cb,
        )

        # Установим connected manually
        service._on_connect(mock_client, None, None, 0)

        # --- install ---
        msg_install = SimpleNamespace(topic=COMMAND_TOPIC, payload=b"install")
        service._on_message(mock_client, None, msg_install)
        assert called["install"] is True

    @patch("app.mqtt_service.mqtt.Client")
    def test_clear_retained_messages(self, mock_client_cls):
        """Проверка очистки retain-сообщений."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=True)
        service._on_connect(mock_client, None, None, 0)

        # simulate clearing
        service.clear_retained_messages()

        # Два топика должны быть очищены (без REBOOT_AVAIL_TOPIC)
        topics_cleared = [call.args[0] for call in mock_client.publish.call_args_list if call.args[1] == ""]
        assert set(topics_cleared) >= {STATE_TOPIC, UPDATE_AVAIL_TOPIC} 