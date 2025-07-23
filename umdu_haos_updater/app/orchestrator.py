from __future__ import annotations

import logging
from pathlib import Path

from .config import AddonConfig
from .updater import check_for_update_and_download, fetch_available_update
from .rauc_installer import install_bundle, InstallError
from .notification_service import NotificationService, reboot_required_message
from .supervisor_api import get_current_haos_version
from .mqtt_service import MqttService

_LOGGER = logging.getLogger(__name__)


class UpdateOrchestrator:
    """Координирует проверку, загрузку и установку обновлений."""

    def __init__(self, cfg: AddonConfig, notifier: NotificationService | None = None) -> None:
        self._cfg = cfg
        self._notifier = notifier or NotificationService(enabled=cfg.notifications)
        self._mqtt_service: MqttService | None = None
        self._in_progress: bool = False
        self._latest_version: str | None = None
        self._installed_version: str | None = None

    def set_mqtt_service(self, mqtt_service: MqttService | None) -> None:
        self._mqtt_service = mqtt_service



    def get_versions(self, installed: str | None = None, latest: str | None = None) -> tuple[str, str]:
        """Получает и кэширует версии системы."""
        if installed is None:
            if self._installed_version is None:
                self._installed_version = get_current_haos_version() or "unknown"
            installed = self._installed_version
        else:
            self._installed_version = installed
        
        if latest is not None:
            self._latest_version = latest
        elif self._latest_version is None:
            try:
                self._latest_version = fetch_available_update(dev_channel=self._cfg.dev_channel).version
            except Exception:
                self._latest_version = installed
        
        return installed, self._latest_version

    def _safe_mqtt_operation(self, operation_name: str, operation_func) -> None:
        """Безопасно выполняет MQTT операцию с обработкой ошибок."""
        if not self._mqtt_service:
            return
        try:
            operation_func()
        except Exception as e:
            _LOGGER.warning("Ошибка %s MQTT: %s", operation_name, e)

    def _publish_update_state(self, installed: str, latest: str, in_progress: bool = False) -> None:
        """Публикует состояние обновления через MQTT безопасно."""
        self._safe_mqtt_operation(
            "публикации состояния",
            lambda: self._mqtt_service.publish_update_state(installed, latest, in_progress)
        )

    def publish_state(self, installed: str | None = None, latest: str | None = None, in_progress: bool | None = None) -> None:
        """Публикует текущее состояние в MQTT."""
        if not self._mqtt_service or not self._mqtt_service._is_ready():
            return

        installed, latest = self.get_versions(installed, latest)
        current_in_progress = self._in_progress if in_progress is None else in_progress
        self._publish_update_state(installed, latest, current_in_progress)



    def check_and_download(self) -> Path | None:
        """Проверяет и загружает обновление согласно конфигурации."""
        return check_for_update_and_download(auto_download=self._cfg.auto_update, orchestrator=self, dev_channel=self._cfg.dev_channel)

    def install_if_ready(self, bundle_path: Path) -> bool:
        """Устанавливает RAUC bundle."""
        _LOGGER.info("Начало install_if_ready для %s", bundle_path)
        try:
            success = install_bundle(bundle_path)
            _LOGGER.info("install_bundle вернул: %s", success)
            if success:
                _LOGGER.info("Создание флага перезагрузки")
                self._touch_reboot_flag()
            return success
        except InstallError as exc:
            _LOGGER.error("RAUC install failed: %s", exc)
            self._notifier.send_notification(
                "UMDU HAOS Update – ошибка установки",
                f"❌ Не удалось установить обновление: {exc}",
            )
            return False

    def auto_cycle_once(self) -> None:
        """Одна итерация цикла автообновления."""
        if self._in_progress:
            return

        bundle_path = self.check_and_download()
        if bundle_path and self._cfg.auto_update:
            _LOGGER.info("Auto-installing %s", bundle_path)
            self.run_install(bundle_path)
        else:
            self.publish_state()

    def run_install(self, bundle_path: Path, latest_version: str | None = None) -> None:
        """Запускает RAUC-установку."""
        _LOGGER.info("Начало установки: %s", bundle_path)
        self._in_progress = True
        self.publish_state(latest=latest_version)

        try:
            success = self.install_if_ready(bundle_path)
        except Exception as e:
            _LOGGER.error("Исключение во время установки: %s", e)
            success = False
        
        self._in_progress = False
        
        if success:
            self._safe_mqtt_operation(
                "деактивации update entity",
                lambda: self._mqtt_service.deactivate_update_entity()
            )
            try:
                self._notifier.send_notification(
                    "UMDU HAOS Update Installed", 
                    reboot_required_message(latest_version or "unknown")
                )
            except Exception as e:
                _LOGGER.error("Ошибка отправки уведомления: %s", e)
        
        # Публикуем финальное состояние только если установка не удалась
        if not success:
            self.publish_state(latest=latest_version)
        
        _LOGGER.info("Установка завершена: %s", "успешно" if success else "неудачно")

    @staticmethod
    def _touch_reboot_flag() -> None:
        Path("/data/reboot_required").touch(exist_ok=True)