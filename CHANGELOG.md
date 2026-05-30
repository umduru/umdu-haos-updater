# Changelog

## Unreleased

- Добавлена публикация готового aarch64 Docker-образа в GHCR и настройка `image` в конфиге дополнения, чтобы Supervisor скачивал образ вместо локальной сборки на устройстве.
- Исправлена локальная сборка в актуальном Home Assistant Supervisor: Dockerfile больше не зависит от `BUILD_FROM` и использует официальный base image `ghcr.io/home-assistant/base:3.23`.
- Добавлены build labels для `BUILD_VERSION` и `BUILD_ARCH`.
- Уменьшен набор Alpine-пакетов в Docker-образе до реально используемых.
- Документация дополнена командами проверки сборки и описанием требуемых прав.

## 1.0.0

- Первый релиз.
