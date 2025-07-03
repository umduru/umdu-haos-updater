import json
import os
from pathlib import Path
from dataclasses import dataclass


CONFIG_PATH = Path("/data/options.json")


@dataclass
class AddonConfig:
    update_check_interval: int = 3600
    auto_update: bool = False
    notifications: bool = True
    mqtt_discovery: bool = True
    mqtt_host: str | None = None
    mqtt_port: int | None = None
    mqtt_user: str | None = None
    mqtt_password: str | None = None
    debug: bool = False

    @classmethod
    def load(cls) -> "AddonConfig":
        if not CONFIG_PATH.exists():
            # Запускаемся даже без options.json (для локального теста)
            return cls()

        with CONFIG_PATH.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        # Приводим числовые поля к int (в options.json могут быть строки)
        def _to_int(val, default):
            try:
                return int(val)
            except Exception:
                return default

        return cls(
            update_check_interval=_to_int(data.get("update_check_interval"), 3600),
            auto_update=data.get("auto_update", False),
            notifications=data.get("notifications", True),
            mqtt_discovery=data.get("mqtt_discovery", True),
            mqtt_host=data.get("mqtt_host") or None,
            mqtt_port=_to_int(data.get("mqtt_port"), None) if data.get("mqtt_port") else None,
            mqtt_user=data.get("mqtt_user") or None,
            mqtt_password=data.get("mqtt_password") or None,
            debug=data.get("debug", False),
        )

    def __post_init__(self):
        # Значения по умолчанию, совпадающие с конфигом, считаем «пустыми»
        if self.mqtt_host == "core-mosquitto":
            self.mqtt_host = None
        if self.mqtt_port == 1883:
            self.mqtt_port = None

        # --- Валидация ---
        if self.update_check_interval < 60:
            raise ValueError("update_check_interval must be ≥ 60 seconds")

        if self.mqtt_port is not None and not (1 <= self.mqtt_port <= 65535):
            raise ValueError("mqtt_port must be between 1 and 65535") 