from __future__ import annotations

import os
import logging
import requests

from .errors import SupervisorError, NetworkError

logger = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"
TOKEN = os.getenv("SUPERVISOR_TOKEN")
if not TOKEN:
    logger.error(
        "SUPERVISOR_TOKEN не найден в переменных окружения — скрипт не сможет обращаться к API."
    )

def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def get_current_haos_version() -> str:
    """Возвращает установленную версию HAOS или бросает SupervisorError."""
    try:
        r = requests.get(f"{SUPERVISOR_URL}/os/info", headers=_headers(), timeout=5)
        r.raise_for_status()
        return r.json()["data"]["version"]
    except requests.RequestException as exc:
        raise NetworkError("/os/info network error") from exc
    except Exception as exc:  # noqa: BLE001
        raise SupervisorError("Invalid response from /os/info") from exc


def get_mqtt_service() -> dict[str, str | None]:
    """Возвращает словарь host/port/username/password или бросает SupervisorError."""
    try:
        r = requests.get(f"{SUPERVISOR_URL}/services/mqtt", headers=_headers(), timeout=5)
        r.raise_for_status()
        data = r.json().get("data", {})
        return {
            "host": data.get("host"),
            "port": data.get("port"),
            "username": data.get("username"),
            "password": data.get("password"),
        }
    except requests.RequestException as exc:
        raise NetworkError("/services/mqtt network error") from exc
    except Exception as exc:  # noqa: BLE001
        raise SupervisorError("Invalid response from /services/mqtt") from exc 