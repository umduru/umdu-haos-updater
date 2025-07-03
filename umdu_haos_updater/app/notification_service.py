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
    """Отправка persistent_notification.* в Home Assistant."""

    def __init__(self, enabled: bool = True, timeout: float = 5.0) -> None:
        self._enabled = enabled
        self._timeout = timeout

    @property
    def enabled(self) -> bool:  # noqa: D401
        return self._enabled

    def send(self, title: str, message: str) -> None:  # noqa: D401
        """Отправляет уведомление; молча игнорирует ошибки сети."""
        if not self._enabled:
            _LOGGER.debug("Notifications disabled: %s — %s", title, message)
            return

        payload: dict[str, Any] = {"title": title, "message": message}
        try:
            r = requests.post(
                f"{SUPERVISOR_URL}/core/api/services/persistent_notification/create",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json=payload,
                timeout=self._timeout,
            )
            r.raise_for_status()
            _LOGGER.info("HA notification sent: %s", title)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Failed to send HA notification: %s", exc)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def reboot_required_message(version: str | None = None) -> str:
    """Возвращает текст уведомления о необходимости перезагрузки.

    Если передана *version*, она добавляется к сообщению.
    """

    header = (
        f"✅ Обновление до версии {version} установлено успешно!"
        if version
        else "✅ Обновление установлено успешно!"
    )

    return (
        f"{header}\n"
        "🔄 Требуется перезагрузка системы для применения изменений.\n\n"
        "**Для перезагрузки системы:**\n"
        "1. Перейдите в **Режим разработчика** (Developer Tools)\n"
        "2. Выберите **Перезапустить** (Restart)\n"
        "3. Нажмите **Дополнительные опции** (Advanced Options)\n"
        "4. Нажмите **Перезапустить систему** (Restart System)"
    ) 