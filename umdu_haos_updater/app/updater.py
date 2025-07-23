from __future__ import annotations

import logging
import requests
from packaging.version import Version
from pathlib import Path
import hashlib
from contextlib import contextmanager

from .supervisor_api import get_current_haos_version
from .errors import DownloadError, NetworkError, handle_request_error

_LOGGER = logging.getLogger(__name__)

GITHUB_VERSIONS_URL = "https://raw.githubusercontent.com/umduru/umdu-haos-updater/main/versions.json"
GITHUB_VERSIONS_DEV_URL = "https://raw.githubusercontent.com/umduru/umdu-haos-updater/main/versions_dev.json"
RELEASE_BASE_TEMPLATE = "https://github.com/umduru/umdu-haos-updater/releases/download/{ver}"
SHARE_DIR = Path("/share/umdu-haos-updater")


class UpdateInfo:
    def __init__(self, version: str, sha256: str | None = None):
        self.version = version
        self.sha256 = sha256

    @property
    def filename(self) -> str:
        return f"haos_umdu-k1-{self.version}.raucb"

    @property
    def url(self) -> str:
        return f"{RELEASE_BASE_TEMPLATE.format(ver=self.version)}/{self.filename}"

    @property
    def download_path(self) -> Path:
        SHARE_DIR.mkdir(parents=True, exist_ok=True)
        return SHARE_DIR / self.filename





def fetch_available_update(dev_channel: bool = False) -> UpdateInfo:
    """Запрашивает доступные версии с GitHub."""
    url = GITHUB_VERSIONS_DEV_URL if dev_channel else GITHUB_VERSIONS_URL
    channel_name = "dev" if dev_channel else "stable"
    _LOGGER.debug("Запрос версий из %s канала: %s", channel_name, url)
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()["hassos"]["umdu-k1"]
        if isinstance(data, dict):
            return UpdateInfo(version=str(data.get("version")), sha256=data.get("sha256"))
        return UpdateInfo(version=str(data))
    except Exception as e:
        handle_request_error(e, "получить versions.json", _LOGGER)


def is_newer(ver_a: str, ver_b: str) -> bool:
    """Возвращает True если ver_a > ver_b."""
    try:
        return Version(ver_a) > Version(ver_b)
    except Exception:
        return ver_a != ver_b and ver_a > ver_b


@contextmanager
def _download_progress(orchestrator, version: str):
    """Контекст-менеджер для управления статусом прогресса загрузки."""
    if orchestrator:
        orchestrator._in_progress = True
        orchestrator.publish_state(latest=version)
    try:
        yield
    finally:
        if orchestrator:
            orchestrator._in_progress = False
            orchestrator.publish_state(latest=version)


def download_update(info: UpdateInfo, orchestrator=None) -> Path:
    path = info.download_path

    if path.exists():
        if info.sha256:
            if _verify_sha256(path, info.sha256):
                _LOGGER.info("Файл обновления уже существует и валиден: %s", path)
                return path
            _LOGGER.warning("Файл существует но хэш не совпадает, перезагружаем: %s", path)
            path.unlink(missing_ok=True)
        else:
            _LOGGER.info("Файл обновления уже существует: %s", path)
            return path

    # Очистка старых бандлов
    for p in SHARE_DIR.glob("haos_umdu-k1-*.raucb"):
        if p.name != path.name:
            p.unlink(missing_ok=True)

    _LOGGER.info("Загрузка обновления %s", info.url)
    with _download_progress(orchestrator, info.version):
        try:
            with requests.get(info.url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(path, "wb") as fw:
                    for chunk in r.iter_content(chunk_size=8192):
                        fw.write(chunk)
        except Exception as e:
            handle_request_error(e, "загрузки бандла", _LOGGER)

        if info.sha256 and not _verify_sha256(path, info.sha256):
            _LOGGER.error("Хэш-сумма не совпала для %s", path)
            path.unlink(missing_ok=True)
            raise DownloadError("SHA256 mismatch after download")
    _LOGGER.info("Файл обновления сохранён: %s", path)
    return path


def _verify_sha256(path: Path, expected: str) -> bool:
    sha = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest().lower() == expected.lower()


def check_for_update_and_download(auto_download: bool = False, orchestrator=None, dev_channel: bool = False) -> Path | None:
    current = get_current_haos_version()
    if not current:
        _LOGGER.warning("Не удалось определить установленную версию")
        return None

    try:
        avail = fetch_available_update(dev_channel=dev_channel)
    except NetworkError:
        _LOGGER.info("Не удалось получить информацию об обновлении")
        return None

    _LOGGER.info("Текущая версия: %s; доступная: %s", current, avail.version)
    if is_newer(avail.version, current):
        _LOGGER.info("Найдена новая версия %s", avail.version)
        if auto_download:
            try:
                return download_update(avail, orchestrator)
            except DownloadError as e:
                _LOGGER.error("Скачивание обновления не удалось: %s", e)
    else:
        _LOGGER.info("Система актуальна")
    return None