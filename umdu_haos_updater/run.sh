#!/bin/bash

# Строгий режим (выходим при обращении к несуществующей переменной, ошибки пайпов ловим)
set -u
set -o pipefail

# Включаем алиасы внутри скрипта и добавляем метку времени ко всем echo
shopt -s expand_aliases
alias echo='builtin echo "$(date "+%Y-%m-%d %H:%M:%S")"'

# Проверяем наличие токена Supervisor
if [[ -z "${SUPERVISOR_TOKEN:-}" ]]; then
    echo "[ERROR] SUPERVISOR_TOKEN не установлен. Add-on не может общаться с Supervisor API."
    exit 1
fi

# Логирование начала работы
echo "[INFO] Запуск UMDU HAOS Updater для K1..."

# Чтение конфигурации из /data/options.json
CONFIG_FILE="/data/options.json"
UPDATE_INTERVAL=$(jq -r '.update_check_interval // 3600' "$CONFIG_FILE")
AUTO_UPDATE=$(jq -r '.auto_update // false' "$CONFIG_FILE")
BACKUP_BEFORE_UPDATE=$(jq -r '.backup_before_update // true' "$CONFIG_FILE")
NOTIFICATIONS=$(jq -r '.notifications // true' "$CONFIG_FILE")

echo "[INFO] Интервал проверки обновлений: ${UPDATE_INTERVAL} секунд"
echo "[INFO] Автоматическое обновление: ${AUTO_UPDATE}"
echo "[INFO] Резервное копирование перед обновлением: ${BACKUP_BEFORE_UPDATE}"
echo "[INFO] Уведомления: ${NOTIFICATIONS}"

# Global constants
SHARE_DIR="/share/umdu-haos-updater"

# Функция проверки доступности supervisor API
check_supervisor_access() {
    if curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
       "http://supervisor/supervisor/info" > /dev/null 2>&1; then
        echo "[INFO] Доступ к Supervisor API получен"
        return 0
    else
        echo "[ERROR] Нет доступа к Supervisor API"
        return 1
    fi
}

# Функция получения текущей версии HAOS
get_current_haos_version() {
    local version=$(curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
                   "http://supervisor/os/info" | jq -r '.data.version')
    command echo "$version"
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
            echo "[INFO] Уведомление отправлено в Home Assistant"
        else
            echo "[WARNING] Не удалось отправить уведомление в Home Assistant"
        fi
    fi
}

# Функция сравнения версий: возвращает 0, если $1 > $2
version_gt() {
    # Используем sort -V для корректной сортировки семантических номеров
    local v1="$1"
    local v2="$2"

    if [[ "$(printf '%s\n' "${v1}" "${v2}" | sort -V | head -n1)" != "${v1}" ]]; then
        # v1 выше v2
        return 0
    fi
    return 1
}

# Функция проверки обновлений
check_for_updates() {
    echo "[INFO] Проверка доступных обновлений HAOS для UMDU K1..."
    
    local current_version=$(get_current_haos_version)
    echo "[INFO] Текущая версия HAOS: ${current_version}"
    
    # Получение доступной версии из репозитория
    local timestamp=$(date +%s)
    local versions_url="https://raw.githubusercontent.com/umduru/umdu-haos-updater/main/versions.json?t=${timestamp}"
    local available_version=$(curl -s "${versions_url}" | jq -r '.hassos."umdu-k1"' 2>/dev/null)
    
    if [[ -z "${available_version}" || "${available_version}" == "null" ]]; then
        echo "[WARNING] Не удалось получить информацию о доступных версиях"
        return 1
    fi
    
    echo "[INFO] Доступная версия HAOS: ${available_version}"
    
    # Сравнение версий (обновление только на более новую)
    if [[ "${current_version}" == "${available_version}" ]]; then
        echo "[INFO] Система использует актуальную версию"
    elif version_gt "${available_version}" "${current_version}"; then
        echo "[INFO] Доступно обновление: ${current_version} -> ${available_version}"
        
        # Отправка уведомления
        send_notification \
            "UMDU HAOS Обновление доступно" \
            "Доступна новая версия Home Assistant OS для UMDU K1: ${available_version}. Текущая версия: ${current_version}."
        
        # Проверка режима обновления
        if [[ "${AUTO_UPDATE}" == "true" ]]; then
            echo "[INFO] Автоматическое обновление включено, загружаем и устанавливаем..."
            
            # Загрузка файла обновления
            if update_file_path=$(download_update_file "${available_version}"); then
                echo "[INFO] Начинаем установку..."
                install_update_file "${update_file_path}"
            else
                echo "[ERROR] Ошибка загрузки файла обновления"
            fi
        else
            echo "[INFO] Автоматическое обновление отключено"
            echo "[INFO] Доступна версия: ${available_version}. Текущая: ${current_version}"
            echo "[INFO] Для автоматической загрузки и установки включите 'auto_update: true' в настройках add-on"
            
            # Отправка уведомления о доступности обновления
            send_notification \
                "UMDU HAOS Обновление доступно" \
                "Доступна версия: ${available_version}. Для автоматической установки включите auto_update в настройках add-on."
        fi
    else
        echo "[INFO] Доступная версия (${available_version}) не выше текущей (${current_version}). Обновление не требуется."
    fi
    
    echo "[INFO] Проверка завершена"
}

# Функция загрузки файла обновления
download_update_file() {
    local available_version="$1"
    local update_url="https://github.com/umduru/umdu-haos-updater/releases/download/rauc/haos_umdu-k1-${available_version}.raucb"
    # Ensure shared directory exists
    mkdir -p "${SHARE_DIR}"
    local download_path="${SHARE_DIR}/haos_umdu-k1-${available_version}.raucb"
    
    # Проверка существования файла
    if [[ -f "${download_path}" ]]; then
        echo "[INFO] Файл обновления уже существует: ${download_path}" >&2
        command echo "${download_path}"
        return 0
    fi
    
    echo "[INFO] Загрузка обновления с ${update_url}..." >&2
    
    # --fail      : прервать по HTTP-ошибке
    # --retry 3   : три попытки
    # --retry-delay 5 : пауза 5 сек
    if curl -# -L --fail --retry 3 --retry-delay 5 -o "${download_path}" "${update_url}"; then
        echo "[INFO] Файл обновления загружен: ${download_path}" >&2
        command echo "${download_path}"
        return 0
    else
        echo "[ERROR] Не удалось загрузить файл обновления" >&2
        return 1
    fi
}

# Функция установки обновления через RAUC CLI
install_update_file() {
    local update_file="$1"
    
    if [[ ! -f "${update_file}" ]]; then
        echo "[ERROR] Файл обновления не найден: ${update_file}"
        return 1
    fi
    
    echo "[INFO] Начинаем установку обновления..."
    echo "[INFO] Файл: ${update_file}"
    
    # Установка через RAUC CLI
    if command -v rauc > /dev/null 2>&1; then
        echo "[INFO] RAUC CLI найден: $(which rauc)"
        echo "[INFO] Запускаем установку: rauc install ${update_file}"
        
        # Запуск с детальным выводом
        if rauc install "${update_file}" 2>&1; then
            rauc_exit_code=$?
            echo "[INFO] RAUC завершился с кодом: ${rauc_exit_code}"
            
            # Проверяем статус слотов после установки
            echo "[INFO] Статус слотов после установки:"
            rauc status 2>/dev/null || echo "[WARNING] Не удалось получить статус слотов"
            
            echo "[SUCCESS] Обновление успешно установлено!"
            # Удаляем установочный файл, чтобы не занимал место
            rm -f "${update_file}" || true
            install_success=true
        else
            rauc_exit_code=$?
            echo "[ERROR] RAUC завершился с ошибкой, код: ${rauc_exit_code}"
            echo "[INFO] Попытка получить статус слотов для диагностики:"
            rauc status 2>/dev/null || echo "[WARNING] Статус слотов недоступен"
            install_success=false
        fi
    else
        echo "[ERROR] RAUC CLI недоступен в PATH"
        echo "[DEBUG] Содержимое PATH: ${PATH}"
        echo "[DEBUG] Проверка /usr/bin/rauc: $(ls -la /usr/bin/rauc 2>/dev/null || echo 'не найден')"
        echo "[DEBUG] Проверка /sbin/rauc: $(ls -la /sbin/rauc 2>/dev/null || echo 'не найден')"
        install_success=false
    fi
    
    # Обработка результата
    if [[ "${install_success}" == "true" ]]; then
        echo "[INFO] Система будет перезагружена для применения обновления..."
        
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
        echo "[ERROR] Установка обновления не удалась"
        
        # Отправка уведомления об ошибке
        send_notification \
            "UMDU HAOS Ошибка обновления" \
            "Произошла ошибка при установке обновления Home Assistant OS. Проверьте логи add-on."
        
        return 1
    fi
}

# Проверка доступа к supervisor при запуске
if ! check_supervisor_access; then
    echo "[ERROR] Невозможно получить доступ к Supervisor. Проверьте настройки add-on'а"
    exit 1
fi

# Основной цикл работы
while true; do
    check_for_updates
    
    echo "[INFO] Ожидание ${UPDATE_INTERVAL} секунд до следующей проверки..."
    sleep "${UPDATE_INTERVAL}"
done 