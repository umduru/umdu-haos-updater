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

    def set_mqtt_service(self, mqtt_service: MqttService | None) -> None:
        self._mqtt_service = mqtt_service

    def publish_state(self, installed: str | None = None, latest: str | None = None) -> None:
        """Публикует текущее состояние в MQTT."""
        if not self._mqtt_service:
            return

        if installed is None:
            installed = get_current_haos_version() or "unknown"
        
        if latest is not None:
            self._latest_version = latest
        elif self._latest_version is None:
            try:
                self._latest_version = fetch_available_update().version
            except Exception:
                self._latest_version = installed

        try:
            self._mqtt_service.publish_update_state(installed, self._latest_version, self._in_progress)
        except Exception as e:
            _LOGGER.warning("Ошибка публикации состояния MQTT: %s", e)

    def publish_initial_state(self) -> None:
        """Публикует начальное состояние после инициализации MQTT."""
        if not self._mqtt_service:
            return
        
        _LOGGER.info("Публикация начального состояния MQTT")
        
        # Получаем текущую версию
        installed = get_current_haos_version() or "unknown"
        
        # Пытаемся получить доступную версию
        try:
            latest = fetch_available_update().version
            self._latest_version = latest
            _LOGGER.info("Получена доступная версия: %s", latest)
        except Exception as e:
            _LOGGER.warning("Не удалось получить доступную версию при инициализации: %s", e)
            latest = installed
            self._latest_version = latest
        
        # Публикуем состояние
        try:
            self._mqtt_service.publish_update_state(installed, latest, False)
            _LOGGER.info("Начальное состояние опубликовано: installed=%s, latest=%s", installed, latest)
        except Exception as e:
            _LOGGER.warning("Ошибка публикации начального состояния MQTT: %s", e)

    def check_and_download(self) -> Path | None:
        """Проверяет и загружает обновление согласно конфигурации."""
        return check_for_update_and_download(auto_download=self._cfg.auto_update, orchestrator=self)

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

        try:
            self._latest_version = fetch_available_update().version
        except Exception:
            if not self._latest_version:
                self._latest_version = get_current_haos_version() or "unknown"

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
            _LOGGER.info("Результат установки: %s", success)
        except Exception as e:
            _LOGGER.error("Исключение во время установки: %s", e)
            success = False
        
        self._in_progress = False
        _LOGGER.info("Установка завершена, success=%s", success)
        
        if self._mqtt_service:
            _LOGGER.info("Обработка MQTT после установки")
            if success:
                _LOGGER.info("Деактивация MQTT сущности обновления")
                self._mqtt_service.deactivate_update_entity()
            else:
                _LOGGER.info("Публикация состояния MQTT после неудачной установки")
                self.publish_state(latest=latest_version)

        if success:
            _LOGGER.info("Отправка уведомления о необходимости перезагрузки")
            try:
                notification_sent = self._notifier.send_notification(
                    "UMDU HAOS Update Installed", 
                    reboot_required_message(latest_version or "unknown")
                )
                if notification_sent:
                    _LOGGER.info("Уведомление о перезагрузке отправлено успешно")
                else:
                    _LOGGER.warning("Не удалось отправить уведомление о перезагрузке")
            except Exception as e:
                _LOGGER.error("Исключение при отправке уведомления: %s", e)
        
        _LOGGER.info("Метод run_install завершен")

    @staticmethod
    def _touch_reboot_flag() -> None:
        Path("/data/reboot_required").touch(exist_ok=True)