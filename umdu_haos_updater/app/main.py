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


def _get_supervisor_mqtt_params(cfg: AddonConfig) -> tuple[str, int, str | None, str | None]:
    """Получает параметры MQTT из Supervisor API."""
    try:
        sup = get_mqtt_service()
        if sup and sup.get("host"):
            return (
                sup["host"],
                sup.get("port") or cfg.mqtt_port or 1883,
                cfg.mqtt_username or sup.get("username"),
                cfg.mqtt_password or sup.get("password")
            )
    except Exception as exc:
        from .errors import NetworkError
        if isinstance(exc, NetworkError) and "not ready yet" in str(exc):
            logger.debug("MQTT сервис еще не готов, будем ждать")
        else:
            logger.warning("MQTT params via Supervisor API failed: %s", exc)
    return cfg.mqtt_host or "core-mosquitto", cfg.mqtt_port or 1883, cfg.mqtt_username, cfg.mqtt_password


def build_mqtt_params(cfg: AddonConfig):
    host, port, user, password = cfg.mqtt_host, cfg.mqtt_port or 1883, cfg.mqtt_username, cfg.mqtt_password

    # Fallback к Supervisor API если нет учетных данных или используется дефолтный хост
    if not user or not password or host == "core-mosquitto":
        host, port, user, password = _get_supervisor_mqtt_params(cfg)
        if host != "core-mosquitto":
            logger.debug("Получены параметры MQTT из Supervisor API")

    return host, port, user, password


# ------------------------------------------------------------------
# MQTT command handlers
# ------------------------------------------------------------------





def handle_install_cmd(orchestrator: UpdateOrchestrator):
    """Обработчик MQTT-команды install."""
    _, latest_version = orchestrator.get_versions()
    logger.info("MQTT install: установка версии %s", latest_version)

    bundle_path = check_for_update_and_download(auto_download=True, orchestrator=orchestrator)
    if not bundle_path:
        logger.error("Не удалось получить RAUC-бандл, установка отменена")
        orchestrator.publish_state(latest=latest_version)
        return

    orchestrator.run_install(bundle_path, latest_version)





async def try_initialize_mqtt(cfg: AddonConfig, orchestrator: UpdateOrchestrator, loop: asyncio.AbstractEventLoop, retry_delay: int = 0) -> MqttService | None:
    """Пытается инициализировать MQTT сервис."""
    if retry_delay > 0:
        logger.info("Ожидание %d секунд перед попыткой подключения к MQTT", retry_delay)
        await asyncio.sleep(retry_delay)
    
    logger.info("Попытка инициализации MQTT...")
    host, port, user, passwd = await loop.run_in_executor(None, lambda: build_mqtt_params(cfg))

    if not host:
        logger.warning("Не удалось инициализировать MQTT. Следующая попытка будет в следующем цикле.")
        return None

    try:
        installed, latest = await loop.run_in_executor(None, orchestrator.get_versions)
        
        mqtt_service = MqttService(host=host, port=port, username=user, password=passwd, discovery=True)
        mqtt_service.set_initial_versions(installed, latest)
        mqtt_service.start()
        logger.info("MQTT сервис успешно запущен")
        return mqtt_service
    except Exception as exc:
        logger.warning("Не удалось инициализировать MQTT: %s. Следующая попытка будет в следующем цикле.", exc)
        return None


async def main() -> None:
    logger.info("-" * 80)
    logger.info("Запуск UMDU HAOS Updater")

    cfg = AddonConfig()
    if cfg.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("DEBUG mode включён")
    logger.info("Настройки: interval=%s auto_update=%s", cfg.check_interval, cfg.auto_update)

    if not TOKEN:
        logger.error("SUPERVISOR_TOKEN отсутствует — работа невозможна")
        sys.exit(1)

    loop = asyncio.get_running_loop()
    
    notifier = NotificationService(enabled=cfg.notifications)
    orchestrator = UpdateOrchestrator(cfg, notifier)
    
    # Начальная задержка для ожидания готовности MQTT сервиса
    mqtt_service = await try_initialize_mqtt(cfg, orchestrator, loop, retry_delay=30)
    orchestrator.set_mqtt_service(mqtt_service)

    def setup_mqtt_handler(mqtt_svc):
        if mqtt_svc:
            mqtt_svc.on_install_cmd = lambda: loop.run_in_executor(None, handle_install_cmd, orchestrator)
            return True
        return False

    if setup_mqtt_handler(mqtt_service):
        await asyncio.sleep(2)
        mqtt_service.clear_retained_messages()

    mqtt_retry_count = 0
    max_mqtt_retries = 5
    
    while True:
        await loop.run_in_executor(None, orchestrator.auto_cycle_once)

        if not mqtt_service:
            mqtt_retry_count += 1
            retry_delay = min(30 + (mqtt_retry_count - 1) * 15, 120)  # Увеличиваем задержку: 30, 45, 60, 75, 90, 105, 120
            
            logger.info("MQTT не подключен. Попытка переподключения #%d через %d секунд", mqtt_retry_count, retry_delay)
            mqtt_service = await try_initialize_mqtt(cfg, orchestrator, loop, retry_delay=retry_delay)
            
            if setup_mqtt_handler(mqtt_service):
                logger.info("MQTT успешно переподключен")
                orchestrator.set_mqtt_service(mqtt_service)
                mqtt_retry_count = 0  # Сбрасываем счетчик при успешном подключении
                await asyncio.sleep(2)
                mqtt_service.clear_retained_messages()
                # Публикуем актуальное состояние после переподключения
                await loop.run_in_executor(None, orchestrator.publish_initial_state)
            elif mqtt_retry_count >= max_mqtt_retries:
                logger.warning("Достигнуто максимальное количество попыток подключения к MQTT (%d). Продолжаем работу без MQTT.", max_mqtt_retries)
                mqtt_retry_count = 0  # Сбрасываем счетчик для следующего цикла

        await asyncio.sleep(cfg.check_interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Завершение по Ctrl+C")