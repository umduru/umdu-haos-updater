# UMDU Home Assistant OS Updater

Add-on для обновления форка Home Assistant OS для UMDU K1.

## Описание

Этот add-on предназначен для автоматической проверки и обновления специальной версии Home Assistant OS, оптимизированной для устройства UMDU K1.

## Архитектура

- aarch64 (UMDU K1)

## Конфигурация

- `update_check_interval`: Интервал проверки обновлений в секундах (300-86400)
- `auto_update`: Автоматическое применение обновлений (true/false)
- `backup_before_update`: Создание резервной копии перед обновлением (true/false) 