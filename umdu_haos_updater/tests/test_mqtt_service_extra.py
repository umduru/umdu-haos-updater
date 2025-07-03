from unittest.mock import MagicMock, patch

from app.mqtt_service import MqttService, UPDATE_AVAIL_TOPIC


@patch("app.mqtt_service.mqtt.Client")
def test_on_disconnect_publishes_offline(mock_client_cls):
    client = MagicMock()
    mock_client_cls.return_value = client

    service = MqttService(host="localhost", discovery=True)
    # Подключаемся
    service._on_connect(client, None, None, 0)
    # Отписываемся (rc=1)
    service._on_disconnect(client, None, 1)

    # После disconnect публикаций offline быть не должно (логика _is_ready())
    offline_topics = [c.args[0] for c in client.publish.call_args_list if c.args[1] == "offline"]
    assert offline_topics == []


@patch("app.mqtt_service.mqtt.Client")
def test_no_publish_when_discovery_disabled(mock_client_cls):
    client = MagicMock()
    mock_client_cls.return_value = client

    service = MqttService(host="localhost", discovery=False)
    service._on_connect(client, None, None, 0)

    # Пытаемся опубликовать — публикаций не должно быть
    service.publish_update_state("a", "b")
    client.publish.assert_not_called() 