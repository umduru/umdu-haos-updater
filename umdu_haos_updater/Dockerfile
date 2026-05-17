FROM ghcr.io/home-assistant/base:3.23

ARG BUILD_VERSION="0.0.0"
ARG BUILD_ARCH="aarch64"
ARG ALPINE_MIRROR="https://mirror.yandex.ru/mirrors/alpine"
ARG PIP_INDEX_URL="https://mirror.yandex.ru/pypi/web/simple"

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  io.hass.name="UMDU Home Assistant OS Updater" \
  io.hass.description="Home Assistant OS updater for umdu k1" \
  io.hass.url="https://github.com/umduru/umdu-haos-updater" \
  org.opencontainers.image.title="UMDU Home Assistant OS Updater" \
  org.opencontainers.image.description="Home Assistant OS updater for umdu k1" \
  org.opencontainers.image.source="https://github.com/umduru/umdu-haos-updater"

# Установка необходимых пакетов для работы с системой и обновлениями
# Примечание: пакет rauc отсутствует в стабильных репозиториях Alpine, поэтому
# устанавливаем его из edge/testing. Остальные пакеты — из стабильного репо базового образа.
RUN printf '%s\n' \
    "${ALPINE_MIRROR}/v3.23/main" \
    "${ALPINE_MIRROR}/v3.23/community" \
    > /etc/apk/repositories && \
  apk add --no-cache \
    ca-certificates \
    dbus \
    python3 \
    py3-pip && \
  apk add --no-cache \
    --repository="${ALPINE_MIRROR}/edge/testing" \
    rauc

# Создание рабочей директории
WORKDIR /app

# Копирование зависимостей Python и установка
COPY requirements.txt /app/requirements.txt
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN pip3 install \
    --no-cache-dir \
    --no-warn-script-location \
    --index-url "${PIP_INDEX_URL}" \
    -r /app/requirements.txt

# Копирование Python-кода
COPY app /app/app


# Отключаем S6 overlay и используем простой bash
ENTRYPOINT []
CMD [ "python3", "-u", "-m", "app.main" ] 
