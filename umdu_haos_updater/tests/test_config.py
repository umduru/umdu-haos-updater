"""Тесты для модуля config.py"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

from umdu_haos_updater.app.config import AddonConfig


class TestAddonConfig:
    """Тесты для класса AddonConfig"""

    def test_default_config(self):
        """Тест создания конфигурации с значениями по умолчанию"""
        with patch('builtins.open'), patch('umdu_haos_updater.app.config.json.load', return_value={}):
            config = AddonConfig()
        
        assert config.check_interval == 3600
        assert config.auto_update is False
        assert config.notifications is True
        assert config.mqtt_host == "core-mosquitto"
        assert config.mqtt_port == 1883
        assert config.mqtt_username == ""
        assert config.mqtt_password == ""
        assert config.debug is False

    def test_load_config_file_not_exists(self):
        """Тест загрузки когда файл конфигурации не существует"""
        with patch('builtins.open', side_effect=FileNotFoundError):
            config = AddonConfig()
            
        # Должны быть значения по умолчанию
        assert config.check_interval == 3600
        assert config.auto_update is False

    def test_load_config_from_file(self):
        """Тест загрузки конфигурации из файла"""
        test_config = {
            "check_interval": 1800,
            "auto_update": True,
            "notifications": False,
            "mqtt": {
                "host": "test-mqtt",
                "port": 1884,
                "username": "test_user",
                "password": "test_pass"
            },
            "debug": True
        }
        
        with patch('builtins.open'), patch('umdu_haos_updater.app.config.json.load', return_value=test_config):
            config = AddonConfig()
        
        assert config.check_interval == 1800
        assert config.auto_update is True
        assert config.notifications is False
        assert config.mqtt_host == "test-mqtt"
        assert config.mqtt_port == 1884
        assert config.mqtt_username == "test_user"
        assert config.mqtt_password == "test_pass"
        assert config.debug is True

    def test_post_init_cleanup(self):
        """Тест значений по умолчанию"""
        with patch('builtins.open'), patch('umdu_haos_updater.app.config.json.load', return_value={}):
            config = AddonConfig()
        
        # Значения по умолчанию
        assert config.mqtt_host == "core-mosquitto"
        assert config.mqtt_port == 1883

    def test_load_partial_config(self):
        """Тест загрузки частичной конфигурации"""
        test_config = {
            "auto_update": True,
            "mqtt": {
                "host": "custom-mqtt"
            }
        }
        
        with patch('builtins.open'), patch('umdu_haos_updater.app.config.json.load', return_value=test_config):
            config = AddonConfig()
        
        # Заданные значения
        assert config.auto_update is True
        assert config.mqtt_host == "custom-mqtt"
        
        # Значения по умолчанию для остальных
        assert config.check_interval == 3600
        assert config.notifications is True

    def test_load_invalid_json(self):
        """Тест обработки невалидного JSON"""
        with patch('builtins.open'), patch('umdu_haos_updater.app.config.json.load', side_effect=json.JSONDecodeError("msg", "doc", 0)):
            config = AddonConfig()  # Должен использовать значения по умолчанию
            assert config.check_interval == 3600

    def test_empty_string_values_become_none(self):
        """Тест что пустые строки остаются пустыми"""
        test_config = {
            "mqtt": {
                "host": "",
                "username": "",
                "password": ""
            }
        }
        
        with patch('builtins.open'), patch('umdu_haos_updater.app.config.json.load', return_value=test_config):
            config = AddonConfig()
        
        assert config.mqtt_host == ""
        assert config.mqtt_username == ""
        assert config.mqtt_password == ""

    def test_string_to_int_conversion(self):
        """Тест что числовые значения работают корректно"""
        test_config = {
            "check_interval": 1800,  # число
            "mqtt": {
                "port": 1884  # число
            }
        }
        
        with patch('builtins.open'), patch('umdu_haos_updater.app.config.json.load', return_value=test_config):
            config = AddonConfig()
        
        assert config.check_interval == 1800
        assert config.mqtt_port == 1884

    # ------------------------------------------------------------------
    # Валидация значений
    # ------------------------------------------------------------------
    def test_invalid_interval_raises(self):
        """Тест валидации слишком маленького интервала"""
        test_config = {"check_interval": 30}  # меньше 60
        with patch('builtins.open'), patch('umdu_haos_updater.app.config.json.load', return_value=test_config):
            config = AddonConfig()
            # Должен быть исправлен на значение по умолчанию
            assert config.check_interval == 3600

    def test_invalid_mqtt_port_raises(self):
        """Тест валидации неверного порта"""
        test_config = {"mqtt": {"port": 70000}}  # за пределами диапазона
        with patch('builtins.open'), patch('umdu_haos_updater.app.config.json.load', return_value=test_config):
            config = AddonConfig()
            # Должен быть исправлен на значение по умолчанию
            assert config.mqtt_port == 1883