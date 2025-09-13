from __future__ import annotations

import os
import logging
import time
import requests

from .errors import SupervisorError

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"
TOKEN = os.getenv("SUPERVISOR_TOKEN")

def _headers() -> dict[str, str]:
    """Build auth headers for Supervisor API.

    Avoid emitting an invalid "Bearer None" header when the token is absent.
    In production code paths, the main entrypoint validates the token early.
    """
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def _supervisor_request(endpoint: str, error_context: str) -> dict:
    """Общая функция для выполнения запросов к Supervisor API с телеметрией.

    Логируем latency и, при ошибках, статус/Retry-After для упрощения диагностики
    флапающих состояний и rate-limit.
    """
    url = f"{SUPERVISOR_URL}{endpoint}"
    start = time.monotonic()
    try:
        response = requests.get(url, headers=_headers(), timeout=10)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        _LOGGER.debug("Supervisor API GET %s status=%s elapsed_ms=%d", endpoint, getattr(response, "status_code", "?"), elapsed_ms)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        status = getattr(resp, "status_code", None)
        retry_after = None
        try:
            retry_after = resp.headers.get("Retry-After") if resp and getattr(resp, "headers", None) else None
        except Exception:
            retry_after = None
        if endpoint == "/services/mqtt" and status == 400:
            _LOGGER.debug("MQTT сервис ещё не готов (400 Bad Request), context=%s", error_context)
            raise SupervisorError("MQTT service not ready yet") from e
        # Отдельно подсвечиваем rate-limit
        if status == 429:
            _LOGGER.warning("Supervisor API rate-limited during %s: status=429 retry_after=%s", error_context, retry_after)
        else:
            _LOGGER.exception("HTTP ошибка Supervisor API при %s (status=%s, retry_after=%s)", error_context, status, retry_after)
        raise SupervisorError(f"HTTP error {error_context}") from e
    except requests.RequestException as e:
        # Детализируем тип ошибки (timeout/DNS/conn)
        kind = type(e).__name__
        _LOGGER.exception("Ошибка запроса к Supervisor API при %s (%s)", error_context, kind)
        raise SupervisorError(f"Request error {error_context}") from e
    except Exception as e:
        _LOGGER.exception("Неожиданная ошибка %s", error_context)
        raise SupervisorError(f"Unexpected error {error_context}") from e


def get_current_haos_version() -> str | None:
    """Получает текущую версию HAOS через Supervisor API."""
    data = _supervisor_request("/os/info", "получения версии HAOS")
    return data.get("data", {}).get("version")


def get_mqtt_service() -> dict | None:
    """Получает информацию о MQTT сервисе через Supervisor API."""
    data = _supervisor_request("/services/mqtt", "получения информации о MQTT")
    return data.get("data")
