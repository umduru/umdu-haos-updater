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

        mqtt_config = options.get("mqtt", {})
        self.mqtt_host = mqtt_config.get("host", "core-mosquitto")
        self.mqtt_port = mqtt_config.get("port", 1883)
        self.mqtt_username = mqtt_config.get("username", "")
        self.mqtt_password = mqtt_config.get("password", "")


        self._validate_config()

    def _validate_config(self):
        if not isinstance(self.mqtt_port, int) or not (1 <= self.mqtt_port <= 65535):
            self.mqtt_port = 1883

    def get_mqtt_params(self) -> tuple[str, int, str | None, str | None]:
        """Получает параметры MQTT из конфигурации или Supervisor API."""
        host, port, user, password = self.mqtt_host, self.mqtt_port or 1883, self.mqtt_username, self.mqtt_password

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
                    _LOGGER.debug("Получены параметры MQTT из Supervisor API")
                else:
                    host = host or "core-mosquitto"
            except Exception as exc:
                from .errors import NetworkError
                if isinstance(exc, NetworkError) and "not ready yet" in str(exc):
                    _LOGGER.debug("MQTT сервис еще не готов, будем ждать")
                else:
                    _LOGGER.warning("MQTT params via Supervisor API failed: %s", exc)
                host = host or "core-mosquitto"

        return host, port, user, password