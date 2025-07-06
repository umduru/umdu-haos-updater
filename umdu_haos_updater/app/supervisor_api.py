from __future__ import annotations

import os
import logging
import requests
import aiohttp
import asyncio

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


# -----------------------------------------------------------------------------
# Async versions using aiohttp
# -----------------------------------------------------------------------------


async def _async_headers() -> dict[str, str]:
    # Same header factory but kept async in case future async-derived tokens needed
    return {"Authorization": f"Bearer {TOKEN}"}


async def _async_get_json(endpoint: str, timeout: float = 5.0) -> dict:
    """Internal helper that performs GET request to Supervisor API asynchronously."""
    headers = await _async_headers()
    url = f"{SUPERVISOR_URL}{endpoint}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as exc:
            raise NetworkError(f"{endpoint} network error") from exc
        except Exception as exc:  # noqa: BLE001
            raise SupervisorError(f"Invalid response from {endpoint}") from exc


async def async_get_current_haos_version() -> str:
    """Asynchronous variant of :func:`get_current_haos_version`."""
    data = await _async_get_json("/os/info")
    return data["data"]["version"]


async def async_get_mqtt_service() -> dict[str, str | None]:
    """Asynchronous variant of :func:`get_mqtt_service`."""
    data = await _async_get_json("/services/mqtt")
    return {
        "host": data.get("host"),
        "port": data.get("port"),
        "username": data.get("username"),
        "password": data.get("password"),
    } 