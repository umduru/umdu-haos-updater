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
    """Единообразно логирует и поднимает сетевую ошибку.

    Используется в сетевых утилитах (например, загрузка метаданных),
    где любые ошибки запросов трактуются как NetworkError.
    """
    logger.exception("Не удалось %s", context)
    raise NetworkError(f"Failed to {context}") from e
