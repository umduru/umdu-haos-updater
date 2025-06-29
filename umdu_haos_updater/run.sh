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
        
        # Загрузка файла обновления
        if update_file_path=$(download_update_file "${available_version}"); then
            
            # Проверка режима обновления
            if [[ "${AUTO_UPDATE}" == "true" ]]; then
                bashio::log.info "Автоматическое обновление включено, начинаем установку..."
                install_update_file "${update_file_path}"
            else
                bashio::log.info "Файл обновления загружен и готов к ручной установке"
                bashio::log.info "Местоположение файла: ${update_file_path}"
                bashio::log.info "Для автоматической установки включите 'auto_update: true' в настройках add-on"
                
                # Отправка уведомления о готовности к ручной установке
                send_notification \
                    "UMDU HAOS Файл обновления готов" \
                    "Файл обновления загружен: ${available_version}. Для автоматической установки включите auto_update в настройках add-on."
            fi
        else
            bashio::log.error "Ошибка загрузки файла обновления"
        fi
    fi
    
    bashio::log.info "Проверка завершена"
}

# Функция загрузки файла обновления
download_update_file() {
    local available_version="$1"
    local update_url="https://github.com/umduru/umdu-haos-updater/releases/download/rauc/haos_umdu-k1-${available_version}.raucb"
    local download_path="/tmp/haos_umdu-k1-${available_version}.raucb"
    
    # Проверка существования файла
    if [[ -f "${download_path}" ]]; then
        bashio::log.info "Файл обновления уже существует: ${download_path}"
        echo "${download_path}"
        return 0
    fi
    
    bashio::log.info "Загрузка обновления с ${update_url}..."
    
    if curl -L -o "${download_path}" "${update_url}"; then
        bashio::log.info "Файл обновления загружен: ${download_path}"
        echo "${download_path}"
        return 0
    else
        bashio::log.error "Не удалось загрузить файл обновления"
        return 1
    fi
}

# Функция установки обновления через RAUC CLI
install_update_file() {
    local update_file="$1"
    
    if [[ ! -f "${update_file}" ]]; then
        bashio::log.error "Файл обновления не найден: ${update_file}"
        return 1
    fi
    
    bashio::log.info "Начинаем установку обновления..."
    bashio::log.info "Файл: ${update_file}"
    
    # Попробуем сначала RAUC CLI
    if command -v rauc > /dev/null 2>&1; then
        bashio::log.info "Используем RAUC CLI..."
        if rauc install "${update_file}"; then
            bashio::log.info "Обновление успешно установлено через RAUC CLI!"
            install_success=true
        else
            bashio::log.warning "RAUC CLI не удалось, пробуем D-Bus API..."
            install_success=false
        fi
    else
        bashio::log.info "RAUC CLI недоступен, используем D-Bus API..."
        install_success=false
    fi
    
    # Если RAUC CLI не сработал, пробуем D-Bus
    if [[ "${install_success}" != "true" ]]; then
        if command -v busctl > /dev/null 2>&1; then
            bashio::log.info "Установка через D-Bus API..."
            if busctl call de.pengutronix.rauc / de.pengutronix.rauc.Installer Install s "${update_file}"; then
                bashio::log.info "Обновление успешно установлено через D-Bus API!"
                install_success=true
            else
                bashio::log.error "Ошибка установки через D-Bus API"
                install_success=false
            fi
        else
            bashio::log.error "D-Bus API также недоступен"
            install_success=false
        fi
    fi
    
    # Обработка результата
    if [[ "${install_success}" == "true" ]]; then
        bashio::log.info "Система будет перезагружена для применения обновления..."
        
        # Отправка уведомления об успешной установке
        send_notification \
            "UMDU HAOS Обновление установлено" \
            "Обновление Home Assistant OS успешно установлено. Система перезагружается..."
        
        # Перезагрузка системы через Supervisor API
        sleep 5
        curl -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
             "http://supervisor/host/reboot"
        return 0
    else
        bashio::log.error "Все методы установки не удались"
        
        # Отправка уведомления об ошибке
        send_notification \
            "UMDU HAOS Ошибка обновления" \
            "Произошла ошибка при установке обновления Home Assistant OS. Проверьте логи add-on."
        
        return 1
    fi
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