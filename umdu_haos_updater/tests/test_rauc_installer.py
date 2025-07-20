"""Тесты для модуля rauc_installer.py"""
import pytest
from pathlib import Path
from unittest.mock import patch, Mock, call, ANY
import subprocess

from app.rauc_installer import install_bundle
from app.errors import InstallError


class TestInstallBundle:
    """Тесты для функции install_bundle"""

    def test_install_bundle_file_not_exists(self):
        """Тест обработки несуществующего файла"""
        bundle_path = Path("/nonexistent/bundle.raucb")
        
        with patch.object(Path, 'exists', return_value=False):
            with pytest.raises(InstallError):
                install_bundle(bundle_path)

    @patch('subprocess.Popen')
    def test_install_bundle_success(self, mock_popen):
        """Тест успешной установки"""
        bundle_path = Path("/share/umdu-haos-updater/bundle.raucb")
        
        # Мокаем процесс
        mock_proc = Mock()
        mock_proc.stdout = ["Line 1\n", "Line 2\n", "Installing...\n"]
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc
        
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'mkdir'), \
             patch.object(Path, 'symlink_to'):
            install_bundle(bundle_path)  # Функция не возвращает значение
        # Проверяем что вызван правильный путь (хостовый)
        expected_host_path = "/mnt/data/supervisor/share/umdu-haos-updater/bundle.raucb"
        mock_popen.assert_called_once_with(
            ["rauc", "install", expected_host_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

    @patch('subprocess.Popen')
    def test_install_bundle_rauc_failure(self, mock_popen):
        """Тест обработки ошибки RAUC"""
        bundle_path = Path("/share/umdu-haos-updater/bundle.raucb")
        
        mock_proc = Mock()
        mock_proc.stdout = ["Error installing bundle\n"]
        mock_proc.wait.return_value = 1  # ошибка
        mock_popen.return_value = mock_proc
        
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'mkdir'), \
             patch.object(Path, 'symlink_to'):
            with pytest.raises(InstallError, match="RAUC install завершился с кодом 1"):
                install_bundle(bundle_path)

    @patch('subprocess.Popen')
    def test_install_bundle_rauc_not_found(self, mock_popen):
        """Тест обработки отсутствия RAUC CLI"""
        bundle_path = Path("/share/umdu-haos-updater/bundle.raucb")
        
        mock_popen.side_effect = FileNotFoundError("rauc not found")
        
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'mkdir'), \
             patch.object(Path, 'symlink_to'):
            with pytest.raises(InstallError, match="RAUC CLI не найден"):
                install_bundle(bundle_path)

    @patch('subprocess.Popen')
    def test_install_bundle_unexpected_error(self, mock_popen):
        """Тест обработки неожиданной ошибки"""
        bundle_path = Path("/share/umdu-haos-updater/bundle.raucb")
        
        mock_popen.side_effect = RuntimeError("Unexpected error")
        
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'mkdir'), \
             patch.object(Path, 'symlink_to'):
            with pytest.raises(InstallError, match="Ошибка при установке: Unexpected error"):
                install_bundle(bundle_path)

    @patch('subprocess.Popen')
    def test_symlink_creation(self, mock_popen):
        """Тест создания символической ссылки"""
        bundle_path = Path("/share/umdu-haos-updater/bundle.raucb")
        
        mock_proc = Mock()
        mock_proc.stdout = []
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc
        
        # Возвращаем True для bundle_path.exists() и False для share_link.exists()
        def exists_side_effect():
            # Эта функция будет вызвана для каждого path.exists()
            # Возвращаем разные значения по порядку: сначала для bundle_path, потом для share_link
            if not hasattr(exists_side_effect, 'call_count'):
                exists_side_effect.call_count = 0
            exists_side_effect.call_count += 1
            if exists_side_effect.call_count == 1:
                return True  # bundle_path.exists()
            else:
                return False  # share_link.exists()
        
        with patch.object(Path, 'exists', side_effect=exists_side_effect), \
             patch.object(Path, 'mkdir') as mock_mkdir, \
             patch.object(Path, 'symlink_to') as mock_symlink:
            install_bundle(bundle_path)
        
        # Проверяем создание символической ссылки
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_symlink.assert_called_once_with("/share")

    @patch('subprocess.Popen')
    def test_symlink_creation_error(self, mock_popen):
        """Тест обработки ошибки создания символической ссылки"""
        bundle_path = Path("/share/umdu-haos-updater/bundle.raucb")
        
        mock_proc = Mock()
        mock_proc.stdout = []
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc
        
        # Возвращаем True для bundle_path.exists() и False для share_link.exists()
        def exists_side_effect():
            # Эта функция будет вызвана для каждого path.exists()
            if not hasattr(exists_side_effect, 'call_count'):
                exists_side_effect.call_count = 0
            exists_side_effect.call_count += 1
            if exists_side_effect.call_count == 1:
                return True  # bundle_path.exists()
            else:
                return False  # share_link.exists()
        
        with patch.object(Path, 'exists', side_effect=exists_side_effect), \
             patch.object(Path, 'mkdir'), \
             patch.object(Path, 'symlink_to', side_effect=OSError("Permission denied")), \
             patch('app.rauc_installer.logger') as mock_logger:
            # Должно продолжить работу несмотря на ошибку создания symlink
            install_bundle(bundle_path)  # Функция не возвращает значение
        mock_logger.warning.assert_called_once()

    def test_host_path_conversion(self):
        """Тест конвертации пути контейнера в хостовый путь"""
        bundle_path = Path("/share/umdu-haos-updater/bundle.raucb")
        
        mock_proc = Mock()
        mock_proc.stdout = []
        mock_proc.wait.return_value = 0
        
        with patch.object(Path, 'exists', return_value=True), \
             patch('subprocess.Popen', return_value=mock_proc) as mock_popen, \
             patch.object(Path, 'mkdir'), \
             patch.object(Path, 'symlink_to'):
            
            install_bundle(bundle_path)
        
        # Проверяем что RAUC вызван с хостовым путем
        expected_host_path = "/mnt/data/supervisor/share/umdu-haos-updater/bundle.raucb"
        mock_popen.assert_called_once_with(
            ["rauc", "install", expected_host_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )