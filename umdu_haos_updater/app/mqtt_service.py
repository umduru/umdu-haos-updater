from __future__ import annotations

import json
import logging
import threading
from typing import Callable, Optional
import time

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


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

    def start(self) -> None:
        """Запускает MQTT клиент."""
        logger.info("MQTT: connecting to %s:%s (user: %s)", self.host, self.port, self._client._username or "None")
        try:
            self._client.enable_logger(logger)
            self._client.connect(self.host, self.port, 60)
            self._client.loop_start()
            logger.debug("MQTT: клиент запущен, ожидание подключения...")
        except Exception as exc:
            logger.error("MQTT: connection error: %s", exc)
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
        
        self._publish_state(STATE_TOPIC, json.dumps(payload))

    def publish_update_availability(self, online: bool) -> None:
        """Публикует доступность update entity."""
        if not self._is_ready():
            return
        self._publish(UPDATE_AVAIL_TOPIC, "online" if online else "offline")

    def clear_retained_messages(self) -> None:
        """Очищает retain-сообщения для state топиков."""
        if not self.discovery_enabled:
            return
        
        topics = [STATE_TOPIC, UPDATE_AVAIL_TOPIC]
        
        for topic in topics:
            logger.info("MQTT: очистка retain-сообщения для %s", topic)
            self._client.publish(topic, "", retain=True)

    def deactivate_update_entity(self) -> None:
        """Деактивирует update entity."""
        if not self.discovery_enabled:
            return
        
        logger.info("MQTT: деактивация update entity")
        
        # Устанавливаем availability в offline (entity остается в HA, но показывается как недоступный)
        self._publish(UPDATE_AVAIL_TOPIC, "offline")
        
        self._update_entity_active = False
        logger.info("MQTT: update entity деактивирован")

    def _on_connect(self, client, userdata, flags, rc):  # noqa: D401
        success = rc == 0
        with self._lock:
            self._connected = success
        
        if not success:
            logger.warning("MQTT: failed to connect, code=%s", rc)
            return
        
        logger.info("MQTT: connected")
        time.sleep(0.5)
        client.subscribe(COMMAND_TOPIC)

        if self.discovery_enabled:
            self._publish_discovery()
            if self._update_entity_active:
                self.publish_update_availability(True)

    def _on_disconnect(self, client, userdata, rc):  # noqa: D401
        with self._lock:
            self._connected = False
        logger.warning("MQTT: disconnected code=%s", rc)
        
        if self.discovery_enabled and self._update_entity_active:
            try:
                self.publish_update_availability(False)
            except Exception as e:
                logger.debug("Не удалось отправить offline статус при отключении: %s", e)

    def _on_message(self, client, userdata, msg):  # noqa: D401
        topic = msg.topic
        payload = msg.payload.decode("utf-8").strip()
        logger.debug("MQTT: message %s %s", topic, payload)

        if topic == COMMAND_TOPIC:
            if payload == "install" and self.on_install_cmd:
                logger.info("MQTT: received install command")
                self.on_install_cmd()
            elif payload == "clear" and self._connected:
                logger.info("MQTT: received clear command - очистка retain-сообщений")
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

    def _publish(self, topic: str, payload: str):
        """Внутренний метод для публикации с retain=True."""
        logger.debug("MQTT publish (retained) %s %s", topic, payload[:120])
        if not self._connected:
            logger.warning("MQTT: попытка публикации при отсутствии подключения")
            return
        result = self._client.publish(topic, payload, retain=True)
        if result.rc != 0:
            logger.warning("MQTT: ошибка публикации в %s: %s", topic, result.rc)
        else:
            logger.debug("MQTT: успешная публикация в %s", topic)

    def _publish_state(self, topic: str, payload: str):
        """Внутренний метод для публикации state сообщений без retain."""
        logger.debug("MQTT publish (state) %s %s", topic, payload[:120])
        if not self._connected:
            logger.warning("MQTT: попытка публикации состояния при отсутствии подключения")
            return
        
        time.sleep(0.1)
        
        result = self._client.publish(topic, payload, retain=False, qos=1)
        if result.rc != 0:
            logger.warning("MQTT: ошибка публикации состояния в %s: %s", topic, result.rc)
        else:
            logger.debug("MQTT: успешная публикация состояния в %s", topic)
            result.wait_for_publish(timeout=2.0)