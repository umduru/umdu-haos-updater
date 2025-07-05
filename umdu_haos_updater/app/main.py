#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from .config import AddonConfig
from .updater import check_for_update_and_download, fetch_available_update
from .mqtt_service import MqttService
from .supervisor_api import get_mqtt_service, get_current_haos_version, SUPERVISOR_URL, TOKEN
from .notification_service import NotificationService
from .orchestrator import UpdateOrchestrator
import requests


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def build_mqtt_params(cfg: AddonConfig):
    host = cfg.mqtt_host
    port = cfg.mqtt_port or 1883
    user = cfg.mqtt_user
    password = cfg.mqtt_password

    if not host:
        try:
            sup = get_mqtt_service()
        except Exception as exc:  # noqa: BLE001
            logger.debug("MQTT params via Supervisor API failed: %s", exc)
            sup = None
        if sup and sup.get("host"):
            host = sup["host"]
            port = sup.get("port") or port
            user = user or sup.get("username")
            password = password or sup.get("password")

    return host, port, user, password


# ------------------------------------------------------------------
# MQTT command handlers
# ------------------------------------------------------------------


def handle_install_cmd(cfg: AddonConfig, orchestrator: UpdateOrchestrator):
    """Обработчик MQTT-команды `install`.

    • Всегда публикует `in_progress=True`, чтобы Home Assistant показал спиннер.
    • Использует унифицированную установку через orchestrator.
    """
    if orchestrator is None:
        logger.error("Orchestrator not provided for install command")
        return

    # Пытаемся получить сведения об актуальной версии (необязательно)
    try:
        _info = fetch_available_update()
        latest_version = _info.version
    except Exception as exc:  # noqa: BLE001
        logger.debug("fetch_available_update failed: %s", exc)
        latest_version = None

    logger.info("MQTT install: установка версии %s", latest_version)

    bundle_path = check_for_update_and_download(auto_download=True)
    if not bundle_path:
        logger.error("Не удалось получить RAUC-бандл, установка отменена")
        orchestrator.publish_state(latest=latest_version)
        return

    # Унифицированная установка через orchestrator
    orchestrator.run_install(bundle_path, latest_version)


async def _configure_mqtt_service(
    mqtt_service: MqttService,
    orchestrator: UpdateOrchestrator,
    loop: asyncio.AbstractEventLoop,
    cfg: AddonConfig,
    event: asyncio.Event,
    is_reconnect: bool = False,
):
    """Настраивает колбэки и состояние для нового экземпляра MQTT."""
    log_prefix = " (повторное)" if is_reconnect else ""
    
    orchestrator.set_mqtt_service(mqtt_service)
    mqtt_service.on_install_cmd = lambda: loop.run_in_executor(
        None, handle_install_cmd, cfg, orchestrator
    )
    
    try:
        await asyncio.wait_for(event.wait(), timeout=10.0)
        logger.info(f"MQTT-соединение{log_prefix} подтверждено.")
        mqtt_service.clear_retained_messages()
    except asyncio.TimeoutError:
        logger.warning(f"MQTT{log_prefix} не подключился за 10 секунд.")


async def try_initialize_mqtt(
    cfg: AddonConfig, 
    loop: asyncio.AbstractEventLoop,
    connection_event: asyncio.Event
) -> MqttService | None:
    """Пытается инициализировать MQTT сервис (одна попытка)."""
    logger.info("Попытка инициализации MQTT...")
    host, port, user, passwd = await loop.run_in_executor(None, lambda: build_mqtt_params(cfg))

    if cfg.mqtt_discovery and host:
        mqtt_service = MqttService(
            host=host,
            port=port,
            username=user,
            password=passwd,
            discovery=True,
            on_install_cmd=None,
            connection_event=connection_event,
        )
        mqtt_service.start()
        logger.info("MQTT сервис успешно запущен.")
        return mqtt_service

    logger.warning("Не удалось инициализировать MQTT. Следующая попытка будет в следующем цикле.")
    return None


async def main() -> None:
    logger.info("-" * 80)
    logger.info("Запуск UMDU HAOS Updater (Python edition)…")

    cfg = AddonConfig.load()
    if cfg.debug:
        logging.getLogger().setLevel(logging.DEBUG)  # root logger
        logger.debug("DEBUG mode включён")
    logger.info(
        "Настройки: interval=%s auto_update=%s", cfg.update_check_interval, cfg.auto_update
    )

    # --- Валидация Supervisor Token ---
    if not TOKEN:
        logger.error("SUPERVISOR_TOKEN отсутствует — работа невозможна")
        sys.exit(1)

    # Получаем ссылку на текущий event-loop для запуска блокирующих
    # операций в пуле потоков (run_in_executor). Это защитит loop от
    # длительных HTTP-таймаутов и операций ввода-вывода.
    loop = asyncio.get_running_loop()

    # --- MQTT setup ---
    mqtt_connection_event = asyncio.Event()
    mqtt_service = await try_initialize_mqtt(cfg, loop, mqtt_connection_event)

    # Notification service & orchestrator
    notifier = NotificationService(enabled=cfg.notifications)
    orchestrator = UpdateOrchestrator(cfg, notifier)
    orchestrator.set_mqtt_service(mqtt_service)

    # Устанавливаем обработчик после создания orchestrator
    if mqtt_service:
        await _configure_mqtt_service(
            mqtt_service, orchestrator, loop, cfg, mqtt_connection_event
        )

    while True:
        # Полный цикл обновления выполняем в пуле потоков, чтобы не
        # блокировать event-loop.
        await loop.run_in_executor(None, orchestrator.auto_cycle_once)

        # Если MQTT не был подключен при старте, пытаемся снова
        if not mqtt_service:
            logger.info("MQTT не подключен. Попытка переподключения...")
            mqtt_connection_event.clear()
            mqtt_service = await try_initialize_mqtt(cfg, loop, mqtt_connection_event)
            if mqtt_service:
                logger.info("MQTT успешно переподключен.")
                await _configure_mqtt_service(
                    mqtt_service, orchestrator, loop, cfg, mqtt_connection_event, is_reconnect=True
                )
                # Состояние опубликует следующий auto_cycle_once()

        await asyncio.sleep(cfg.update_check_interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Завершение по Ctrl+C") 