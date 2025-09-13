from __future__ import annotations

import json
import logging
import threading
from typing import Callable, Optional
from pathlib import Path
from functools import wraps

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)


def requires_discovery(func):
    """Декоратор для методов, требующих включенного discovery."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not self.discovery_enabled:
            return
        return func(self, *args, **kwargs)
    return wrapper


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
        use_tls: bool = False,
        discovery: bool = True,
        on_install_cmd: Optional[Callable[[], None]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.discovery_enabled = discovery
        self.on_install_cmd = on_install_cmd
        self._log_username = username or "None"
        self._use_tls = use_tls

        # paho-mqtt 2.x: параметр clean_session удалён из конструктора
        self._client = mqtt.Client(
            client_id="umdu_haos_updater",
            protocol=mqtt.MQTTv311,
        )
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        
        # Настраиваем LWT для корректной пометки offline при внезапном разрыве
        if self.discovery_enabled:
            # Гарантируем доставку LWT offline с QoS=1 при аварийном разрыве
            self._client.will_set(UPDATE_AVAIL_TOPIC, "offline", qos=1, retain=True)
        
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
        _LOGGER.info("MQTT: connecting to %s:%s (user: %s)", self.host, self.port, self._log_username)
        try:
            self._client.enable_logger(_LOGGER)
            if self._use_tls:
                # Используем системные корни (ca-certificates внутри контейнера)
                try:
                    self._client.tls_set()
                except Exception as e:
                    _LOGGER.warning("MQTT: не удалось включить TLS: %s", e)
            self._client.connect(self.host, self.port, 60)
            self._client.loop_start()
            _LOGGER.debug("MQTT: клиент запущен, ожидание подключения...")
        except Exception as exc:
            _LOGGER.error("MQTT: connection error: %s", exc)
            raise

    def is_ready(self) -> bool:
        """Проверяет готовность к публикации (публичный метод)."""
        return self.discovery_enabled and self._connected

    def publish_update_state(self, installed: str, latest: str, in_progress: bool = False) -> None:
        """Публикует состояние обновления в едином формате."""
        if not self.is_ready():
            return
        payload = {
            "installed_version": installed,
            "latest_version": latest,
            "in_progress": in_progress
        }
        
        self._publish(STATE_TOPIC, json.dumps(payload), retain=False)

    def publish_update_availability(self, online: bool) -> None:
        """Публикует доступность update entity."""
        if not self.is_ready():
            return
        self._publish(UPDATE_AVAIL_TOPIC, "online" if online else "offline")
    
    def set_initial_versions(self, installed: str, latest: str) -> None:
        """Устанавливает начальные версии для публикации при подключении."""
        self._initial_versions = (installed, latest)
        _LOGGER.debug("MQTT: установлены начальные версии: installed=%s, latest=%s", installed, latest)

    @requires_discovery
    def clear_retained_messages(self) -> None:
        """Очищает retain-сообщения для state топиков."""
        # Также очищаем discovery-конфиг, чтобы HA пере-создал entity без устаревшей привязки к device
        for topic in [STATE_TOPIC, UPDATE_AVAIL_TOPIC, UPDATE_DISC_TOPIC]:
            _LOGGER.info("MQTT: очистка retain-сообщения для %s", topic)
            self._client.publish(topic, "", retain=True, qos=1)

    @requires_discovery
    def deactivate_update_entity(self) -> None:
        """Деактивирует update entity."""
        _LOGGER.info("MQTT: деактивация update entity")
        
        # Устанавливаем availability в offline (entity остается в HA, но показывается как недоступный)
        self._publish(UPDATE_AVAIL_TOPIC, "offline")
        
        self._update_entity_active = False
        _LOGGER.info("MQTT: update entity деактивирован")

    def _on_connect(self, client, userdata, flags, rc, properties=None):  # noqa: D401
        # paho 1.x/2.x: rc может быть int либо enum/объект с кодом
        try:
            code = int(rc)
        except Exception:
            code = 0 if rc == 0 else 1
        success = code == 0
        with self._lock:
            self._connected = success
        
        if not success:
            _LOGGER.warning("MQTT: failed to connect, code=%s", code)
            return
        
        _LOGGER.info("MQTT: connected")
        client.subscribe(COMMAND_TOPIC, qos=1)

        if self.discovery_enabled:
            # Однократная миграция: очистка старого discovery-конфига с device-блоком
            self._maybe_migrate_discovery()
            self._publish_discovery()

    def _maybe_migrate_discovery(self) -> None:
        """Один раз очищает старый discovery-конфиг (без трогания state/availability).

        Нужна для отвязки entity от устройства у существующих установок.
        Выполняется только один раз, помечается файлом-маркером в /data.
        """
        marker = Path("/data/.umdu_haos_updater_discovery_migrated_v1")
        if marker.exists():
            return
        try:
            _LOGGER.info("MQTT: миграция discovery — очистка retained конфига")
            # Публикуем пустой retained payload только в discovery-топик
            self._client.publish(UPDATE_DISC_TOPIC, "", retain=True, qos=1)
            try:
                marker.touch(exist_ok=True)
            except Exception:
                # Отсутствие возможности записать маркер не критично
                pass
        except Exception as e:
            _LOGGER.debug("MQTT: ошибка миграции discovery: %s", e)

    def _on_disconnect(self, client, userdata, rc, properties=None):  # noqa: D401
        with self._lock:
            self._connected = False
        # rc==0 означает штатное отключение
        try:
            code = int(rc)
        except Exception:
            code = 1
        level = logging.INFO if code == 0 else logging.WARNING
        _LOGGER.log(level, "MQTT: disconnected code=%s", code)
        
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
            self._handle_command(payload)

    def _handle_command(self, payload: str):
        """Обрабатывает команды, полученные через MQTT."""
        commands = {
            "install": self._handle_install,
            "clear": self._handle_clear
        }
        handler = commands.get(payload)
        if handler:
            handler()

    def _handle_install(self):
        if self.on_install_cmd:
            _LOGGER.info("MQTT: received install command")
            self.on_install_cmd()

    def _handle_clear(self):
        if self._connected:
            _LOGGER.info("MQTT: received clear command - очистка retain-сообщений")
            self.clear_retained_messages()
            self._publish_discovery()

    def _publish_discovery(self):
        """Публикует конфигурацию для Home Assistant discovery."""
        if self._update_entity_active:
            update_config = {
                "name": "Home Assistant OS for umdu k1",
                "unique_id": "umdu_haos_k1_os",
                "state_topic": STATE_TOPIC,
                "installed_version_template": "{{ value_json.installed_version }}",
                "latest_version_template": "{{ value_json.latest_version }}",
                "command_topic": COMMAND_TOPIC,
                "payload_install": "install",
                "availability_topic": UPDATE_AVAIL_TOPIC,
                "device_class": "firmware",
            }
            self._publish(UPDATE_DISC_TOPIC, json.dumps(update_config))
            
            # Публикуем availability
            self.publish_update_availability(True)
            
            # Если есть начальные версии, сразу публикуем состояние
            if self._initial_versions:
                installed, latest = self._initial_versions
                _LOGGER.info("MQTT: публикация начального состояния: installed=%s, latest=%s", installed, latest)
                # Публикуем начальное состояние с retain=True, чтобы HA не терял его при гонке подписки
                payload = {
                    "installed_version": installed,
                    "latest_version": latest,
                    "in_progress": False,
                }
                self._publish(STATE_TOPIC, json.dumps(payload), retain=True)

    def _publish(self, topic: str, payload: str, retain: bool = True):
        """Внутренний метод для публикации сообщений."""
        msg_type = "retained" if retain else "state"
        _LOGGER.debug("MQTT publish (%s) %s %s", msg_type, topic, payload[:120])
        if not self._connected:
            # Ожидаемое состояние при реконнекте — не шумим WARN
            _LOGGER.debug("MQTT: пропуск публикации — нет подключения")
            return
        
        # Используем QoS=1 для всех сообщений (включая retained) ради надежной доставки
        result = self._client.publish(topic, payload, retain=retain, qos=1)
        if result.rc != 0:
            _LOGGER.warning("MQTT: ошибка публикации в %s: %s", topic, result.rc)
        else:
            _LOGGER.debug("MQTT: успешная публикация в %s", topic)

    def stop(self) -> None:
        """Останавливает MQTT-клиент и сетевой цикл."""
        try:
            if self._connected and self.discovery_enabled and self._update_entity_active:
                try:
                    info = self._client.publish(UPDATE_AVAIL_TOPIC, "offline", retain=True, qos=1)
                    info.wait_for_publish(timeout=2)
                except Exception:
                    pass
            # Не публикуем offline из колбэков, просто закрываем соединение
            self._client.disconnect()
        except Exception as e:
            _LOGGER.debug("MQTT: ошибка при disconnect(): %s", e)
        try:
            self._client.loop_stop()
        except Exception as e:
            _LOGGER.debug("MQTT: ошибка при loop_stop(): %s", e)
