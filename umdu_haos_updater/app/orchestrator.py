from __future__ import annotations

"""Central orchestrator that coordinates checking, downloading and installing updates."""

import logging
from pathlib import Path
from typing import Callable

from .config import AddonConfig
from .updater import check_for_update_and_download
from .rauc_installer import install_bundle, InstallError
from .notification_service import NotificationService, reboot_required_message
from .supervisor_api import get_current_haos_version
from .mqtt_service import MqttService

_LOGGER = logging.getLogger(__name__)


class UpdateOrchestrator:
    """Encapsulates the update flow so that UI (MQTT / CLI) can just call high-level methods."""

    def __init__(self, cfg: AddonConfig, notifier: NotificationService | None = None) -> None:
        self._cfg = cfg
        self._notifier = notifier or NotificationService(enabled=cfg.notifications)
        # Когда true — цикл auto_update временно приостанавливается, т.к.
        # ручная установка already выполняется в другом потоке.
        self.manual_install_active: bool = False

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def check_and_download(self) -> Path | None:
        """Checks for update and (optionally) downloads it according to config."""
        return check_for_update_and_download(auto_download=self._cfg.auto_update)

    def install_if_ready(self, bundle_path: Path) -> bool:
        """Calls RAUC installer; returns success flag."""
        try:
            success = install_bundle(bundle_path)
        except InstallError as exc:
            _LOGGER.error("RAUC install failed: %s", exc)
            # Уведомляем пользователя, если возможно
            self._notifier.send(
                "UMDU HAOS Update – ошибка установки",
                f"❌ Не удалось установить обновление: {exc}",
            )
            return False

        if success:
            # Успешно – помечаем, что требуется перезагрузка
            self._touch_reboot_flag()
        return success

    def auto_cycle_once(self) -> None:
        """Single iteration of auto-update loop (non-blocking)."""
        if self.manual_install_active:
            _LOGGER.debug("manual_install_active=True – пропуск auto_cycle_once")
            return

        bundle_path = self.check_and_download()
        if bundle_path and self._cfg.auto_update:
            _LOGGER.info("Auto-installing %s", bundle_path)
            self.run_install(bundle_path)

    # ---------------------------------------------------------------------
    # Unified install flow
    # ---------------------------------------------------------------------

    def run_install(
        self,
        bundle_path: Path,
        mqtt_service: MqttService | None = None,
        latest_version: str | None = None,
    ) -> None:
        """Запускает RAUC-установку и публикует MQTT-индикатор.

        Используется и в авто-режиме, и в ручном install.
        """

        installed_version = get_current_haos_version() or "unknown"
        target_version = latest_version or installed_version

        if mqtt_service:
            mqtt_service.publish_update_state(installed_version, target_version, in_progress=True)

        success = self.install_if_ready(bundle_path)

        if mqtt_service:
            mqtt_service.publish_update_state(installed_version, target_version, in_progress=False)
            if success:
                mqtt_service.deactivate_update_entity()

        if success:
            self._notifier.send(
                "UMDU HAOS Update Installed",
                reboot_required_message(target_version),
            )

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def _touch_reboot_flag() -> None:
        Path("/data/reboot_required").touch(exist_ok=True) 