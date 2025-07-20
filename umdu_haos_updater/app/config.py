import json
from pathlib import Path


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

        mqtt_config = options.get("mqtt", {})
        self.mqtt_host = mqtt_config.get("host", "core-mosquitto")
        self.mqtt_port = mqtt_config.get("port", 1883)
        self.mqtt_username = mqtt_config.get("username", "")
        self.mqtt_password = mqtt_config.get("password", "")


        self._validate_config()

    def _validate_config(self):
        if not isinstance(self.mqtt_port, int) or not (1 <= self.mqtt_port <= 65535):
            self.mqtt_port = 1883