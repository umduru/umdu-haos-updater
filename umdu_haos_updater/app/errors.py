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