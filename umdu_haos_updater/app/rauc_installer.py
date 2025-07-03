from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .errors import InstallError

logger = logging.getLogger(__name__)


def install_bundle(path: Path) -> bool:
    """Устанавливает RAUC-бандл.

    Возвращает True при успехе, иначе поднимает :class:`InstallError`.
    """

    if not path.exists():
        raise InstallError(f"Bundle file not found: {path}")

    # Workaround: создаем символическую ссылку /mnt/data/supervisor/share -> /share
    # чтобы RAUC на хосте мог найти файл по пути /mnt/data/supervisor/share/...
    share_link = Path("/mnt/data/supervisor/share")
    if not share_link.exists():
        try:
            share_link.parent.mkdir(parents=True, exist_ok=True)
            share_link.symlink_to("/share")
            logger.info("Создана символическая ссылка %s -> /share", share_link)
        except Exception as e:
            logger.warning("Не удалось создать символическую ссылку %s: %s", share_link, e)

    # RAUC выполняется на хосте, поэтому нужен хостовый путь
    host_path = str(path).replace("/share/", "/mnt/data/supervisor/share/")
    logger.info("Запуск установки RAUC: %s (хостовый путь: %s)", path, host_path)
    try:
        # Печатаем вывод RAUC построчно, используем хостовый путь
        proc = subprocess.Popen(
            ["rauc", "install", host_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:  # type: ignore[attr-defined]
            line = line.rstrip()
            print(line)
        
        proc.wait()
        if proc.returncode == 0:
            logger.info("RAUC завершился успешно")
            return True

        # Неуспешный код завершения – считаем ошибкой установки.
        logger.error("RAUC завершился с кодом %s", proc.returncode)
        raise InstallError(f"RAUC install exited with code {proc.returncode}")
    except FileNotFoundError as exc:
        logger.exception("RAUC CLI не найден в контейнере")
        raise InstallError("RAUC CLI not found") from exc
    except Exception as e:
        logger.exception("Ошибка запуска rauc")
        raise InstallError("Unexpected error while running rauc") from e 