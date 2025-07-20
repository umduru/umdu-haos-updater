#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import sys

from .config import AddonConfig
from .updater import check_for_update_and_download
from .mqtt_service import MqttService
from .supervisor_api import TOKEN
from .notification_service import NotificationService
from .orchestrator import UpdateOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
_LOGGER = logging.getLogger(__name__)





def handle_install_cmd(orchestrator: UpdateOrchestrator):
    """Обработчик MQTT-команды install."""
    _, latest_version = orchestrator.get_versions()
    _LOGGER.info("MQTT install: установка версии %s", latest_version)

    bundle_path = check_for_update_and_download(auto_download=True, orchestrator=orchestrator)
    if not bundle_path:
        _LOGGER.error("Не удалось получить RAUC-бандл, установка отменена")
        orchestrator.publish_state(latest=latest_version)
        return

    orchestrator.run_install(bundle_path, latest_version)


async def try_initialize_mqtt(cfg: AddonConfig, orchestrator: UpdateOrchestrator, loop: asyncio.AbstractEventLoop, retry_delay: int = 0) -> MqttService | None:
    """Пытается инициализировать MQTT сервис."""
    if retry_delay > 0:
        _LOGGER.info("Ожидание %d секунд перед попыткой подключения к MQTT", retry_delay)
        await asyncio.sleep(retry_delay)
    
    _LOGGER.info("Попытка инициализации MQTT...")
    host, port, user, passwd = await loop.run_in_executor(None, cfg.get_mqtt_params)

    if not host:
        _LOGGER.warning("Не удалось инициализировать MQTT. Следующая попытка будет в следующем цикле.")
        return None

    try:
        installed, latest = await loop.run_in_executor(None, orchestrator.get_versions)
        
        mqtt_service = MqttService(host=host, port=port, username=user, password=passwd, discovery=True)
        mqtt_service.set_initial_versions(installed, latest)
        mqtt_service.start()
        _LOGGER.info("MQTT сервис успешно запущен")
        return mqtt_service
    except Exception as exc:
        _LOGGER.warning("Не удалось инициализировать MQTT: %s. Следующая попытка будет в следующем цикле.", exc)
        return None


async def setup_mqtt_service(mqtt_service: MqttService | None, orchestrator: UpdateOrchestrator, loop: asyncio.AbstractEventLoop) -> bool:
    """Настраивает обработчики MQTT сервиса."""
    if not mqtt_service:
        return False
    
    mqtt_service.on_install_cmd = lambda: loop.run_in_executor(None, handle_install_cmd, orchestrator)
    await asyncio.sleep(2)
    mqtt_service.clear_retained_messages()
    return True


async def handle_mqtt_reconnection(cfg: AddonConfig, orchestrator: UpdateOrchestrator, loop: asyncio.AbstractEventLoop, mqtt_retry_count: int) -> tuple[MqttService | None, int]:
    """Обрабатывает переподключение к MQTT."""
    mqtt_retry_count += 1
    max_mqtt_retries = 5
    retry_delay = min(30 + (mqtt_retry_count - 1) * 15, 120)
    
    _LOGGER.info("MQTT не подключен. Попытка переподключения #%d через %d секунд", mqtt_retry_count, retry_delay)
    mqtt_service = await try_initialize_mqtt(cfg, orchestrator, loop, retry_delay=retry_delay)
    
    if await setup_mqtt_service(mqtt_service, orchestrator, loop):
        _LOGGER.info("MQTT успешно переподключен")
        orchestrator.set_mqtt_service(mqtt_service)
        _LOGGER.info("Публикация начального состояния MQTT")
        await loop.run_in_executor(None, orchestrator.publish_state)
        return mqtt_service, 0  # Сбрасываем счетчик
    elif mqtt_retry_count >= max_mqtt_retries:
        _LOGGER.warning("Достигнуто максимальное количество попыток подключения к MQTT (%d). Продолжаем работу без MQTT.", max_mqtt_retries)
        return None, 0  # Сбрасываем счетчик
    
    return None, mqtt_retry_count


async def main() -> None:
    _LOGGER.info("-" * 80)
    _LOGGER.info("Запуск UMDU HAOS Updater")

    cfg = AddonConfig()
    if cfg.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        _LOGGER.debug("DEBUG mode включён")
    _LOGGER.info("Настройки: interval=%s auto_update=%s", cfg.check_interval, cfg.auto_update)

    if not TOKEN:
        _LOGGER.error("SUPERVISOR_TOKEN отсутствует — работа невозможна")
        sys.exit(1)

    loop = asyncio.get_running_loop()
    
    notifier = NotificationService(enabled=cfg.notifications)
    orchestrator = UpdateOrchestrator(cfg, notifier)
    
    # Начальная задержка для ожидания готовности MQTT сервиса
    mqtt_service = await try_initialize_mqtt(cfg, orchestrator, loop, retry_delay=30)
    orchestrator.set_mqtt_service(mqtt_service)
    await setup_mqtt_service(mqtt_service, orchestrator, loop)

    mqtt_retry_count = 0
    
    while True:
        await loop.run_in_executor(None, orchestrator.auto_cycle_once)

        if not orchestrator.is_mqtt_ready():
            mqtt_service, mqtt_retry_count = await handle_mqtt_reconnection(cfg, orchestrator, loop, mqtt_retry_count)

        await asyncio.sleep(cfg.check_interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _LOGGER.info("Завершение по Ctrl+C")