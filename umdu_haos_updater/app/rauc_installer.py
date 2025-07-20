from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .errors import InstallError

_LOGGER = logging.getLogger(__name__)


def _ensure_share_link() -> None:
    """Создает символическую ссылку для доступа к /share."""
    share_link = Path("/mnt/data/supervisor/share")
    if not share_link.exists():
        try:
            share_link.parent.mkdir(parents=True, exist_ok=True)
            share_link.symlink_to("/share")
            _LOGGER.info("Создана символическая ссылка %s -> /share", share_link)
        except Exception as e:
            _LOGGER.warning("Не удалось создать символическую ссылку: %s", e)


def _run_rauc_install(host_bundle_path: str) -> None:
    """Выполняет установку RAUC-бандла."""
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
                    _LOGGER.info("RAUC: %s", line)

        return_code = process.wait()
        if return_code != 0:
            raise InstallError(f"RAUC install завершился с кодом {return_code}")

    except FileNotFoundError as e:
        raise InstallError("RAUC CLI не найден") from e
    except Exception as e:
        raise InstallError(f"Ошибка при установке: {e}") from e


def install_bundle(bundle_path: Path) -> bool:
    """Устанавливает RAUC-бандл."""
    if not bundle_path.exists():
        raise InstallError(f"Bundle file not found: {bundle_path}")

    _ensure_share_link()

    host_bundle_path = str(bundle_path).replace("/share/", "/mnt/data/supervisor/share/")
    _LOGGER.info("Установка бандла: %s", host_bundle_path)

    _run_rauc_install(host_bundle_path)
    
    _LOGGER.info("Установка бандла завершена успешно")
    return True