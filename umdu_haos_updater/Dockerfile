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
    mosquitto-clients \
    python3 \
    py3-pip

# Создание рабочей директории
WORKDIR /app

# Копирование зависимостей Python и установка
COPY requirements.txt /app/requirements.txt
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN pip3 install --no-cache-dir --no-warn-script-location -r /app/requirements.txt

# Копирование Python-кода
COPY app /app/app


# Отключаем S6 overlay и используем простой bash
ENTRYPOINT []
CMD [ "python3", "-u", "-m", "app.main" ] 