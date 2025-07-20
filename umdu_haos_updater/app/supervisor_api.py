from __future__ import annotations

import os
import logging
import requests

from .errors import SupervisorError, NetworkError

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"
TOKEN = os.getenv("SUPERVISOR_TOKEN")
if not TOKEN:
    _LOGGER.error(
        "SUPERVISOR_TOKEN не найден в переменных окружения — скрипт не сможет обращаться к API."
    )

def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _supervisor_request(endpoint: str, error_context: str) -> dict:
    """Общая функция для выполнения запросов к Supervisor API."""
    try:
        url = f"{SUPERVISOR_URL}{endpoint}"
        response = requests.get(url, headers=_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as e:
        if endpoint == "/services/mqtt" and e.response.status_code == 400:
            _LOGGER.debug("MQTT сервис еще не готов (400 Bad Request) - это нормально при старте системы")
            raise NetworkError("MQTT service not ready yet") from e
        else:
            _LOGGER.error("HTTP ошибка %s: %s", error_context, e)
            raise NetworkError(f"Failed to {error_context}") from e
    except requests.RequestException as e:
        _LOGGER.error("Ошибка %s: %s", error_context, e)
        raise NetworkError(f"Failed to {error_context}") from e
    except Exception as e:
        _LOGGER.error("Неожиданная ошибка %s: %s", error_context, e)
        raise SupervisorError(f"Unexpected error {error_context}") from e


def get_current_haos_version() -> str | None:
    """Получает текущую версию HAOS через Supervisor API."""
    data = _supervisor_request("/os/info", "получения версии HAOS")
    return data.get("data", {}).get("version")


def get_mqtt_service() -> dict | None:
    """Получает информацию о MQTT сервисе через Supervisor API."""
    data = _supervisor_request("/services/mqtt", "получения информации о MQTT")
    return data.get("data")