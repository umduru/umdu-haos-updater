#!/usr/bin/with-contenv bashio

# Логирование начала работы
bashio::log.info "Запуск UMDU HAOS Updater для K1..."

# Чтение конфигурации
UPDATE_INTERVAL=$(bashio::config 'update_check_interval')
AUTO_UPDATE=$(bashio::config 'auto_update')
BACKUP_BEFORE_UPDATE=$(bashio::config 'backup_before_update')
NOTIFICATIONS=$(bashio::config 'notifications')

bashio::log.info "Интервал проверки обновлений: ${UPDATE_INTERVAL} секунд"
bashio::log.info "Автоматическое обновление: ${AUTO_UPDATE}"
bashio::log.info "Резервное копирование перед обновлением: ${BACKUP_BEFORE_UPDATE}"
bashio::log.info "Уведомления: ${NOTIFICATIONS}"

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

# Функция отправки уведомления в Home Assistant
send_notification() {
    local title="$1"
    local message="$2"
    
    if [[ "${NOTIFICATIONS}" == "true" ]]; then
        local notification_data=$(cat <<EOF
{
  "title": "${title}",
  "message": "${message}",
  "notification_id": "umdu_haos_updater"
}
EOF
)
        
        if curl -s -X POST \
           -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
           -H "Content-Type: application/json" \
           -d "${notification_data}" \
           "http://supervisor/core/api/services/persistent_notification/create" > /dev/null 2>&1; then
            bashio::log.info "Уведомление отправлено в Home Assistant"
        else
            bashio::log.warning "Не удалось отправить уведомление в Home Assistant"
        fi
    fi
}

# Функция проверки обновлений
check_for_updates() {
    bashio::log.info "Проверка доступных обновлений HAOS для UMDU K1..."
    
    local current_version=$(get_current_haos_version)
    bashio::log.info "Текущая версия HAOS: ${current_version}"
    
    # Получение доступной версии из репозитория
    local timestamp=$(date +%s)
    local versions_url="https://raw.githubusercontent.com/umduru/umdu-haos-updater/main/versions.json?t=${timestamp}"
    local available_version=$(curl -s "${versions_url}" | jq -r '.hassos."umdu-k1"' 2>/dev/null)
    
    if [[ -z "${available_version}" || "${available_version}" == "null" ]]; then
        bashio::log.warning "Не удалось получить информацию о доступных версиях"
        return 1
    fi
    
    bashio::log.info "Доступная версия HAOS: ${available_version}"
    
    # Сравнение версий
    if [[ "${current_version}" == "${available_version}" ]]; then
        bashio::log.info "Система использует актуальную версию"
    else
        bashio::log.info "Доступно обновление: ${current_version} -> ${available_version}"
        
        # Отправка уведомления
        send_notification \
            "UMDU HAOS Обновление доступно" \
            "Доступна новая версия Home Assistant OS для UMDU K1: ${available_version}. Текущая версия: ${current_version}."
        
        # TODO: Добавить логику обновления когда будет готова
    fi
    
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