class UpdaterError(Exception):
    """Базовый класс всех ошибок UMDU-Updater."""


class NetworkError(UpdaterError):
    """Ошибки сетевого уровня (timeout, DNS, HTTP)."""


class DownloadError(UpdaterError):
    """Ошибки при загрузке RAUC-бандла."""


class InstallError(UpdaterError):
    """Ошибки процесса RAUC-install."""


class SupervisorError(UpdaterError):
    """Ошибки взаимодействия с Supervisor API."""


def handle_request_error(e: Exception, context: str, logger) -> None:
    """Общая обработка ошибок HTTP-запросов."""
    import requests
    logger.exception("Не удалось %s", context)
    if isinstance(e, requests.RequestException):
        raise NetworkError(f"Failed to {context}") from e
    raise DownloadError(f"Error {context}") from e