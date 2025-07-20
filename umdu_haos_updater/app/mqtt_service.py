from __future__ import annotations

import json
import logging
import threading
from typing import Callable, Optional
import time

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)


# MQTT Topics
COMMAND_TOPIC = "umdu/haos_updater/cmd"
STATE_TOPIC = "umdu/haos_updater/state"
UPDATE_AVAIL_TOPIC = "umdu/haos_updater/availability"

# Discovery Topics (только update entity)
UPDATE_DISC_TOPIC = "homeassistant/update/umdu_haos_k1/config"


class MqttService:
    """MQTT сервис для управления состоянием обновлений и команд."""

    def __init__(
        self,
        host: str,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        discovery: bool = True,
        on_install_cmd: Optional[Callable[[], None]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.discovery_enabled = discovery
        self.on_install_cmd = on_install_cmd

        self._client = mqtt.Client(client_id="umdu_haos_updater", clean_session=True)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        
        if username:
            self._client.username_pw_set(username, password or "")

        self._client.on_connect = self._on_connect  # type: ignore[assignment]
        self._client.on_message = self._on_message  # type: ignore[assignment]
        self._client.on_disconnect = self._on_disconnect  # type: ignore[assignment]

        self._lock = threading.Lock()
        self._connected = False
        self._update_entity_active: bool = True
        self._initial_versions: tuple[str, str] | None = None

    def start(self) -> None:
        """Запускает MQTT клиент."""
        _LOGGER.info("MQTT: connecting to %s:%s (user: %s)", self.host, self.port, self._client._username or "None")
        try:
            self._client.enable_logger(_LOGGER)
            self._client.connect(self.host, self.port, 60)
            self._client.loop_start()
            _LOGGER.debug("MQTT: клиент запущен, ожидание подключения...")
        except Exception as exc:
            _LOGGER.error("MQTT: connection error: %s", exc)
            raise

    def _is_ready(self) -> bool:
        """Проверяет готовность к публикации."""
        return self.discovery_enabled and self._connected

    def publish_update_state(self, installed: str, latest: str, in_progress: bool = False) -> None:
        """Публикует состояние обновления в едином формате."""
        if not self._is_ready():
            return
        payload = {
            "installed_version": installed,
            "latest_version": latest,
            "in_progress": in_progress
        }
        
        self._publish(STATE_TOPIC, json.dumps(payload), retain=False)

    def publish_update_availability(self, online: bool) -> None:
        """Публикует доступность update entity."""
        if not self._is_ready():
            return
        self._publish(UPDATE_AVAIL_TOPIC, "online" if online else "offline")
    
    def set_initial_versions(self, installed: str, latest: str) -> None:
        """Устанавливает начальные версии для публикации при подключении."""
        self._initial_versions = (installed, latest)
        _LOGGER.debug("MQTT: установлены начальные версии: installed=%s, latest=%s", installed, latest)

    def clear_retained_messages(self) -> None:
        """Очищает retain-сообщения для state топиков."""
        if not self.discovery_enabled:
            return
        
        for topic in [STATE_TOPIC, UPDATE_AVAIL_TOPIC]:
            _LOGGER.info("MQTT: очистка retain-сообщения для %s", topic)
            self._client.publish(topic, "", retain=True)

    def deactivate_update_entity(self) -> None:
        """Деактивирует update entity."""
        if not self.discovery_enabled:
            return
        
        _LOGGER.info("MQTT: деактивация update entity")
        
        # Устанавливаем availability в offline (entity остается в HA, но показывается как недоступный)
        self._publish(UPDATE_AVAIL_TOPIC, "offline")
        
        self._update_entity_active = False
        _LOGGER.info("MQTT: update entity деактивирован")

    def _on_connect(self, client, userdata, flags, rc):  # noqa: D401
        success = rc == 0
        with self._lock:
            self._connected = success
        
        if not success:
            _LOGGER.warning("MQTT: failed to connect, code=%s", rc)
            return
        
        _LOGGER.info("MQTT: connected")
        time.sleep(0.5)
        client.subscribe(COMMAND_TOPIC)

        if self.discovery_enabled:
            self._publish_discovery()

    def _on_disconnect(self, client, userdata, rc):  # noqa: D401
        with self._lock:
            self._connected = False
        _LOGGER.warning("MQTT: disconnected code=%s", rc)
        
        if self.discovery_enabled and self._update_entity_active:
            try:
                self.publish_update_availability(False)
            except Exception as e:
                _LOGGER.debug("Не удалось отправить offline статус при отключении: %s", e)

    def _on_message(self, client, userdata, msg):  # noqa: D401
        topic = msg.topic
        payload = msg.payload.decode("utf-8").strip()
        _LOGGER.debug("MQTT: message %s %s", topic, payload)

        if topic == COMMAND_TOPIC:
            if payload == "install" and self.on_install_cmd:
                _LOGGER.info("MQTT: received install command")
                self.on_install_cmd()
            elif payload == "clear" and self._connected:
                _LOGGER.info("MQTT: received clear command - очистка retain-сообщений")
                self.clear_retained_messages()
                self._publish_discovery()

    def _publish_discovery(self):
        """Публикует конфигурацию для Home Assistant discovery."""
        if self._update_entity_active:
            update_config = {
                "name": "Home Assistant OS for UMDU K1",
                "unique_id": "umdu_haos_k1_os",
                "state_topic": STATE_TOPIC,
                "command_topic": COMMAND_TOPIC,
                "payload_install": "install",
                "availability_topic": UPDATE_AVAIL_TOPIC,
                "device_class": "firmware",
                "platform": "update"
            }
            self._publish(UPDATE_DISC_TOPIC, json.dumps(update_config))
            
            # Публикуем availability
            self.publish_update_availability(True)
            
            # Если есть начальные версии, сразу публикуем состояние
            if self._initial_versions:
                installed, latest = self._initial_versions
                _LOGGER.info("MQTT: публикация начального состояния: installed=%s, latest=%s", installed, latest)
                self.publish_update_state(installed, latest, False)

    def _publish(self, topic: str, payload: str, retain: bool = True):
        """Внутренний метод для публикации сообщений."""
        msg_type = "retained" if retain else "state"
        _LOGGER.debug("MQTT publish (%s) %s %s", msg_type, topic, payload[:120])
        if not self._connected:
            _LOGGER.warning("MQTT: попытка публикации при отсутствии подключения")
            return
        
        if not retain:
            time.sleep(0.1)
        
        qos = 1 if not retain else 0
        result = self._client.publish(topic, payload, retain=retain, qos=qos)
        if result.rc != 0:
            _LOGGER.warning("MQTT: ошибка публикации в %s: %s", topic, result.rc)
        else:
            _LOGGER.debug("MQTT: успешная публикация в %s", topic)
            if not retain:
                result.wait_for_publish(timeout=2.0)