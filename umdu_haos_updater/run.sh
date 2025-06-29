#!/usr/bin/with-contenv bashio

# Логирование начала работы
bashio::log.info "Запуск UMDU HAOS Updater для K1..."

# Чтение конфигурации
UPDATE_INTERVAL=$(bashio::config 'update_check_interval')
AUTO_UPDATE=$(bashio::config 'auto_update')
BACKUP_BEFORE_UPDATE=$(bashio::config 'backup_before_update')

bashio::log.info "Интервал проверки обновлений: ${UPDATE_INTERVAL} секунд"
bashio::log.info "Автоматическое обновление: ${AUTO_UPDATE}"
bashio::log.info "Резервное копирование перед обновлением: ${BACKUP_BEFORE_UPDATE}"

# Функция проверки доступности supervisor API
check_supervisor_access() {
    if curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
       "http://supervisor/supervisor/info" > /dev/null 2>&1; then
        bashio::log.info "Доступ к Supervisor API получен"
        return 0
    else
        bashio::log.error "Нет доступа к Supervisor API"
        return 1
    fi
}

# Функция получения текущей версии HAOS
get_current_haos_version() {
    local version=$(curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
                   "http://supervisor/os/info" | jq -r '.data.version')
    echo "$version"
}

# Функция проверки обновлений
check_for_updates() {
    bashio::log.info "Проверка доступных обновлений HAOS для UMDU K1..."
    
    local current_version=$(get_current_haos_version)
    bashio::log.info "Текущая версия HAOS: ${current_version}"
    
    # TODO: Здесь будет логика проверки обновлений из репозитория UMDU
    # Пока просто логируем
    bashio::log.info "Проверка завершена"
}

# Проверка доступа к supervisor при запуске
if ! check_supervisor_access; then
    bashio::log.error "Невозможно получить доступ к Supervisor. Проверьте настройки add-on'а"
    exit 1
fi

# Основной цикл работы
while true; do
    check_for_updates
    
    bashio::log.info "Ожидание ${UPDATE_INTERVAL} секунд до следующей проверки..."
    sleep "${UPDATE_INTERVAL}"
done 