import types
import pytest
import logging

import app.supervisor_api as sup
from app.errors import SupervisorError


class Resp:
    def __init__(self, payload=None, status=200):
        self._payload = payload or {}
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            http_err = requests.HTTPError(response=self)
            raise http_err


def test_get_current_haos_version_success(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return Resp({"data": {"version": "16.1"}}, status=200)

    # patch only .get to preserve exception classes on sup.requests
    import requests
    monkeypatch.setattr(sup.requests, "get", fake_get)
    assert sup.get_current_haos_version() == "16.1"


def test_mqtt_not_ready_400(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return Resp({}, status=400)

    import requests
    monkeypatch.setattr(sup.requests, "get", fake_get)
    try:
        sup.get_mqtt_service()
        assert False, "expected error"
    except SupervisorError as e:
        assert "not ready" in str(e)


def test_http_error_raises_supervisor_error(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return Resp({}, status=500)

    monkeypatch.setattr(sup.requests, "get", fake_get)
    try:
        sup.get_current_haos_version()
        assert False, "expected error"
    except SupervisorError:
        pass


def test_request_exception_raises(monkeypatch):
    import requests

    def fake_get(url, headers=None, timeout=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(sup.requests, "get", fake_get)
    try:
        sup.get_current_haos_version()
        assert False, "expected"
    except SupervisorError:
        pass


def test_generic_exception_raises(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        raise ValueError("oops")

    monkeypatch.setattr(sup.requests, "get", fake_get)
    try:
        sup.get_current_haos_version()
        assert False, "expected"
    except SupervisorError:
        pass


def test_get_mqtt_service_success(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return Resp({"data": {"host": "h", "port": 1883, "username": "u", "password": "p"}})

    monkeypatch.setattr(sup.requests, "get", fake_get)
    data = sup.get_mqtt_service()
    assert data["host"] == "h" and data["port"] == 1883


def test_http_error_429_rate_limit_logs(monkeypatch, caplog):
    class R429:
        def __init__(self):
            self.status_code = 429
            self.headers = {"Retry-After": "5"}
        def json(self):
            return {}
        def raise_for_status(self):
            import requests
            raise requests.HTTPError(response=self)

    monkeypatch.setattr(sup.requests, "get", lambda url, headers=None, timeout=None: R429())
    caplog.set_level(logging.WARNING)
    try:
        sup.get_current_haos_version()
        assert False, "expected SupervisorError"
    except SupervisorError:
        pass
    assert any("rate-limited" in rec.getMessage() for rec in caplog.records)


def test_http_error_headers_access_raises(monkeypatch):
    class BadHeaders:
        def get(self, key):
            raise RuntimeError("boom")

    class R500:
        def __init__(self):
            self.status_code = 500
            self.headers = BadHeaders()
        def json(self):
            return {}
        def raise_for_status(self):
            import requests
            raise requests.HTTPError(response=self)

    monkeypatch.setattr(sup.requests, "get", lambda url, headers=None, timeout=None: R500())
    with pytest.raises(SupervisorError):
        sup.get_current_haos_version()
