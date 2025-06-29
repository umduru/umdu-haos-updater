ARG BUILD_FROM
FROM $BUILD_FROM

# Установка необходимых пакетов для работы с системой и обновлениями
RUN echo "http://dl-cdn.alpinelinux.org/alpine/edge/testing" >> /etc/apk/repositories && \
  apk add --no-cache \
    bash \
    curl \
    wget \
    jq \
    ca-certificates \
    dbus \
    rauc \
    mosquitto-clients

# Создание рабочей директории
WORKDIR /app

# Копирование скриптов
COPY run.sh /
RUN chmod a+x /run.sh

# Отключаем S6 overlay и используем простой bash
ENTRYPOINT []
CMD [ "/bin/bash", "/run.sh" ] 