# UMDU Home Assistant OS Updater

Дополнение для автоматического обновления Home Assistant OS на устройстве umdu k1.

## Как это работает

- Проверяет доступность обновлений раз в 24 часа.
- В Home Assistant появляется сущность обновления “Home Assistant OS for umdu k1”, показывающая текущую и доступную версии.
- Если включен `auto_update`, дополнение автоматически скачает и установит обновление. Иначе — только уведомит и позволит установить из интерфейса HA.
- После успешной установки требуется перезагрузка системы (уведомление появится в HA).

## Установка

Добавьте этот репозиторий в Home Assistant Supervisor:

[![Добавить репозиторий](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fumduru%2Fumdu-haos-updater)

Или добавьте репозиторий вручную:
1. Откройте Home Assistant
2. Перейдите в Supervisor → Add-on Store
3. Нажмите на три точки в правом верхнем углу
4. Выберите «Repositories»
5. Добавьте URL: `https://github.com/umduru/umdu-haos-updater`

## Параметры конфигурации

- auto_update: Включить автоустановку найденных обновлений (по умолчанию: false).
- notifications: Отправлять уведомления о статусе и ошибках в HA (true).
- debug: Подробные логи для диагностики (false).
- dev_channel: Получать версии из канала предварительных сборок (false).
- mqtt_host / mqtt_port / mqtt_user / mqtt_password: Параметры MQTT. Обычно можно оставить пустыми — будут использованы настройки сервиса MQTT из Supervisor. Указывайте значения, только если используете внешний брокер.

## Сборка и проверка

Дополнение собирается из каталога `umdu_haos_updater`. Dockerfile не требует `BUILD_FROM`: базовый образ задан явно как официальный multi-arch образ Home Assistant `ghcr.io/home-assistant/base:3.23`, который поддерживает `linux/arm64`.

Локальная проверка сборки, близкая к команде Supervisor:

```bash
cd umdu_haos_updater
docker buildx build . \
  --file Dockerfile \
  --platform linux/arm64 \
  --pull \
  --build-arg BUILD_VERSION=1.0.0 \
  --build-arg BUILD_ARCH=aarch64 \
  --tag local/aarch64-addon-umdu_haos_updater:1.0.0 \
  --load
```

Если локальный Docker не может загрузить cross-platform образ через `--load`, проверьте хотя бы синтаксис и удаленную сборку без загрузки:

```bash
cd umdu_haos_updater
docker buildx imagetools inspect ghcr.io/home-assistant/base:3.23
docker buildx build . \
  --file Dockerfile \
  --platform linux/arm64 \
  --pull \
  --build-arg BUILD_VERSION=1.0.0 \
  --build-arg BUILD_ARCH=aarch64 \
  --tag local/aarch64-addon-umdu_haos_updater:1.0.0
```

Для проверки в Home Assistant добавьте репозиторий, откройте карточку дополнения в Supervisor / Apps, нажмите Install и проверьте лог сборки Supervisor. В команде сборки не должен появляться `--build-arg BUILD_FROM`, и ошибка `base name ($BUILD_FROM) should not be blank` не должна возникать.

## Права и безопасность

- `arch: [aarch64]` — целевая архитектура устройства umdu k1.
- `ingress` не включен: у дополнения нет веб-интерфейса и оно не слушает HTTP-порт.
- `hassio_api: true` и `hassio_role: admin` нужны для совместимого доступа к Supervisor API: чтения версии HAOS через `/os/info` и получения параметров MQTT-сервиса.
- `homeassistant_api: true` нужен для уведомлений в Home Assistant через внутренний API-прокси Supervisor.
- `host_dbus: true` нужен для запуска `rauc install` через host D-Bus.
- Не используются `privileged`, `full_access`, `host_network`, `docker_api`, доступ к `/dev`, `/boot`, `/sys` или `/proc`.
- Обновления скачиваются только по HTTPS. Если в manifest версии указан `sha256`, файл RAUC bundle проверяется до установки; сам RAUC дополнительно проверяет подпись bundle при установке.
