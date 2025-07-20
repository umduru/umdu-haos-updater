from __future__ import annotations

import logging
import requests
from packaging.version import Version
from pathlib import Path
import hashlib

from .supervisor_api import get_current_haos_version
from .errors import DownloadError, NetworkError

logger = logging.getLogger(__name__)

GITHUB_VERSIONS_URL = "https://raw.githubusercontent.com/umduru/umdu-haos-updater/main/versions.json"
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


def fetch_available_update() -> UpdateInfo:
    """Запрашивает доступные версии с GitHub."""
    try:
        r = requests.get(GITHUB_VERSIONS_URL, timeout=5)
        r.raise_for_status()
        data = r.json()["hassos"]["umdu-k1"]
        if isinstance(data, dict):
            return UpdateInfo(version=str(data.get("version")), sha256=data.get("sha256"))
        return UpdateInfo(version=str(data))
    except Exception as e:
        logger.exception("Не удалось получить versions.json")
        raise NetworkError("Failed to fetch available update info") from e


def is_newer(ver_a: str, ver_b: str) -> bool:
    """Возвращает True если ver_a > ver_b."""
    try:
        return Version(ver_a) > Version(ver_b)
    except Exception:
        return ver_a != ver_b and ver_a > ver_b


def download_update(info: UpdateInfo) -> Path:
    path = info.download_path

    if path.exists():
        if info.sha256:
            if _verify_sha256(path, info.sha256):
                logger.info("Файл обновления уже существует и валиден: %s", path)
                return path
            logger.warning("Файл существует но хэш не совпадает, перезагружаем: %s", path)
            path.unlink(missing_ok=True)
        else:
            logger.info("Файл обновления уже существует: %s", path)
            return path

    # Очистка старых бандлов
    for p in SHARE_DIR.glob("haos_umdu-k1-*.raucb"):
        if p.name != path.name:
            p.unlink(missing_ok=True)

    logger.info("Загрузка обновления %s", info.url)
    try:
        with requests.get(info.url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(path, "wb") as fw:
                for chunk in r.iter_content(chunk_size=8192):
                    fw.write(chunk)
    except Exception as e:
        logger.exception("Ошибка загрузки бандла")
        raise DownloadError("Error downloading update bundle") from e

    if info.sha256 and not _verify_sha256(path, info.sha256):
        logger.error("Хэш-сумма не совпала для %s", path)
        path.unlink(missing_ok=True)
        raise DownloadError("SHA256 mismatch after download")
    
    logger.info("Файл обновления сохранён: %s", path)
    return path


def _verify_sha256(path: Path, expected: str) -> bool:
    sha = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest().lower() == expected.lower()


def check_for_update_and_download(auto_download: bool = False) -> Path | None:
    current = get_current_haos_version()
    if not current:
        logger.warning("Не удалось определить установленную версию")
        return None

    try:
        avail = fetch_available_update()
    except NetworkError:
        logger.info("Не удалось получить информацию об обновлении")
        return None

    logger.info("Текущая версия: %s; доступная: %s", current, avail.version)
    if is_newer(avail.version, current):
        logger.info("Найдена новая версия %s", avail.version)
        if auto_download:
            try:
                return download_update(avail)
            except DownloadError as e:
                logger.error("Скачивание обновления не удалось: %s", e)
    else:
        logger.info("Система актуальна")
    return None