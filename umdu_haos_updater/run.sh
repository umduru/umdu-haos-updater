#!/bin/bash

# Строгий режим (выходим при обращении к несуществующей переменной, ошибки пайпов ловим)
set -u
set -o pipefail

# Включаем алиасы внутри скрипта и добавляем метку времени ко всем echo
shopt -s expand_aliases
alias echo='builtin echo "$(date "+%Y-%m-%d %H:%M:%S")"'

# Функция вывода отладочных сообщений
log_debug() {
    if [[ "$DEBUG" == "true" ]]; then
        echo "[DEBUG] $*"
    fi
}

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
DEBUG=$(jq -r '.debug // false' "$CONFIG_FILE")

# Настройки MQTT из options.json (префикс CFG_ — чтобы не перекрывать финальные переменные)
CFG_MQTT_DISCOVERY=$(jq -r '.mqtt_discovery // true' "$CONFIG_FILE")
CFG_MQTT_HOST=$(jq -r '.mqtt_host // "core-mosquitto"' "$CONFIG_FILE")
CFG_MQTT_PORT=$(jq -r '.mqtt_port // 1883' "$CONFIG_FILE")
CFG_MQTT_USER=$(jq -r '.mqtt_user // empty' "$CONFIG_FILE")
CFG_MQTT_PASSWORD=$(jq -r '.mqtt_password // empty' "$CONFIG_FILE")

# Инициализируем финальные переменные MQTT значениями из конфигурации
MQTT_DISCOVERY="$CFG_MQTT_DISCOVERY"

# Значения по умолчанию считаем "пустыми", чтобы их можно было заменить
[[ "$CFG_MQTT_HOST" == "core-mosquitto" ]] && CFG_MQTT_HOST=""
[[ "$CFG_MQTT_PORT" == "1883" ]] && CFG_MQTT_PORT=""

MQTT_HOST="$CFG_MQTT_HOST"
MQTT_PORT="$CFG_MQTT_PORT"
MQTT_USER="$CFG_MQTT_USER"
MQTT_PASSWORD="$CFG_MQTT_PASSWORD"

echo "[INFO] Интервал проверки обновлений: ${UPDATE_INTERVAL} секунд"
echo "[INFO] Автоматическое обновление: ${AUTO_UPDATE}"
echo "[INFO] Резервное копирование перед обновлением: ${BACKUP_BEFORE_UPDATE}"
echo "[INFO] Уведомления: ${NOTIFICATIONS}"
echo "[INFO] MQTT Discovery: ${MQTT_DISCOVERY}"

# Проверяем наличие mosquitto_pub, иначе отключаем discovery
if [[ "$MQTT_DISCOVERY" == "true" && ! $(command -v mosquitto_pub) ]]; then
   echo "[WARNING] mosquitto_pub не найден в контейнере — MQTT discovery будет отключён"
   MQTT_DISCOVERY="false"
fi

# Global constants
SHARE_DIR="/share/umdu-haos-updater"

# Переменная для хранения последней доступной версии
LAST_AVAILABLE_VERSION=""

# --- MQTT helper functions (должны быть определены ДО их использования) ---
publish_mqtt() {
    local topic="$1"; shift
    local payload="$1"
    if [[ "$MQTT_DISCOVERY" == "true" ]]; then
        if ! mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" \
            ${MQTT_USER:+-u "$MQTT_USER"} ${MQTT_PASSWORD:+-P "$MQTT_PASSWORD"} \
            -r -t "$topic" -m "$payload" > /dev/null 2>&1; then
            echo "[WARNING] MQTT publish to $topic failed (отключаю discovery до перезапуска)"
            MQTT_DISCOVERY="false"
        fi
    fi
}

publish_discovery() {
    if [[ "$MQTT_DISCOVERY" != "true" ]]; then return; fi
    local disc_topic="homeassistant/update/umdu_haos_k1/config"
    local disc_payload='{"name":"Home Assistant OS for UMDU K1","uniq_id":"umdu_haos_k1_os","stat_t":"umdu/haos_updater/state","json_attr_t":"umdu/haos_updater/state","cmd_t":"umdu/haos_updater/cmd","pl_inst":"install","ent_cat":"diagnostic"}'
    publish_mqtt "$disc_topic" "$disc_payload"
}

publish_state() {
    local installed="$1"; local latest="$2"
    local state_payload="{\"installed_version\":\"$installed\",\"latest_version\":\"$latest\"}"
    publish_mqtt "umdu/haos_updater/state" "$state_payload"
}

handle_mqtt_commands() {
    if [[ "$MQTT_DISCOVERY" != "true" ]]; then return; fi
    echo "[INFO] Ожидание MQTT-команд на topic umdu/haos_updater/cmd…"
    mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" \
        ${MQTT_USER:+-u "$MQTT_USER"} ${MQTT_PASSWORD:+-P "$MQTT_PASSWORD"} \
        -t "umdu/haos_updater/cmd" 2>/tmp/mqtt_sub_err.log |
    while read -r cmd; do
        log_debug "MQTT cmd recv: $cmd"
        if [[ "$cmd" == "install" ]]; then
            # Берём последнюю строку файла, отбираем последний "токен" (чистая версия)
            avail_ver=$(awk '{print $NF}' /tmp/umdu_last_ver 2>/dev/null || true)
            if [[ -z "$avail_ver" ]]; then
                echo "[ERROR] Неизвестна доступная версия — запустите проверку обновлений и попробуйте снова"
                continue
            fi
            echo "[INFO] Получена команда install через MQTT; версия к установке: $avail_ver"
            if update_file_path=$(download_update_file "$avail_ver"); then
                install_update_file "$update_file_path"
            else
                echo "[ERROR] Не удалось загрузить файл обновления после команды install"
            fi
        else
            echo "[WARNING] Неизвестная команда через MQTT: $cmd"
        fi
    done &

    # Проверим, запустился ли mosquitto_sub (файл ошибки не пуст – проблема подключения)
    sleep 2
    if [[ -s /tmp/mqtt_sub_err.log ]]; then
        echo "[ERROR] Ошибка подключения для mosquitto_sub:"; cat /tmp/mqtt_sub_err.log
        MQTT_DISCOVERY="false"
    fi
}

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
    LAST_AVAILABLE_VERSION="$available_version"
    # Записываем чистое значение без таймштампа (printf обходит алиас echo)
    printf '%s' "$available_version" > /tmp/umdu_last_ver
    
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
    publish_state "$current_version" "$available_version"
}

# Функция загрузки файла обновления
download_update_file() {
    local available_version="$1"
    local update_url="https://github.com/umduru/umdu-haos-updater/releases/download/rauc/haos_umdu-k1-${available_version}.raucb"
    # Ensure shared directory exists
    mkdir -p "${SHARE_DIR}"
    # Удаляем старые бандлы, чтобы не смешивались версии
    find "${SHARE_DIR}" -type f -name 'haos_umdu-k1-*.raucb' ! -name "haos_umdu-k1-${available_version}.raucb" -delete || true
    local download_path="${SHARE_DIR}/haos_umdu-k1-${available_version}.raucb"
    
    # Хостовой путь (видимый RAUC) совпадает с /share, только префикс /mnt/data/supervisor
    host_share_dir="/mnt/data/supervisor/share/umdu-haos-updater"
    host_path="${host_share_dir}/haos_umdu-k1-${available_version}.raucb"

    # Если файл уже есть в контейнере
    if [[ -f "${download_path}" ]]; then
        echo "[INFO] Файл обновления уже существует: ${download_path}" >&2
        # Обеспечим наличие копии для RAUC
        mkdir -p "${host_share_dir}"
        echo "[INFO] Копирую файл в ${host_path} для доступа RAUC" >&2
        # cp убран, RAUC видит файл напрямую через /mnt/data/supervisor/share
        command echo "${download_path}"
        return 0
    fi
    
    echo "[INFO] Загрузка обновления с ${update_url}..." >&2
    
    # --fail      : прервать по HTTP-ошибке
    # --retry 3   : три попытки
    # --retry-delay 5 : пауза 5 сек
    if curl -# -L --fail --retry 3 --retry-delay 5 -o "${download_path}" "${update_url}"; then
        echo "[INFO] Файл обновления загружен: ${download_path}" >&2
        # Копируем в /data/share для RAUC
        mkdir -p "${host_share_dir}"
        echo "[INFO] Копирую файл в ${host_path} для доступа RAUC" >&2
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
    
    # RAUC-daemon на хосте ожидает файл внутри /data/share
    local host_update_file="/mnt/data/supervisor/share${update_file#/share}"
    
    echo "[INFO] Начинаем установку обновления..."
    echo "[INFO] Файл: ${host_update_file}"
    
    # Установка через RAUC CLI
    if command -v rauc > /dev/null 2>&1; then
        echo "[INFO] RAUC CLI найден: $(which rauc)"
        echo "[INFO] Запускаем установку: rauc install ${host_update_file}"
        
        # Запуск с детальным выводом
        if rauc install "${host_update_file}" 2>&1; then
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

# --- Fallback: переменные окружения Home Assistant ---
if [[ "$MQTT_DISCOVERY" == "true" ]]; then
    [[ -z "$MQTT_HOST" && -n "${HASSIO_MQTT_HOST:-${HASSIO_MQTT_ADDRESS:-}}" ]] && MQTT_HOST="${HASSIO_MQTT_HOST:-$HASSIO_MQTT_ADDRESS}"
    [[ -z "$MQTT_PORT" && -n "${HASSIO_MQTT_PORT:-}" ]] && MQTT_PORT="$HASSIO_MQTT_PORT"
    [[ -z "$MQTT_USER" && -n "${HASSIO_MQTT_USERNAME:-${HASS_MQTT_USERNAME:-}}" ]] && MQTT_USER="${HASSIO_MQTT_USERNAME:-$HASS_MQTT_USERNAME}"
    [[ -z "$MQTT_PASSWORD" && -n "${HASSIO_MQTT_PASSWORD:-${HASS_MQTT_PASSWORD:-}}" ]] && MQTT_PASSWORD="${HASSIO_MQTT_PASSWORD:-$HASS_MQTT_PASSWORD}"
fi

# --- Автоподстановка MQTT параметров из Supervisor ---
if [[ "$MQTT_DISCOVERY" == "true" ]]; then
    # Обращаемся к Supervisor API v2 (/services/mqtt)
    sup_resp=$(curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/services/mqtt 2>/dev/null) || true

    # Всегда логируем ответ в режиме DEBUG, чтобы упростить диагностику
    log_debug "/services/mqtt: $sup_resp"

    # Пытаемся вынуть данные, не полагаясь на поле result, так как у некоторых версий Supervisоr оно может отсутствовать
    sup_host=$(printf '%s' "$sup_resp" | jq -r '.data.host // empty' 2>/dev/null || echo "")
    sup_port=$(printf '%s' "$sup_resp" | jq -r '.data.port // empty' 2>/dev/null || echo "")
    sup_user=$(printf '%s' "$sup_resp" | jq -r '.data.username // empty' 2>/dev/null || echo "")
    sup_pass=$(printf '%s' "$sup_resp" | jq -r '.data.password // empty' 2>/dev/null || echo "")

    if [[ -n "$sup_host" ]]; then
        # Подставляем, только если переменная ещё не заполнена
        [[ -z "$MQTT_HOST" ]] && MQTT_HOST="$sup_host"
        [[ -z "$MQTT_PORT" && -n "$sup_port" ]] && MQTT_PORT="$sup_port"
        [[ -z "$MQTT_PORT" && -z "$sup_port" ]] && MQTT_PORT="1883"
        [[ -z "$MQTT_USER" && -n "$sup_user" ]] && MQTT_USER="$sup_user"
        [[ -z "$MQTT_PASSWORD" && -n "$sup_pass" ]] && MQTT_PASSWORD="$sup_pass"
        echo "[INFO] MQTT параметры Supervisor: $MQTT_HOST:$MQTT_PORT (user: $MQTT_USER)"
        log_debug "sup_host=$sup_host sup_port=$sup_port sup_user=$sup_user"
    elif [[ -z "$MQTT_HOST" ]]; then
        # Fallback к устаревшему API (общий список сервисов)
        old_json=$(curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/services 2>/dev/null | jq -c '.. | objects | select(.service? == "mqtt")' | head -n1 ) || true
        if [[ -n "$old_json" ]]; then
            sup_host=$(printf '%s' "$old_json" | jq -r '.host // empty')
            sup_port=$(printf '%s' "$old_json" | jq -r '.port // 1883')
            sup_user=$(printf '%s' "$old_json" | jq -r '.username // empty')
            sup_pass=$(printf '%s' "$old_json" | jq -r '.password // empty')

            [[ -z "$MQTT_HOST" && -n "$sup_host" ]] && MQTT_HOST="$sup_host"
            [[ -z "$MQTT_PORT" && -n "$sup_port" ]] && MQTT_PORT="$sup_port"
            [[ -z "$MQTT_PORT" && -z "$sup_port" ]] && MQTT_PORT="1883"
            [[ -z "$MQTT_USER" && -n "$sup_user" ]] && MQTT_USER="$sup_user"
            [[ -z "$MQTT_PASSWORD" && -n "$sup_pass" ]] && MQTT_PASSWORD="$sup_pass"
            echo "[INFO] MQTT параметры Supervisor (v1 API): $MQTT_HOST:$MQTT_PORT (user: $MQTT_USER)"
            log_debug "sup_host=$sup_host sup_port=$sup_port sup_user=$sup_user"
        else
            echo "[WARNING] Supervisor не вернул данные mqtt; discovery будет отключён"
            MQTT_DISCOVERY="false"
        fi
    fi
fi

# --- Финальный резервы по MQTT ---
if [[ "$MQTT_DISCOVERY" == "true" ]]; then
    [[ -z "$MQTT_PORT" ]] && MQTT_PORT="1883"
    if [[ -z "$MQTT_HOST" ]]; then
        echo "[WARNING] MQTT_HOST не определён — discovery будет отключён"
        MQTT_DISCOVERY="false"
    fi
fi

# Инициализируем discovery и слушаем команды (после всех фоллбэков)
publish_discovery
handle_mqtt_commands

# Основной цикл работы
while true; do
    check_for_updates
    
    echo "[INFO] Ожидание ${UPDATE_INTERVAL} секунд до следующей проверки..."
    echo "-----------------------------"
    sleep "${UPDATE_INTERVAL}"
done 