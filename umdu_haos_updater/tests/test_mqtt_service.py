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
        # State сообщения публикуются без retain и с qos=1
        mock_client.publish.assert_any_call(STATE_TOPIC, expected_payload, retain=False, qos=1)

    @patch("app.mqtt_service.mqtt.Client")
    def test_publish_update_availability_online(self, mock_client_cls):
        """Проверка публикации доступности online."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=True)
        service._on_connect(mock_client, None, None, 0)

        service.publish_update_availability(True)

        mock_client.publish.assert_called_with(
            UPDATE_AVAIL_TOPIC, "online", retain=True
        )

    @patch("app.mqtt_service.mqtt.Client")
    def test_publish_update_availability_offline(self, mock_client_cls):
        """Проверка публикации доступности offline."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=True)
        service._on_connect(mock_client, None, None, 0)

        service.publish_update_availability(False)

        mock_client.publish.assert_called_with(
            UPDATE_AVAIL_TOPIC, "offline", retain=True
        )

    @patch("app.mqtt_service.mqtt.Client")
    def test_publish_when_not_ready(self, mock_client_cls):
        """Проверка что публикация не происходит когда сервис не готов."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=False)  # discovery отключен
        
        service.publish_update_state("15.2.0", "15.2.1")
        service.publish_update_availability(True)

        mock_client.publish.assert_not_called()

    @patch("app.mqtt_service.mqtt.Client")
    def test_deactivate_update_entity(self, mock_client_cls):
        """Проверка деактивации update entity."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=True)
        service._on_connect(mock_client, None, None, 0)

        service.deactivate_update_entity()

        # Проверяем публикацию пустого discovery сообщения
        mock_client.publish.assert_called_with(
            UPDATE_DISC_TOPIC, "", retain=True
        )
        assert service._update_entity_active is False

    @patch("app.mqtt_service.mqtt.Client")
    def test_on_disconnect(self, mock_client_cls):
        """Проверка обработки отключения."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=True)
        service._on_connect(mock_client, None, None, 0)
        
        # Сбрасываем вызовы от подключения
        mock_client.reset_mock()
        
        service._on_disconnect(mock_client, None, 1)

        assert service._connected is False
        # При отключении publish_update_availability не вызывается из-за _is_ready() проверки
        # Проверяем только что статус подключения изменился
        mock_client.publish.assert_not_called()

    @patch("app.mqtt_service.mqtt.Client")
    def test_mqtt_service_with_username_password(self, mock_client_cls):
        """Тест создания MQTT сервиса с username и password."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        service = MqttService(
            host="localhost", 
            username="testuser", 
            password="testpass",
            discovery=True
        )
        
        # Проверяем, что username_pw_set был вызван
        mock_client.username_pw_set.assert_called_once_with("testuser", "testpass")

    @patch("app.mqtt_service.mqtt.Client")
    def test_mqtt_service_with_username_no_password(self, mock_client_cls):
        """Тест создания MQTT сервиса с username но без password."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        service = MqttService(
            host="localhost", 
            username="testuser", 
            password=None,
            discovery=True
        )
        
        # Проверяем, что username_pw_set был вызван с пустым паролем
        mock_client.username_pw_set.assert_called_once_with("testuser", "")

    @patch("app.mqtt_service.mqtt.Client")
    def test_on_message_clear_command(self, mock_client_cls):
        """Проверка обработки команды clear."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=True)
        service._on_connect(mock_client, None, None, 0)
        
        # Создаем mock сообщение
        msg = SimpleNamespace()
        msg.topic = COMMAND_TOPIC
        msg.payload = b"clear"
        
        # Сбрасываем вызовы от подключения
        mock_client.reset_mock()
        
        service._on_message(mock_client, None, msg)

        # Должна быть очистка retain сообщений и переиздание discovery
        calls = mock_client.publish.call_args_list
        # Ожидаем вызовы для очистки state топиков и переиздания discovery
        assert len(calls) >= 2

    @patch("app.mqtt_service.mqtt.Client")
    def test_start_connection_error(self, mock_client_cls):
        """Проверка обработки ошибки подключения при старте."""
        mock_client = MagicMock()
        mock_client.connect.side_effect = Exception("Connection failed")
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=True)
        
        # Не должно вызывать исключение
        service.start()
        
        mock_client.connect.assert_called_once()
        mock_client.loop_start.assert_not_called()

    @patch("app.mqtt_service.mqtt.Client")
    def test_publish_discovery_when_entity_inactive(self, mock_client_cls):
        """Проверка что discovery не публикуется для неактивной entity."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        service = MqttService(host="localhost", discovery=True)
        service._update_entity_active = False
        service._on_connect(mock_client, None, None, 0)

        # Проверяем что UPDATE_DISC_TOPIC не публикуется
        published_topics = [call.args[0] for call in mock_client.publish.call_args_list]
        assert UPDATE_DISC_TOPIC not in published_topics

    @patch("app.mqtt_service.mqtt.Client")
    def test_is_ready_method(self, mock_client_cls):
        """Проверка метода _is_ready."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Discovery отключен
        service = MqttService(host="localhost", discovery=False)
        assert service._is_ready() is False
        
        # Discovery включен, но не подключен
        service = MqttService(host="localhost", discovery=True)
        assert service._is_ready() is False
        
        # Discovery включен и подключен
        service._on_connect(mock_client, None, None, 0)
        assert service._is_ready() is True

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

    @patch("app.mqtt_service.mqtt.Client")
    def test_mqtt_service_without_username(self, mock_client_cls):
        """Тест создания MQTT сервиса без username."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        service = MqttService(host="localhost", discovery=True)
        
        # Проверяем, что username_pw_set НЕ был вызван
        mock_client.username_pw_set.assert_not_called()

    @patch("app.mqtt_service.mqtt.Client")
    def test_start_connection_error(self, mock_client_cls):
        """Тест обработки ошибки подключения при старте."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.connect.side_effect = Exception("Connection failed")
        
        service = MqttService("localhost", 1883, discovery=True)
        
        # Вызов start не должен вызывать исключение
        service.start()
        
        # Проверяем, что connect был вызван
        mock_client.connect.assert_called_once_with("localhost", 1883, 60)
        # loop_start не должен быть вызван из-за исключения
        mock_client.loop_start.assert_not_called()

    @patch("app.mqtt_service.mqtt.Client")
    def test_publish_error_handling(self, mock_client_cls):
        """Тест обработки ошибок публикации."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        # Мокируем неудачную публикацию
        mock_result = MagicMock()
        mock_result.rc = 1  # Ошибка
        mock_client.publish.return_value = mock_result
        
        service = MqttService("localhost", 1883, discovery=True)
        service._connected = True
        
        # Вызываем метод, который использует _publish
        service.publish_update_availability(True)
        
        # Проверяем, что publish был вызван
        mock_client.publish.assert_called()

    @patch("app.mqtt_service.mqtt.Client")
    def test_publish_state_error_handling(self, mock_client_cls):
        """Тест обработки ошибок публикации состояния."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        # Мокируем неудачную публикацию состояния
        mock_result = MagicMock()
        mock_result.rc = 1  # Ошибка
        mock_result.wait_for_publish.return_value = None
        mock_client.publish.return_value = mock_result
        
        service = MqttService("localhost", 1883, discovery=True)
        service._connected = True
        
        # Вызываем метод, который использует _publish_state
        service.publish_update_state("1.0.0", "2.0.0", False)
        
        # Проверяем, что publish был вызван
        mock_client.publish.assert_called()

    @patch("app.mqtt_service.mqtt.Client")
    def test_on_disconnect_with_exception(self, mock_client_cls):
        """Тест обработки исключения в _on_disconnect."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        service = MqttService("localhost", 1883, discovery=True)
        service._connected = True
        service._update_entity_active = True
        
        # Мокируем исключение в publish_update_availability
        with patch.object(service, 'publish_update_availability', side_effect=Exception("Publish error")):
            # Вызов не должен вызывать исключение
            service._on_disconnect(mock_client, None, 0)
        
        # Проверяем, что флаг подключения сброшен
        assert not service._connected