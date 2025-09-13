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
    # Защита от повторных/параллельных установок
    if getattr(orchestrator, "_in_progress", False):
        _LOGGER.info("Команда install проигнорирована: установка уже выполняется")
        return
    _, latest_version = orchestrator.get_versions()
    _LOGGER.info("MQTT install: установка версии %s", latest_version)

    bundle_path = check_for_update_and_download(auto_download=True, orchestrator=orchestrator, dev_channel=orchestrator._cfg.dev_channel)
    if not bundle_path:
        _LOGGER.error("Не удалось получить RAUC-бандл, установка отменена")
        orchestrator.publish_state(latest=latest_version)
        return

    orchestrator.run_install(bundle_path, latest_version)


async def initialize_and_setup_mqtt(cfg: AddonConfig, orchestrator: UpdateOrchestrator, loop: asyncio.AbstractEventLoop, retry_delay: int = 0) -> MqttService | None:
    """Инициализирует и настраивает MQTT сервис."""
    if retry_delay > 0:
        _LOGGER.info("Ожидание %d секунд перед попыткой подключения к MQTT", retry_delay)
        await asyncio.sleep(retry_delay)
        # За время ожидания соединение могло восстановиться — проверим и выйдем
        try:
            if orchestrator._mqtt_service and orchestrator._mqtt_service.is_ready():
                _LOGGER.info("MQTT уже подключен, повторная инициализация не требуется")
                return None
        except Exception:
            pass
    
    _LOGGER.info("Попытка инициализации MQTT...")
    params = await loop.run_in_executor(None, cfg.get_mqtt_params)
    host, port, user, passwd, use_tls = params

    if not host:
        _LOGGER.warning("Не удалось инициализировать MQTT. Следующая попытка будет в следующем цикле.")
        return None

    try:
        mqtt_service = MqttService(host=host, port=port, username=user, password=passwd, use_tls=use_tls, discovery=True)
        
        # Получаем версии и устанавливаем их в MQTT сервис
        installed, latest = await loop.run_in_executor(None, orchestrator.get_versions)
        mqtt_service.set_initial_versions(installed, latest)
        mqtt_service.on_install_cmd = lambda: loop.run_in_executor(None, handle_install_cmd, orchestrator)
        mqtt_service.start()
        # На старте не очищаем retain-сообщения: это приводило к стиранию
        # только что опубликованного availability и entity становилась недоступной в HA.
        
        _LOGGER.info("MQTT сервис успешно запущен и настроен")
        return mqtt_service
    except Exception as exc:
        _LOGGER.warning("Не удалось инициализировать MQTT: %s. Следующая попытка будет в следующем цикле.", exc)
        return None


async def handle_mqtt_reconnection(cfg: AddonConfig, orchestrator: UpdateOrchestrator, loop: asyncio.AbstractEventLoop, mqtt_retry_count: int) -> tuple[MqttService | None, int]:
    """Обрабатывает переподключение к MQTT."""
    mqtt_retry_count += 1
    max_mqtt_retries = 5
    retry_delay = min(30 + (mqtt_retry_count - 1) * 15, 120)
    
    _LOGGER.info("MQTT не подключен. Попытка переподключения #%d через %d секунд", mqtt_retry_count, retry_delay)
    mqtt_service = await initialize_and_setup_mqtt(cfg, orchestrator, loop, retry_delay=retry_delay)

    # Если initialize вернул None, но текущий сервис уже в порядке — считаем переподключение успешным
    try:
        if mqtt_service is None and orchestrator._mqtt_service and orchestrator._mqtt_service.is_ready():
            _LOGGER.info("MQTT уже подключен, использование существующего соединения")
            return orchestrator._mqtt_service, 0
    except Exception:
        pass

    if mqtt_service:
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
    _LOGGER.info("Настройки: interval=%s auto_update=%s dev_channel=%s", cfg.check_interval, cfg.auto_update, cfg.dev_channel)

    if not TOKEN:
        _LOGGER.error("SUPERVISOR_TOKEN отсутствует — работа невозможна")
        sys.exit(1)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    
    notifier = NotificationService(enabled=cfg.notifications)
    orchestrator = UpdateOrchestrator(cfg, notifier)
    
    # Начальная задержка для ожидания готовности MQTT сервиса
    mqtt_service = await initialize_and_setup_mqtt(cfg, orchestrator, loop, retry_delay=30)
    mqtt_init_grace = False
    if mqtt_service is not None:
        orchestrator.set_mqtt_service(mqtt_service)
        # Небольшая «grace» задержка: даём MQTT успеть перейти в on_connect
        mqtt_init_grace = True

    # Счётчик повторных попыток подключения к MQTT (между итерациями)
    mqtt_retry_count = 0

    # Аккуратное завершение по сигналу (Linux)
    try:
        import signal  # noqa: WPS433

        def _graceful_shutdown() -> None:
            try:
                if orchestrator._mqtt_service:
                    orchestrator._mqtt_service.stop()
            finally:
                # Signal the main loop to exit without forcibly stopping the event loop
                try:
                    stop_event.set()
                except Exception:
                    pass

        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
            if sig is not None:
                try:
                    loop.add_signal_handler(sig, _graceful_shutdown)
                except Exception:
                    pass
    except Exception:
        pass

    try:
        while not stop_event.is_set():
            await loop.run_in_executor(None, orchestrator.auto_cycle_once)

            if not orchestrator._mqtt_service or not orchestrator._mqtt_service.is_ready():
                # Если только что инициализировали MQTT — подождём чуть-чуть и перепроверим
                if mqtt_init_grace and orchestrator._mqtt_service is not None:
                    try:
                        await asyncio.sleep(2)
                    except Exception:
                        pass
                    finally:
                        mqtt_init_grace = False
                    if orchestrator._mqtt_service.is_ready():
                        mqtt_retry_count = 0
                        continue
                mqtt_service, mqtt_retry_count = await handle_mqtt_reconnection(
                    cfg, orchestrator, loop, mqtt_retry_count
                )
                if mqtt_service is not None:
                    orchestrator.set_mqtt_service(mqtt_service)
            else:
                mqtt_retry_count = 0

            # Sleep but wake up early on shutdown signal
            if cfg.check_interval and cfg.check_interval > 0:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=cfg.check_interval)
                except asyncio.TimeoutError:
                    pass
            else:
                # Yield control (and let tests patch asyncio.sleep to abort)
                await asyncio.sleep(0)
    finally:
        try:
            if orchestrator._mqtt_service:
                orchestrator._mqtt_service.stop()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _LOGGER.info("Завершение по Ctrl+C")
