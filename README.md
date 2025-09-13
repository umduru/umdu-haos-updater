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
