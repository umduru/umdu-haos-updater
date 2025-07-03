from __future__ import annotations

"""Central orchestrator that coordinates checking, downloading and installing updates."""

import logging
from pathlib import Path
from typing import Callable

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
                # При ошибке используем installed как fallback
                self._latest_version = installed
                _LOGGER.debug("Orchestrator: fallback latest_version=%s", self._latest_version)

        _LOGGER.debug("Orchestrator: публикуем состояние installed=%s, latest=%s, in_progress=%s", 
                     installed, self._latest_version, self._in_progress)
        
        # Публикуем состояние с дополнительной проверкой
        try:
            # Генерируем уникальный ID для отслеживания
            import uuid
            msg_id = str(uuid.uuid4())[:8]
            
            self._mqtt_service.publish_update_state(installed, self._latest_version, self._in_progress)
            # Логируем точное содержимое для отладки
            import json
            payload = {
                "installed_version": installed,
                "latest_version": self._latest_version,
                "in_progress": self._in_progress
            }
            _LOGGER.info("Orchestrator [%s]: отправлено MQTT состояние: %s", msg_id, json.dumps(payload))
            
            # Небольшая задержка для обеспечения доставки
            import time
            time.sleep(0.5)  # Увеличиваем задержку для тестирования
            _LOGGER.info("Orchestrator [%s]: задержка завершена", msg_id)
                
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
        _LOGGER.info("RUN_INSTALL: начало установки, устанавливаем in_progress=True")
        
        # ЭКСПЕРИМЕНТАЛЬНЫЙ ФИКС: принудительно обновляем discovery перед установкой
        if self._mqtt_service:
            _LOGGER.info("RUN_INSTALL: принудительное обновление discovery конфигурации")
            self._mqtt_service._publish_discovery()
            import time
            time.sleep(1)  # Ждем обработки discovery
        
        self._in_progress = True
        self.publish_state(latest=latest_version)

        # Добавляем паузу для отображения прогресса в Home Assistant
        # Это необходимо, чтобы HA успел обработать in_progress=True и показать спиннер
        _LOGGER.info("RUN_INSTALL: пауза для отображения прогресса (3 сек)")
        import time
        time.sleep(3)

        _LOGGER.info("RUN_INSTALL: вызов install_if_ready")
        success = self.install_if_ready(bundle_path)

        _LOGGER.info("RUN_INSTALL: установка завершена, success=%s, устанавливаем in_progress=False", success)
        self._in_progress = False
        if self._mqtt_service:
            if success:
                _LOGGER.info("RUN_INSTALL: успех - деактивируем entity")
                self._mqtt_service.deactivate_update_entity()
            else:
                _LOGGER.info("RUN_INSTALL: ошибка - публикуем состояние")
                self.publish_state(latest=latest_version)

        if success:
            self._notifier.send(
                "UMDU HAOS Update Installed",
                reboot_required_message(latest_version),
            )

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    def _send_via_mosquitto_pub(self, installed: str, latest: str, in_progress: bool) -> None:
        """Экспериментальный метод отправки через mosquitto_pub для отладки."""
        import subprocess
        import json
        
        payload = {
            "installed_version": installed,
            "latest_version": latest,
            "in_progress": in_progress
        }
        
        try:
            # Пытаемся отправить через mosquitto_pub
            cmd = [
                "mosquitto_pub",
                "-h", "core-mosquitto",
                "-t", "umdu/haos_updater/state",
                "-m", json.dumps(payload),
                "-q", "1"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                _LOGGER.info("mosquitto_pub: успешная отправка")
            else:
                _LOGGER.warning("mosquitto_pub failed: %s", result.stderr)
        except Exception as e:
            _LOGGER.warning("mosquitto_pub exception: %s", e)

    @staticmethod
    def _touch_reboot_flag() -> None:
        Path("/data/reboot_required").touch(exist_ok=True) 