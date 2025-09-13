import types

import app.notification_service as ns


def test_notifications_disabled():
    service = ns.NotificationService(enabled=False)
    assert service.send_notification("t", "m") is False


def test_missing_token_returns_false(monkeypatch):
    service = ns.NotificationService(enabled=True)
    monkeypatch.setattr(ns, "TOKEN", None, raising=False)
    assert service.send_notification("t", "m") is False


def test_send_notification_ok(monkeypatch):
    service = ns.NotificationService(enabled=True)
    monkeypatch.setattr(ns, "TOKEN", "tkn", raising=False)

    class Resp:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, headers=None, timeout=None):
        return Resp()

    monkeypatch.setattr(ns, "requests", types.SimpleNamespace(post=fake_post))
    assert service.send_notification("t", "m") is True


def test_send_notification_error(monkeypatch):
    service = ns.NotificationService(enabled=True)
    monkeypatch.setattr(ns, "TOKEN", "tkn", raising=False)

    class Resp:
        def raise_for_status(self):
            raise RuntimeError("bad")

    def fake_post(url, json=None, headers=None, timeout=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(ns, "requests", types.SimpleNamespace(post=fake_post))
    assert service.send_notification("t", "m") is False
