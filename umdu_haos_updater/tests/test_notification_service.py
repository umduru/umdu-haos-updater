"""Тесты для модуля notification_service.py"""
import pytest
from unittest.mock import patch, Mock
from requests.exceptions import RequestException, Timeout, ConnectionError

from app.notification_service import NotificationService, reboot_required_message


class TestNotificationService:
    """Тесты для класса NotificationService"""

    def test_init(self):
        """Тест инициализации сервиса"""
        service = NotificationService()
        assert service.enabled is True
        assert service._timeout == 5.0
        
        service_disabled = NotificationService(enabled=False, timeout=10.0)
        assert service_disabled.enabled is False
        assert service_disabled._timeout == 10.0

    @patch('app.notification_service.TOKEN', 'test_token')
    @patch('requests.post')
    def test_send_success(self, mock_post):
        """Тест успешной отправки уведомления"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        service = NotificationService()
        service.send("Test Title", "Test message")

        mock_post.assert_called_once_with(
            "http://supervisor/core/api/services/persistent_notification/create",
            json={
                "title": "Test Title",
                "message": "Test message"
            },
            headers={"Authorization": "Bearer test_token"},
            timeout=5.0
        )

    @patch('app.notification_service.TOKEN', 'test_token')
    @patch('requests.post')
    def test_send_disabled(self, mock_post):
        """Тест отправки уведомления когда сервис отключен"""
        service = NotificationService(enabled=False)
        service.send("Test Title", "Test message")

        mock_post.assert_not_called()

    @patch('app.notification_service.TOKEN', 'test_token')
    @patch('requests.post')
    def test_send_request_exception(self, mock_post):
        """Тест обработки RequestException"""
        mock_post.side_effect = RequestException("Network error")

        service = NotificationService()
        # Не должно вызывать исключение
        service.send("Test Title", "Test message")

    @patch('app.notification_service.TOKEN', 'test_token')
    @patch('requests.post')
    def test_send_timeout_exception(self, mock_post):
        """Тест обработки Timeout"""
        mock_post.side_effect = Timeout("Request timeout")

        service = NotificationService()
        # Не должно вызывать исключение
        service.send("Test Title", "Test message")

    @patch('app.notification_service.TOKEN', 'test_token')
    @patch('requests.post')
    def test_send_connection_error(self, mock_post):
        """Тест обработки ConnectionError"""
        mock_post.side_effect = ConnectionError("Connection failed")

        service = NotificationService()
        # Не должно вызывать исключение
        service.send("Test Title", "Test message")

    @patch('app.notification_service.TOKEN', 'test_token')
    @patch('requests.post')
    def test_send_http_error(self, mock_post):
        """Тест обработки HTTP ошибки"""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = RequestException("HTTP 500")
        mock_post.return_value = mock_response

        service = NotificationService()
        # Не должно вызывать исключение
        service.send("Test Title", "Test message")

    @patch('app.notification_service.TOKEN', None)
    @patch('requests.post')
    def test_send_no_token(self, mock_post):
        """Тест отправки без токена"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        service = NotificationService()
        service.send("Test Title", "Test message")

        mock_post.assert_called_once_with(
            "http://supervisor/core/api/services/persistent_notification/create",
            json={
                "title": "Test Title",
                "message": "Test message"
            },
            headers={"Authorization": "Bearer None"},
            timeout=5.0
        )


class TestRebootRequiredMessage:
    """Тесты для функции reboot_required_message"""

    def test_reboot_required_message_with_version(self):
        """Тест формирования сообщения с версией"""
        result = reboot_required_message("15.2.1")
        assert "✅ Обновление до версии 15.2.1 установлено успешно!" in result
        assert "🔄 Требуется перезагрузка системы" in result
        assert "Перезапустить систему" in result

    def test_reboot_required_message_without_version(self):
        """Тест формирования сообщения без версии"""
        result = reboot_required_message()
        assert "✅ Обновление установлено успешно!" in result
        assert "🔄 Требуется перезагрузка системы" in result
        assert "Перезапустить систему" in result

    def test_reboot_required_message_empty_version(self):
        """Тест формирования сообщения с пустой версией"""
        result = reboot_required_message("")
        assert "✅ Обновление установлено успешно!" in result
        assert "🔄 Требуется перезагрузка системы" in result

    def test_reboot_required_message_none_version(self):
        """Тест формирования сообщения с None версией"""
        result = reboot_required_message(None)
        assert "✅ Обновление установлено успешно!" in result
        assert "🔄 Требуется перезагрузка системы" in result