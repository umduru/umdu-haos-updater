"""Тесты для модуля supervisor_api.py"""
import pytest
import requests
from unittest.mock import patch, Mock

from app.supervisor_api import (
    get_current_haos_version,
    get_mqtt_service,
    _headers,
    SUPERVISOR_URL,
    TOKEN
)
from app.errors import NetworkError, SupervisorError


class TestHeaders:
    """Тесты для функции _headers"""

    def test_headers_with_token(self):
        """Тест генерации заголовков с токеном"""
        with patch('app.supervisor_api.TOKEN', 'test_token'):
            headers = _headers()
        
        assert headers == {"Authorization": "Bearer test_token"}

    def test_headers_with_none_token(self):
        """Тест генерации заголовков с None токеном"""
        with patch('app.supervisor_api.TOKEN', None):
            headers = _headers()
        
        assert headers == {"Authorization": "Bearer None"}


class TestGetCurrentHaosVersion:
    """Тесты для функции get_current_haos_version"""

    @patch('app.supervisor_api.TOKEN', 'test_token')
    def test_get_version_success(self):
        """Тест успешного получения версии HAOS"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "version": "15.2.1"
            }
        }
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response) as mock_get:
            result = get_current_haos_version()
        
        assert result == "15.2.1"
        mock_get.assert_called_once_with(
            f"{SUPERVISOR_URL}/os/info",
            headers={"Authorization": "Bearer test_token"},
            timeout=5
        )

    def test_get_version_network_error(self):
        """Тест обработки сетевой ошибки"""
        with patch('requests.get', side_effect=requests.RequestException("Network error")):
            with pytest.raises(NetworkError):
                get_current_haos_version()

    def test_get_version_http_error(self):
        """Тест обработки HTTP ошибки"""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        
        with patch('requests.get', return_value=mock_response):
            with pytest.raises(NetworkError):
                get_current_haos_version()

    def test_get_version_timeout(self):
        """Тест обработки таймаута"""
        with patch('requests.get', side_effect=requests.Timeout("Timeout")):
            with pytest.raises(NetworkError):
                get_current_haos_version()

    def test_get_version_invalid_json_structure(self):
        """Тест обработки невалидной структуры JSON"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {}  # Отсутствует ключ "version"
        }
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            with pytest.raises(SupervisorError):
                get_current_haos_version()

    def test_get_version_missing_data_key(self):
        """Тест обработки отсутствующего ключа data"""
        mock_response = Mock()
        mock_response.json.return_value = {}  # Отсутствует ключ "data"
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            with pytest.raises(SupervisorError):
                get_current_haos_version()


class TestGetMqttService:
    """Тесты для функции get_mqtt_service"""

    @patch('app.supervisor_api.TOKEN', 'test_token')
    def test_get_mqtt_service_success(self):
        """Тест успешного получения настроек MQTT"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "host": "mqtt.local",
                "port": 1883,
                "username": "user",
                "password": "pass"
            }
        }
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response) as mock_get:
            result = get_mqtt_service()
        
        expected = {
            "host": "mqtt.local",
            "port": 1883,
            "username": "user",
            "password": "pass"
        }
        assert result == expected
        mock_get.assert_called_once_with(
            f"{SUPERVISOR_URL}/services/mqtt",
            headers={"Authorization": "Bearer test_token"},
            timeout=5
        )

    def test_get_mqtt_service_partial_data(self):
        """Тест получения частичных данных MQTT"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "host": "mqtt.local",
                "port": 1883
                # username и password отсутствуют
            }
        }
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            result = get_mqtt_service()
        
        expected = {
            "host": "mqtt.local",
            "port": 1883,
            "username": None,
            "password": None
        }
        assert result == expected

    def test_get_mqtt_service_empty_data(self):
        """Тест получения пустых данных"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {}
        }
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            result = get_mqtt_service()
        
        expected = {"host": None, "port": None, "username": None, "password": None}
        assert result == expected

    def test_get_mqtt_service_network_error(self):
        """Тест обработки сетевой ошибки"""
        with patch('requests.get', side_effect=requests.RequestException("Network error")):
            with pytest.raises(NetworkError):
                get_mqtt_service()

    def test_get_mqtt_service_http_error(self):
        """Тест обработки HTTP ошибки"""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        
        with patch('requests.get', return_value=mock_response):
            with pytest.raises(NetworkError):
                get_mqtt_service()

    def test_get_mqtt_service_timeout(self):
        """Тест обработки таймаута"""
        with patch('requests.get', side_effect=requests.Timeout("Timeout")):
            with pytest.raises(NetworkError):
                get_mqtt_service()

    def test_get_mqtt_service_missing_data_key(self):
        """Тест обработки отсутствующего ключа data"""
        mock_response = Mock()
        mock_response.json.return_value = {}  # Отсутствует ключ "data"
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            result = get_mqtt_service()
        
        expected = {"host": None, "port": None, "username": None, "password": None}
        assert result == expected

    def test_get_mqtt_service_invalid_json(self):
        """Тест обработки невалидного JSON"""
        mock_response = Mock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            with pytest.raises(SupervisorError):
                get_mqtt_service() 