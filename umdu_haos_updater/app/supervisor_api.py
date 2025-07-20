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


def get_current_haos_version() -> str | None:
    """Получает текущую версию HAOS через Supervisor API."""
    try:
        url = f"{SUPERVISOR_URL}/os/info"
        response = requests.get(url, headers=_headers(), timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("data", {}).get("version")
    except requests.RequestException as e:
        logger.error("Ошибка получения версии HAOS: %s", e)
        raise NetworkError("Failed to get HAOS version") from e
    except Exception as e:
        logger.error("Неожиданная ошибка при получении версии HAOS: %s", e)
        raise SupervisorError("Unexpected error getting HAOS version") from e


def get_mqtt_service() -> dict | None:
    """Получает информацию о MQTT сервисе через Supervisor API."""
    try:
        url = f"{SUPERVISOR_URL}/services/mqtt"
        response = requests.get(url, headers=_headers(), timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("data")
    except requests.HTTPError as e:
        if e.response.status_code == 400:
            logger.debug("MQTT сервис еще не готов (400 Bad Request) - это нормально при старте системы")
            raise NetworkError("MQTT service not ready yet") from e
        else:
            logger.error("HTTP ошибка получения информации о MQTT: %s", e)
            raise NetworkError("Failed to get MQTT service info") from e
    except requests.RequestException as e:
        logger.error("Ошибка получения информации о MQTT: %s", e)
        raise NetworkError("Failed to get MQTT service info") from e
    except Exception as e:
        logger.error("Неожиданная ошибка при получении информации о MQTT: %s", e)
        raise SupervisorError("Unexpected error getting MQTT service info") from e