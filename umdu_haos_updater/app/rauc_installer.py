from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .errors import InstallError

logger = logging.getLogger(__name__)


def install_bundle(bundle_path: Path) -> bool:
    """Устанавливает RAUC-бандл."""
    if not bundle_path.exists():
        raise InstallError(f"Bundle file not found: {bundle_path}")

    share_link = Path("/mnt/data/supervisor/share")
    if not share_link.exists():
        try:
            share_link.parent.mkdir(parents=True, exist_ok=True)
            share_link.symlink_to("/share")
            logger.info("Создана символическая ссылка %s -> /share", share_link)
        except Exception as e:
            logger.warning("Не удалось создать символическую ссылку: %s", e)

    host_bundle_path = str(bundle_path).replace("/share/", "/mnt/data/supervisor/share/")
    logger.info("Установка бандла: %s", host_bundle_path)

    try:
        process = subprocess.Popen(
            ["rauc", "install", host_bundle_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        
        if process.stdout:
            for line in process.stdout:
                line = line.strip()
                if line:
                    logger.info("RAUC: %s", line)

        return_code = process.wait()
        if return_code != 0:
            raise InstallError(f"RAUC install завершился с кодом {return_code}")

        logger.info("Установка бандла завершена успешно")
        return True
    except FileNotFoundError as e:
        raise InstallError("RAUC CLI не найден") from e
    except Exception as e:
        raise InstallError(f"Ошибка при установке: {e}") from e