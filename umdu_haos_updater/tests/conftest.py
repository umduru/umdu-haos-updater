import sys
from unittest.mock import MagicMock
import pytest
from pathlib import Path
import asyncio

# Глобальная подмена paho.mqtt, чтобы тесты не требовали реальную библиотеку
mqtt_mock = MagicMock()
client_mock = MagicMock()
mqtt_mock.client = client_mock

sys.modules.setdefault("paho", MagicMock())
sys.modules.setdefault("paho.mqtt", mqtt_mock)
sys.modules.setdefault("paho.mqtt.client", client_mock)

# Автоматически патчим Path.mkdir чтобы он ничего не делал (избегаем /share)
@pytest.fixture(autouse=True)
def _patch_path_mkdir(monkeypatch):
    monkeypatch.setattr(Path, "mkdir", lambda *a, **kw: None)
    yield 

# Быстрый event_loop (pytest-asyncio >= 0.24)
@pytest.fixture(scope="session")
def anyio_backend():  # type: ignore  # noqa: D401
    return "asyncio"

# Патчим asyncio.sleep, чтобы в тестах не было реальных задержек
@pytest.fixture(autouse=True)
def fake_sleep(monkeypatch):
    async def _dummy_sleep(*args, **kwargs):
        pass

    monkeypatch.setattr(asyncio, "sleep", _dummy_sleep)
    yield 