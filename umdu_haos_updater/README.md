# UMDU Home Assistant OS Updater

Автоматическое обновление Home Assistant OS для устройства umdu k1.

### Как это работает

- Проверка наличия обновлений выполняется раз в 24 часа.
- В Home Assistant появляется сущность обновления «Home Assistant OS for umdu k1», отображающая текущую и доступную версии.
- При включенном `auto_update` дополнение автоматически скачает и установит обновление. Если параметр выключен, будет показано уведомление, установку можно запустить из интерфейса HA.
- После успешной установки потребуется перезагрузка системы (об этом появится уведомление).

### Параметры конфигурации

- auto_update — автоустановка найденных обновлений (по умолчанию: false)
- notifications — отправка уведомлений о статусе и ошибках в HA (true)
- debug — детальное логирование для диагностики (false)
- dev_channel — получение версий из канала предварительных сборок (false)
- mqtt_host / mqtt_port / mqtt_user / mqtt_password — параметры MQTT. Обычно их можно не заполнять: будут использованы настройки MQTT из Supervisor. Заполняйте только при использовании внешнего брокера.

### Сборка

Dockerfile использует официальный multi-arch base image Home Assistant `ghcr.io/home-assistant/base:3.23` напрямую. `BUILD_FROM` не нужен и не передается Supervisor начиная с актуального BuildKit-based процесса сборки.

Локальная проверка:

```bash
docker buildx build . \
  --file Dockerfile \
  --platform linux/arm64 \
  --pull \
  --build-arg BUILD_VERSION=1.0.2 \
  --build-arg BUILD_ARCH=aarch64 \
  --tag local/aarch64-addon-umdu_haos_updater:1.0.2 \
  --load
```

### Права

- `hassio_api: true` / `hassio_role: admin` — совместимый доступ к Supervisor API для версии HAOS и параметров MQTT.
- `homeassistant_api: true` — отправка уведомлений в Home Assistant.
- `host_dbus: true` — запуск RAUC-установки через host D-Bus.
- `map: share` — хранение скачанного RAUC bundle в `/share/umdu-haos-updater`.
- Ingress не включен, веб-интерфейс не предоставляется.
- `privileged`, `full_access`, `host_network`, `docker_api` и прямой доступ к системным каталогам/устройствам не используются.

Все скачивания идут по HTTPS. При наличии `sha256` в manifest версии скачанный RAUC bundle проверяется перед установкой; RAUC также проверяет подпись bundle на этапе установки.
