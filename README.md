# UMDU Home Assistant OS Updater

Автоматическое обновление Home Assistant OS для umdu k1.

## Описание

Дополнение автоматически отслеживает доступность новых версий Home Assistant OS для umdu k1 и может устанавливать их без вмешательства пользователя. Проверка обновлений происходит каждые 24 часа. При обнаружении новой версии система может автоматически загрузить и установить обновление (если включена соответствующая опция) или просто уведомить пользователя через интерфейс Home Assistant. Дополнение интегрируется с MQTT для предоставления информации о состоянии обновлений и возможности управления процессом установки.

## Установка

Добавьте этот репозиторий в Home Assistant Supervisor:

[![Добавить репозиторий](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fumduru%2Fumdu-haos-updater)

Или добавьте репозиторий вручную:
1. Откройте Home Assistant
2. Перейдите в Supervisor → Add-on Store
3. Нажмите на три точки в правом верхнем углу
4. Выберите "Repositories"
5. Добавьте URL: `https://github.com/umduru/umdu-haos-updater`

## Конфигурация

- **auto_update**: Автоматическая установка обновлений без подтверждения пользователя
- **notifications**: Отправка уведомлений в Home Assistant о статусе обновлений и ошибках
- **debug**: Включение подробного логирования для диагностики проблем
- **mqtt_***: Параметры подключения к MQTT брокеру для интеграции с Home Assistant