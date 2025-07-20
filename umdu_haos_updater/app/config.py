import json
import os
from pathlib import Path
from dataclasses import dataclass


CONFIG_PATH = Path("/data/options.json")


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

        self.check_interval = options.get("check_interval", 3600)
        self.auto_update = options.get("auto_update", False)
        self.notifications = options.get("notifications", True)
        self.debug = options.get("debug", False)

        mqtt_config = options.get("mqtt", {})
        self.mqtt_host = mqtt_config.get("host", "core-mosquitto")
        self.mqtt_port = mqtt_config.get("port", 1883)
        self.mqtt_username = mqtt_config.get("username", "")
        self.mqtt_password = mqtt_config.get("password", "")
        self.mqtt_enabled = bool(self.mqtt_username and self.mqtt_password)

        self._validate_config()

    def _validate_config(self):
        if not isinstance(self.check_interval, int) or self.check_interval < 60:
            self.check_interval = 3600

        if not isinstance(self.mqtt_port, int) or not (1 <= self.mqtt_port <= 65535):
            self.mqtt_port = 1883