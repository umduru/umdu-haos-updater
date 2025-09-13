import json
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


class AddonConfig:

    def __init__(self, options_path: Path = Path("/data/options.json")):
        self.options_path = options_path
        self._load_config()

    def _load_config(self):
        try:
            with open(self.options_path, encoding="utf-8") as f:
                options = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            options = {}

        # Фиксированный интервал проверки обновлений - 24 часа
        self.check_interval = 86400
        self.auto_update = options.get("auto_update", False)
        self.notifications = options.get("notifications", True)
        self.debug = options.get("debug", False)
        self.dev_channel = options.get("dev_channel", False)

        # Поддерживаем два формата конфигурации MQTT:
        # 1) Верхнеуровневые ключи: mqtt_host/mqtt_port/mqtt_user/mqtt_password (актуально для config.yaml)
        # 2) Вложенный объект mqtt: {host, port, username, password} (обратная совместимость)
        mqtt_config = options.get("mqtt", {})

        self.mqtt_host = (
            options.get("mqtt_host")
            or mqtt_config.get("host")
            or "core-mosquitto"
        )

        port_opt = options.get("mqtt_port") or mqtt_config.get("port")
        try:
            self.mqtt_port = int(port_opt) if port_opt is not None else 1883
        except Exception:
            self.mqtt_port = 1883

        self.mqtt_username = (
            options.get("mqtt_user")
            or mqtt_config.get("username")
            or ""
        )
        self.mqtt_password = (
            options.get("mqtt_password")
            or mqtt_config.get("password")
            or ""
        )


        self._validate_config()

    def _validate_config(self):
        if not isinstance(self.mqtt_port, int) or not (1 <= self.mqtt_port <= 65535):
            self.mqtt_port = 1883

    def get_mqtt_params(self) -> tuple[str | None, int, str | None, str | None, bool]:
        """Получает параметры MQTT из конфигурации или Supervisor API.

        Возвращает кортеж (host, port, username, password, use_tls).
        Если авторизация недоступна, host может быть None (работаем без MQTT).
        """
        host, port, user, password, use_tls = (
            self.mqtt_host,
            self.mqtt_port or 1883,
            self.mqtt_username,
            self.mqtt_password,
            False,
        )

        # Fallback к Supervisor API если нет учетных данных или используется дефолтный хост
        if not user or not password or host == "core-mosquitto":
            try:
                from .supervisor_api import get_mqtt_service
                sup = get_mqtt_service()
                if sup and sup.get("host"):
                    host = sup["host"]
                    port = sup.get("port") or port
                    user = self.mqtt_username or sup.get("username")
                    password = self.mqtt_password or sup.get("password")
                    use_tls = bool(sup.get("ssl") or False)
                    _LOGGER.debug("Получены параметры MQTT из Supervisor API")
                else:
                    host = host or "core-mosquitto"
            except Exception as exc:
                from .errors import SupervisorError
                if isinstance(exc, SupervisorError) and "not ready yet" in str(exc):
                    _LOGGER.debug("MQTT сервис еще не готов, будем ждать")
                else:
                    _LOGGER.warning("MQTT params via Supervisor API failed: %s", exc)
                host = host or "core-mosquitto"
        # Если авторизация отсутствует — не подключаемся анонимно
        if not user or not password:
            _LOGGER.warning("MQTT credentials отсутствуют — работа без MQTT")
            return None, port, None, None, False

        return host, port, user, password, use_tls
