ARG BUILD_FROM
FROM $BUILD_FROM

# Установка необходимых пакетов для работы с системой и обновлениями
RUN \
  apk add --no-cache \
    bash \
    curl \
    wget \
    jq \
    ca-certificates

# Создание рабочей директории
WORKDIR /app

# Копирование скриптов
COPY run.sh /
RUN chmod a+x /run.sh

# Отключаем S6 overlay и используем простой bash
ENTRYPOINT []
CMD [ "/bin/bash", "/run.sh" ] 