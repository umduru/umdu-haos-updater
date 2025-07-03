"""Тесты для модуля updater.py"""
import pytest
import requests
from pathlib import Path
from unittest.mock import patch, Mock, mock_open
import hashlib
from app.errors import NetworkError, DownloadError

from app.updater import (
    UpdateInfo, 
    fetch_available_update, 
    is_newer, 
    download_update, 
    check_for_update_and_download,
    _verify_sha256,
    GITHUB_VERSIONS_URL
)


class TestUpdateInfo:
    """Тесты для класса UpdateInfo"""

    def test_init_with_version_only(self):
        """Тест создания UpdateInfo только с версией"""
        info = UpdateInfo("15.2.1")
        
        assert info.version == "15.2.1"
        assert info.sha256 is None

    def test_init_with_version_and_sha256(self):
        """Тест создания UpdateInfo с версией и хэшем"""
        sha = "abc123def456"
        info = UpdateInfo("15.2.1", sha)
        
        assert info.version == "15.2.1"
        assert info.sha256 == sha

    def test_filename_property(self):
        """Тест генерации имени файла"""
        info = UpdateInfo("15.2.1")
        expected = "haos_umdu-k1-15.2.1.raucb"
        
        assert info.filename == expected

    def test_url_property(self):
        """Тест генерации URL для скачивания"""
        info = UpdateInfo("15.2.1")
        expected = "https://github.com/umduru/umdu-haos-updater/releases/download/15.2.1/haos_umdu-k1-15.2.1.raucb"
        
        assert info.url == expected

    def test_download_path_property(self):
        """Тест генерации пути для сохранения"""
        info = UpdateInfo("15.2.1")
        expected = Path("/share/umdu-haos-updater/haos_umdu-k1-15.2.1.raucb")
        
        with patch.object(Path, 'mkdir'):
            result = info.download_path
        
        assert result == expected


class TestFetchAvailableUpdate:
    """Тесты для функции fetch_available_update"""

    def test_fetch_success_string_version(self):
        """Тест успешного получения версии (строка)"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "hassos": {
                "umdu-k1": "15.2.1"
            }
        }
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            result = fetch_available_update()
        
        assert result is not None
        assert result.version == "15.2.1"
        assert result.sha256 is None

    def test_fetch_success_dict_version(self):
        """Тест успешного получения версии (словарь с хэшем)"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "hassos": {
                "umdu-k1": {
                    "version": "15.2.1",
                    "sha256": "abc123def456"
                }
            }
        }
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            result = fetch_available_update()
        
        assert result is not None
        assert result.version == "15.2.1"
        assert result.sha256 == "abc123def456"

    def test_fetch_network_error(self):
        """Тест обработки сетевой ошибки"""
        with patch('requests.get', side_effect=requests.RequestException("Network error")):
            with pytest.raises(NetworkError):
                fetch_available_update()

    def test_fetch_timeout(self):
        """Тест обработки таймаута"""
        with patch('requests.get', side_effect=requests.Timeout("Timeout")):
            with pytest.raises(NetworkError):
                fetch_available_update()

    def test_fetch_invalid_json(self):
        """Тест обработки невалидного JSON"""
        mock_response = Mock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            with pytest.raises(NetworkError):
                fetch_available_update()


class TestIsNewer:
    """Тесты для функции is_newer"""

    def test_newer_version(self):
        """Тест определения новой версии"""
        assert is_newer("15.2.1", "15.2.0") is True
        assert is_newer("15.3.0", "15.2.1") is True
        assert is_newer("16.0.0", "15.2.1") is True

    def test_older_version(self):
        """Тест определения старой версии"""
        assert is_newer("15.2.0", "15.2.1") is False
        assert is_newer("15.1.0", "15.2.1") is False
        assert is_newer("14.0.0", "15.2.1") is False

    def test_same_version(self):
        """Тест одинаковых версий"""
        assert is_newer("15.2.1", "15.2.1") is False

    def test_invalid_versions_fallback(self):
        """Тест fallback для невалидных версий"""
        assert is_newer("abc", "def") is False  # abc < def
        assert is_newer("xyz", "abc") is True   # xyz > abc
        assert is_newer("same", "same") is False


class TestVerifySha256:
    """Тесты для функции _verify_sha256"""

    def test_verify_correct_hash(self):
        """Тест проверки корректного хэша"""
        content = b"test content"
        expected_hash = hashlib.sha256(content).hexdigest()
        
        with patch("builtins.open", mock_open(read_data=content)):
            result = _verify_sha256(Path("test.file"), expected_hash)
        
        assert result is True

    def test_verify_incorrect_hash(self):
        """Тест проверки некорректного хэша"""
        content = b"test content"
        wrong_hash = "wronghash123"
        
        with patch("builtins.open", mock_open(read_data=content)):
            result = _verify_sha256(Path("test.file"), wrong_hash)
        
        assert result is False

    def test_verify_case_insensitive(self):
        """Тест что проверка хэша нечувствительна к регистру"""
        content = b"test content"
        expected_hash = hashlib.sha256(content).hexdigest().upper()
        
        with patch("builtins.open", mock_open(read_data=content)):
            result = _verify_sha256(Path("test.file"), expected_hash)
        
        assert result is True


class TestDownloadUpdate:
    """Тесты для функции download_update"""

    def test_file_already_exists_valid_hash(self):
        """Тест когда файл уже существует и хэш валиден"""
        info = UpdateInfo("15.2.1", "validhash123")
        
        with patch.object(Path, 'exists', return_value=True), \
             patch('pathlib.Path.mkdir'), \
             patch('app.updater._verify_sha256', return_value=True):
            result = download_update(info)
        
        assert result == info.download_path

    def test_file_exists_invalid_hash_redownload(self):
        """Тест перезагрузки при невалидном хэше"""
        info = UpdateInfo("15.2.1", "validhash123")
        
        mock_response = Mock()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s,*args: None
        mock_response.raise_for_status.return_value = None
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
        
        with patch.object(Path, 'exists', return_value=True), \
             patch('pathlib.Path.mkdir'), \
             patch('app.updater._verify_sha256', side_effect=[False, True]), \
             patch.object(Path, 'unlink'), \
             patch.object(Path, 'glob', return_value=[]), \
             patch('requests.get', return_value=mock_response), \
             patch("builtins.open", mock_open()):
            result = download_update(info)
        
        assert result == info.download_path

    def test_download_network_error(self):
        """Тест обработки сетевой ошибки при загрузке"""
        info = UpdateInfo("15.2.1")
        
        with patch.object(Path, 'exists', return_value=False), \
             patch('pathlib.Path.mkdir'), \
             patch.object(Path, 'glob', return_value=[]), \
             patch('requests.get', side_effect=requests.RequestException("Network error")):
            with pytest.raises(DownloadError):
                download_update(info)

    def test_cleanup_old_bundles(self):
        """Тест очистки старых бандлов"""
        info = UpdateInfo("15.2.1")
        old_files = [Path("/share/umdu-haos-updater/haos_umdu-k1-15.1.0.raucb")]
        
        mock_response = Mock()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s,*args: None
        mock_response.raise_for_status.return_value = None
        mock_response.iter_content.return_value = [b"chunk1"]
        
        with patch.object(Path, 'exists', return_value=False), \
             patch('pathlib.Path.mkdir'), \
             patch.object(Path, 'glob', return_value=old_files), \
             patch.object(Path, 'unlink') as mock_unlink, \
             patch('requests.get', return_value=mock_response), \
             patch("builtins.open", mock_open()):
            download_update(info)
        
        mock_unlink.assert_called()


class TestCheckForUpdateAndDownload:
    """Тесты для функции check_for_update_and_download"""

    @patch('app.updater.get_current_haos_version')
    @patch('app.updater.fetch_available_update')
    def test_no_current_version(self, mock_fetch, mock_current):
        """Тест когда не удается определить текущую версию"""
        mock_current.return_value = None
        
        result = check_for_update_and_download()
        
        assert result is None
        mock_fetch.assert_not_called()

    @patch('app.updater.get_current_haos_version')
    @patch('app.updater.fetch_available_update')
    def test_no_available_update(self, mock_fetch, mock_current):
        """Тест когда нет доступных обновлений"""
        mock_current.return_value = "15.2.0"
        mock_fetch.side_effect = NetworkError("Network")
        
        result = check_for_update_and_download()
        
        assert result is None

    @patch('app.updater.get_current_haos_version')
    @patch('app.updater.fetch_available_update')
    @patch('app.updater.download_update')
    def test_newer_version_auto_download(self, mock_download, mock_fetch, mock_current):
        """Тест автоматической загрузки новой версии"""
        mock_current.return_value = "15.2.0"
        mock_fetch.return_value = UpdateInfo("15.2.1")
        mock_download.return_value = Path("/path/to/bundle")
        
        result = check_for_update_and_download(auto_download=True)
        
        assert result == Path("/path/to/bundle")
        mock_download.assert_called_once()

    @patch('app.updater.get_current_haos_version')
    @patch('app.updater.fetch_available_update')
    def test_no_newer_version(self, mock_fetch, mock_current):
        """Тест когда нет новых версий"""
        mock_current.return_value = "15.2.1"
        mock_fetch.return_value = UpdateInfo("15.2.1")
        
        result = check_for_update_and_download()
        
        assert result is None

    @patch('app.updater.get_current_haos_version')
    @patch('app.updater.fetch_available_update')
    def test_newer_version_no_auto_download(self, mock_fetch, mock_current):
        """Тест когда есть новая версия но автозагрузка отключена"""
        mock_current.return_value = "15.2.0"
        mock_fetch.return_value = UpdateInfo("15.2.1")
        
        result = check_for_update_and_download(auto_download=False)
        
        assert result is None 