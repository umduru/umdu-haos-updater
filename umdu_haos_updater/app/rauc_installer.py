from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .errors import InstallError

_LOGGER = logging.getLogger(__name__)


class RaucCommandError(Exception):
    """Ошибка выполнения RAUC CLI-команды."""


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


def _run_rauc_command(args: list[str], log_prefix: str) -> list[str]:
    """Выполняет RAUC CLI и возвращает строки вывода."""
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    lines: list[str] = []
    if process.stdout:
        for line in process.stdout:
            line = line.strip()
            if line:
                lines.append(line)
                _LOGGER.info("%s: %s", log_prefix, line)

    return_code = process.wait()
    if return_code != 0:
        raise RaucCommandError(f"{' '.join(args)} завершился с кодом {return_code}")
    return lines


def _log_rauc_diagnostic(args: list[str], log_prefix: str) -> None:
    """Логирует диагностическую команду RAUC, не срывая установку при ошибке."""
    try:
        _run_rauc_command(args, log_prefix)
    except FileNotFoundError:
        _LOGGER.warning("RAUC CLI не найден при диагностике: %s", " ".join(args))
    except RaucCommandError as e:
        _LOGGER.warning("Не удалось получить RAUC диагностику (%s): %s", " ".join(args), e)
    except Exception as e:
        _LOGGER.warning("Неожиданная ошибка RAUC диагностики (%s): %s", " ".join(args), e)


def _log_bundle_info(host_bundle_path: str) -> None:
    _log_rauc_diagnostic(["rauc", "info", host_bundle_path], "RAUC bundle")


def _log_system_status(stage: str) -> None:
    _LOGGER.info("RAUC status %s:", stage)
    _log_rauc_diagnostic(["rauc", "status", "--detailed"], "RAUC status")


def _run_rauc_install(host_bundle_path: str) -> None:
    """Выполняет установку RAUC-бандла."""
    try:
        _run_rauc_command(["rauc", "install", host_bundle_path], "RAUC")

    except FileNotFoundError as e:
        raise InstallError("RAUC CLI не найден") from e
    except RaucCommandError as e:
        raise InstallError(str(e)) from e
    except Exception as e:
        raise InstallError(f"Ошибка при установке: {e}") from e


def install_bundle(bundle_path: Path) -> bool:
    """Устанавливает RAUC-бандл."""
    if not bundle_path.exists():
        raise InstallError(f"Bundle file not found: {bundle_path}")

    _ensure_share_link()

    host_bundle_path = str(bundle_path).replace("/share/", "/mnt/data/supervisor/share/")
    _LOGGER.info("Установка бандла: %s", host_bundle_path)

    _log_bundle_info(host_bundle_path)
    _log_system_status("до установки")
    _run_rauc_install(host_bundle_path)
    _log_system_status("после установки")
    
    _LOGGER.info("Установка бандла завершена успешно")
    return True
