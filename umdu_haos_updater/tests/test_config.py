"""Тесты для модуля config.py"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

from app.config import AddonConfig, CONFIG_PATH


class TestAddonConfig:
    """Тесты для класса AddonConfig"""

    def test_default_config(self):
        """Тест создания конфигурации с значениями по умолчанию"""
        config = AddonConfig()
        
        assert config.update_check_interval == 3600
        assert config.auto_update is False
        assert config.notifications is True
        assert config.mqtt_discovery is True
        assert config.mqtt_host is None
        assert config.mqtt_port is None
        assert config.mqtt_user is None
        assert config.mqtt_password is None
        assert config.debug is False

    def test_load_config_file_not_exists(self):
        """Тест загрузки когда файл конфигурации не существует"""
        with patch.object(Path, 'exists', return_value=False):
            config = AddonConfig.load()
            
        # Должны быть значения по умолчанию
        assert config.update_check_interval == 3600
        assert config.auto_update is False

    def test_load_config_from_file(self):
        """Тест загрузки конфигурации из файла"""
        test_config = {
            "update_check_interval": 1800,
            "auto_update": True,
            "notifications": False,
            "mqtt_discovery": False,
            "mqtt_host": "test-mqtt",
            "mqtt_port": 1884,
            "mqtt_user": "test_user",
            "mqtt_password": "test_pass",
            "debug": True
        }
        
        mock_file_content = json.dumps(test_config)
        
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'open', mock_open(read_data=mock_file_content)):
            config = AddonConfig.load()
        
        assert config.update_check_interval == 1800
        assert config.auto_update is True
        assert config.notifications is False
        assert config.mqtt_discovery is False
        assert config.mqtt_host == "test-mqtt"
        assert config.mqtt_port == 1884
        assert config.mqtt_user == "test_user"
        assert config.mqtt_password == "test_pass"
        assert config.debug is True

    def test_post_init_cleanup(self):
        """Тест очистки значений по умолчанию в __post_init__"""
        config = AddonConfig(
            mqtt_host="core-mosquitto",
            mqtt_port=1883
        )
        
        # После __post_init__ должны стать None
        assert config.mqtt_host is None
        assert config.mqtt_port is None

    def test_load_partial_config(self):
        """Тест загрузки частичной конфигурации"""
        test_config = {
            "auto_update": True,
            "mqtt_host": "custom-mqtt"
        }
        
        mock_file_content = json.dumps(test_config)
        
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'open', mock_open(read_data=mock_file_content)):
            config = AddonConfig.load()
        
        # Заданные значения
        assert config.auto_update is True
        assert config.mqtt_host == "custom-mqtt"
        
        # Значения по умолчанию для остальных
        assert config.update_check_interval == 3600
        assert config.notifications is True

    def test_load_invalid_json(self):
        """Тест обработки невалидного JSON"""
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'open', mock_open(read_data="invalid json")):
            with pytest.raises(json.JSONDecodeError):
                AddonConfig.load()

    def test_empty_string_values_become_none(self):
        """Тест что пустые строки становятся None"""
        test_config = {
            "mqtt_host": "",
            "mqtt_user": "",
            "mqtt_password": ""
        }
        
        mock_file_content = json.dumps(test_config)
        
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'open', mock_open(read_data=mock_file_content)):
            config = AddonConfig.load()
        
        assert config.mqtt_host is None
        assert config.mqtt_user is None
        assert config.mqtt_password is None

    def test_string_to_int_conversion(self):
        """Тест конвертации строк в числа"""
        test_config = {
            "update_check_interval": "1800",  # строка
            "mqtt_port": "1884"  # строка
        }
        
        mock_file_content = json.dumps(test_config)
        
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'open', mock_open(read_data=mock_file_content)):
            config = AddonConfig.load()
        
        assert config.update_check_interval == 1800
        assert config.mqtt_port == 1884

    # ------------------------------------------------------------------
    # Валидация значений
    # ------------------------------------------------------------------
    def test_invalid_interval_raises(self):
        """Тест валидации слишком маленького интервала"""
        with pytest.raises(ValueError, match="update_check_interval must be ≥ 60 seconds"):
            AddonConfig(update_check_interval=30)  # меньше 60

    def test_invalid_mqtt_port_raises(self):
        """Тест валидации неверного порта"""
        with pytest.raises(ValueError, match="mqtt_port must be between 1 and 65535"):
            AddonConfig(mqtt_port=70000)  # за пределами диапазона 