"""Extra tests for mqtt_service validations."""

from __future__ import annotations

import pytest  # type: ignore
from app.mqtt_service import MqttService


def test_mqtt_service_port_coercion():
    svc = MqttService(host="localhost", port="1883", discovery=False)
    assert svc.port == 1883


@pytest.mark.parametrize("bad_port", ["not-int", -1, 70000, None])
def test_mqtt_service_port_invalid(bad_port):
    with pytest.raises(ValueError):
        MqttService(host="localhost", port=bad_port, discovery=False)