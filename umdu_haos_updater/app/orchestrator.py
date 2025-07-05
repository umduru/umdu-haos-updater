from __future__ import annotations

"""Central orchestrator that coordinates checking, downloading and installing updates."""

import logging
from pathlib import Path
from typing import Callable
from threading import Lock

from .config import AddonConfig
from .updater import check_for_update_and_download, fetch_available_update
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
        self._mqtt_service: MqttService | None = None
        self._in_progress: bool = False
        self._lock = Lock()  # Блокировка для _in_progress
        self._latest_version: str | None = None  # Кэш последней известной версии
        # Когда true — цикл auto_update временно приостанавливается, т.к.
        # ручная установка already выполняется в другом потоке.
        self.manual_install_active: bool = False

    def set_mqtt_service(self, mqtt_service: MqttService | None) -> None:
        """Устанавливает MQTT сервис для публикации состояния."""
        self._mqtt_service = mqtt_service

    def publish_state(self, installed: str | None = None, latest: str | None = None) -> None:
        """Публикует текущее состояние в MQTT."""
        if not self._mqtt_service:
            return

        if installed is None:
            installed = get_current_haos_version() or "unknown"
        
        # Если версия явно передана - обновляем кэш
        if latest is not None:
            self._latest_version = latest
            _LOGGER.debug("Orchestrator: установлена latest_version=%s", latest)
        # Если не передана, но есть в кэше - используем кэш
        elif self._latest_version is not None:
            _LOGGER.debug("Orchestrator: используем кэш latest_version=%s", self._latest_version)
        # Только если кэш пуст - пытаемся получить новую версию
        else:
            try:
                avail = fetch_available_update()
                self._latest_version = avail.version
                _LOGGER.debug("Orchestrator: получена latest_version=%s", self._latest_version)
            except Exception:
                # При ошибке НЕ меняем _latest_version, используем кэш или None
                _LOGGER.warning("Orchestrator: не удалось получить latest_version, используется кэш")
                if self._latest_version is None:
                    # Если кэш пуст - используем installed как fallback
                    self._latest_version = installed
                    _LOGGER.debug("Orchestrator: fallback latest_version=%s", self._latest_version)

        with self._lock:
            in_progress = self._in_progress
        _LOGGER.debug("Orchestrator: публикуем состояние installed=%s, latest=%s, in_progress=%s", 
                     installed, self._latest_version, in_progress)
        
        # Публикуем состояние с дополнительной проверкой
        try:
            self._mqtt_service.publish_update_state(installed, self._latest_version, in_progress)
            # Небольшая задержка для обеспечения доставки
            import time
            time.sleep(0.2)
        except Exception as e:
            _LOGGER.warning("Ошибка публикации состояния MQTT: %s", e)

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
        with self._lock:
            if self._in_progress:
                _LOGGER.debug("in_progress=True – пропуск auto_cycle_once")
                return

        # Получаем информацию об обновлении
        try:
            avail = fetch_available_update()
            self._latest_version = avail.version
            _LOGGER.debug("Orchestrator: auto_cycle_once получил latest_version=%s", self._latest_version)
        except Exception:
            # При ошибке используем кэш или installed
            if not self._latest_version:
                self._latest_version = get_current_haos_version() or "unknown"
            _LOGGER.debug("Orchestrator: auto_cycle_once использует кэш latest_version=%s", self._latest_version)

        # Проверяем и скачиваем обновление
        bundle_path = self.check_and_download()
        if bundle_path and self._cfg.auto_update:
            _LOGGER.info("Auto-installing %s", bundle_path)
            self.run_install(bundle_path)
        else:
            # Публикуем текущее состояние с найденной версией
            _LOGGER.debug("Orchestrator: auto_cycle_once публикует состояние")
            self.publish_state()

    # ---------------------------------------------------------------------
    # Unified install flow
    # ---------------------------------------------------------------------
    def run_install(
        self,
        bundle_path: Path,
        latest_version: str | None = None,
    ) -> None:
        """Запускает RAUC-установку и публикует MQTT-индикатор."""
        with self._lock:
            if self._in_progress:
                _LOGGER.warning("Установка уже запущена, пропуск нового запроса")
                return
            self._in_progress = True

        self.publish_state(latest=latest_version)

        success = self.install_if_ready(bundle_path)

        with self._lock:
            self._in_progress = False
            
        if self._mqtt_service:
            if success:
                self._mqtt_service.deactivate_update_entity()
            else:
                self.publish_state(latest=latest_version)

        if success:
            self._notifier.send(
                "UMDU HAOS Update Installed",
                reboot_required_message(latest_version),
            )

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def _touch_reboot_flag() -> None:
        Path("/data/reboot_required").touch(exist_ok=True) 