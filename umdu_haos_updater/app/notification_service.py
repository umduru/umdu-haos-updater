from __future__ import annotations

"""Сервис отправки уведомлений в Home Assistant (через Supervisor API).
Выделен в отдельный модуль, чтобы изолировать работу с HTTP и упростить тестирование.
"""

import logging
from typing import Any

import requests

from .supervisor_api import SUPERVISOR_URL, TOKEN

_LOGGER = logging.getLogger(__name__)


class NotificationService:
    """Сервис для отправки уведомлений в Home Assistant."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def send_notification(self, title: str, message: str) -> bool:
        """Отправляет уведомление в Home Assistant."""
        if not self.enabled:
            _LOGGER.debug("Уведомления отключены")
            return False

        try:
            url = f"{SUPERVISOR_URL}/core/api/services/persistent_notification/create"
            headers = {"Authorization": f"Bearer {TOKEN}"}
            data = {"title": title, "message": message}

            response = requests.post(url, json=data, headers=headers, timeout=10)
            response.raise_for_status()
            _LOGGER.info("Уведомление отправлено: %s", title)
            return True
        except Exception as e:
            _LOGGER.error("Ошибка отправки уведомления: %s", e)
            return False


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def reboot_required_message(version: str) -> str:
    """Формирует сообщение о необходимости перезагрузки."""
    return (
        f"Обновление HAOS до версии {version} установлено успешно. "
        "Для завершения обновления требуется перезагрузка системы."
    )