#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import sys

from .config import AddonConfig
from .updater import check_for_update_and_download, fetch_available_update
from .mqtt_service import MqttService
from .supervisor_api import get_mqtt_service, TOKEN
from .notification_service import NotificationService
from .orchestrator import UpdateOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def build_mqtt_params(cfg: AddonConfig):
    host, port, user, password = cfg.mqtt_host, cfg.mqtt_port or 1883, cfg.mqtt_username, cfg.mqtt_password

    # Fallback к Supervisor API если нет учетных данных или используется дефолтный хост
    if not user or not password or host == "core-mosquitto":
        try:
            sup = get_mqtt_service()
            if sup and sup.get("host"):
                host = sup["host"]
                port = sup.get("port") or port
                user = user or sup.get("username")
                password = password or sup.get("password")
        except Exception as exc:
            logger.warning("MQTT params via Supervisor API failed: %s", exc)
            # Если не удалось получить данные из Supervisor API, используем конфигурацию
            if not host or host == "core-mosquitto":
                host = "core-mosquitto"  # Fallback к дефолтному хосту

    return host, port, user, password


# ------------------------------------------------------------------
# MQTT command handlers
# ------------------------------------------------------------------


def handle_install_cmd(orchestrator: UpdateOrchestrator):
    """Обработчик MQTT-команды install."""
    try:
        latest_version = fetch_available_update().version
    except Exception as exc:
        logger.debug("fetch_available_update failed: %s", exc)
        latest_version = None

    logger.info("MQTT install: установка версии %s", latest_version)

    bundle_path = check_for_update_and_download(auto_download=True, orchestrator=orchestrator)
    if not bundle_path:
        logger.error("Не удалось получить RAUC-бандл, установка отменена")
        orchestrator.publish_state(latest=latest_version)
        return

    orchestrator.run_install(bundle_path, latest_version)


async def try_initialize_mqtt(cfg: AddonConfig, loop: asyncio.AbstractEventLoop) -> MqttService | None:
    """Пытается инициализировать MQTT сервис."""
    logger.info("Попытка инициализации MQTT...")
    host, port, user, passwd = await loop.run_in_executor(None, lambda: build_mqtt_params(cfg))

    if not host:
        logger.warning("Не удалось инициализировать MQTT. Следующая попытка будет в следующем цикле.")
        return None

    try:
        mqtt_service = MqttService(host=host, port=port, username=user, password=passwd, discovery=True)
        mqtt_service.start()
        logger.info("MQTT сервис успешно запущен")
        return mqtt_service
    except Exception as exc:
        logger.warning("Не удалось инициализировать MQTT: %s. Следующая попытка будет в следующем цикле.", exc)
        return None


async def main() -> None:
    logger.info("-" * 80)
    logger.info("Запуск UMDU HAOS Updater (Python edition)…")

    cfg = AddonConfig()
    if cfg.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("DEBUG mode включён")
    logger.info("Настройки: interval=%s auto_update=%s", cfg.check_interval, cfg.auto_update)

    if not TOKEN:
        logger.error("SUPERVISOR_TOKEN отсутствует — работа невозможна")
        sys.exit(1)

    loop = asyncio.get_running_loop()
    mqtt_service = await try_initialize_mqtt(cfg, loop)
    
    notifier = NotificationService(enabled=cfg.notifications)
    orchestrator = UpdateOrchestrator(cfg, notifier)
    orchestrator.set_mqtt_service(mqtt_service)

    def setup_mqtt_handler(mqtt_svc):
        if mqtt_svc:
            mqtt_svc.on_install_cmd = lambda: loop.run_in_executor(None, handle_install_cmd, orchestrator)
            return True
        return False

    if setup_mqtt_handler(mqtt_service):
        await asyncio.sleep(2)
        mqtt_service.clear_retained_messages()

    while True:
        await loop.run_in_executor(None, orchestrator.auto_cycle_once)

        if not mqtt_service:
            logger.info("MQTT не подключен. Попытка переподключения...")
            mqtt_service = await try_initialize_mqtt(cfg, loop)
            if setup_mqtt_handler(mqtt_service):
                logger.info("MQTT успешно переподключен")
                orchestrator.set_mqtt_service(mqtt_service)
                await asyncio.sleep(2)
                mqtt_service.clear_retained_messages()

        await asyncio.sleep(cfg.check_interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Завершение по Ctrl+C")