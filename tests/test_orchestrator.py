from pathlib import Path

import app.orchestrator as orch
import app.config as cfg


class DummyNotifier:
    def __init__(self):
        self.sent = []

    def send_notification(self, title, msg):
        self.sent.append((title, msg))


class FakeMQTT:
    def __init__(self):
        self.published = []
        self.deactivated = 0

    def is_ready(self):
        return True

    def publish_update_state(self, installed, latest, in_progress=False):
        self.published.append((installed, latest, in_progress))

    def deactivate_update_entity(self):
        self.deactivated += 1


def make_orchestrator(tmp_path):
    c = cfg.AddonConfig(options_path=tmp_path / "missing.json")
    n = DummyNotifier()
    return orch.UpdateOrchestrator(c, n)


def test_publish_state_calls_mqtt(tmp_path):
    o = make_orchestrator(tmp_path)
    o._installed_version = "1.0"
    o._latest_version = "1.1"
    fake = FakeMQTT()
    o.set_mqtt_service(fake)
    o.publish_state()
    assert fake.published and fake.published[-1] == ("1.0", "1.1", False)


def test_run_install_success_path(tmp_path, monkeypatch):
    o = make_orchestrator(tmp_path)
    o.set_mqtt_service(FakeMQTT())
    # avoid network in publish_state path
    o._installed_version = "1.0"
    o._latest_version = "1.1"
    # success
    monkeypatch.setattr(o, "install_if_ready", lambda bundle_path: True)
    o.run_install(Path("/share/x.raucb"), latest_version="2.0")
    # deactivated
    assert o._mqtt_service.deactivated == 1
    # notification sent
    assert o._notifier.sent, "Notification not sent on success"
    # in_progress reset
    assert o._in_progress is False


def test_run_install_failure_path(tmp_path, monkeypatch):
    o = make_orchestrator(tmp_path)
    fake = FakeMQTT()
    o.set_mqtt_service(fake)
    # avoid network in publish_state path
    o._installed_version = "1.0"
    o._latest_version = "1.1"
    monkeypatch.setattr(o, "install_if_ready", lambda bundle_path: False)
    o.run_install(Path("/share/x.raucb"), latest_version="2.0")
    # publish_state called at end (in_progress False)
    assert fake.published and fake.published[-1][2] is False


def test_auto_cycle_once_flows(tmp_path, monkeypatch):
    o = make_orchestrator(tmp_path)
    o.set_mqtt_service(FakeMQTT())
    o._installed_version = "1.0"
    o._latest_version = "1.1"
    # if in progress -> do nothing
    o._in_progress = True
    o.auto_cycle_once()
    o._in_progress = False

    # if bundle ready and auto_update True -> run_install called
    o._cfg.auto_update = True
    called = {"run": 0}
    monkeypatch.setattr(o, "check_and_download", lambda: Path("/share/a.raucb"))
    monkeypatch.setattr(o, "run_install", lambda p, latest_version=None: called.__setitem__("run", called["run"] + 1))
    o.auto_cycle_once()
    assert called["run"] == 1

    # else publish state
    monkeypatch.setattr(o, "check_and_download", lambda: None)
    before = len(o._mqtt_service.published)
    o.auto_cycle_once()
    assert len(o._mqtt_service.published) > before


def test_get_versions_caching(monkeypatch, tmp_path):
    o = make_orchestrator(tmp_path)
    monkeypatch.setattr(orch, "get_current_haos_version", lambda: "16.0.0")

    class Info:
        def __init__(self, v):
            self.version = v

    monkeypatch.setattr(orch, "fetch_available_update", lambda dev_channel=False: Info("16.1.0"))
    inst, latest = o.get_versions()
    assert inst == "16.0.0" and latest == "16.1.0"


def test_set_mqtt_service_stops_previous(tmp_path):
    o = make_orchestrator(tmp_path)

    class Stoppable(FakeMQTT):
        def __init__(self):
            super().__init__()
            self.stopped = 0

        def stop(self):
            self.stopped += 1

    a = Stoppable()
    b = Stoppable()
    o.set_mqtt_service(a)
    o.set_mqtt_service(b)
    assert a.stopped == 1


def test_set_mqtt_service_stop_exception(tmp_path, monkeypatch):
    o = make_orchestrator(tmp_path)

    class Bad:
        def stop(self):
            raise RuntimeError("oops")

    o.set_mqtt_service(Bad())
    # next set should catch the exception
    o.set_mqtt_service(FakeMQTT())


def test_get_versions_installed_override_and_fetch_error(tmp_path, monkeypatch):
    o = make_orchestrator(tmp_path)
    # Сначала мокаем, чтобы первый вызов не ушёл в сеть и не закешировал latest
    monkeypatch.setattr("app.orchestrator.fetch_available_update",
                        lambda dev_channel=False: (_ for _ in ()).throw(RuntimeError("boom")),
                        raising=True)
    inst, latest = o.get_versions(installed="x")
    assert inst == "x" and latest == "x"


def test_safe_mqtt_operation_paths(tmp_path):
    o = make_orchestrator(tmp_path)
    # no service -> no op
    o._safe_mqtt_operation("op", lambda: 1)

    # with service, but operation raises
    o.set_mqtt_service(FakeMQTT())
    o._safe_mqtt_operation("op", lambda: (_ for _ in ()).throw(RuntimeError("x")))


def test_publish_state_early_return_when_not_ready(tmp_path):
    o = make_orchestrator(tmp_path)

    class NotReady(FakeMQTT):
        def is_ready(self):
            return False

    o.set_mqtt_service(NotReady())
    o.publish_state()


def test_publish_state_no_service_returns(tmp_path):
    o = make_orchestrator(tmp_path)
    # No MQTT service set -> early return, should not raise
    o.publish_state()


def test_publish_state_is_ready_exception(tmp_path):
    o = make_orchestrator(tmp_path)

    class BadReady(FakeMQTT):
        def is_ready(self):
            raise RuntimeError("boom")

    o.set_mqtt_service(BadReady())
    # Should swallow exception from is_ready and return without raising
    o.publish_state()


def test_check_and_download_calls_func(tmp_path, monkeypatch):
    o = make_orchestrator(tmp_path)
    p = Path("/share/z.raucb")
    monkeypatch.setattr(orch, "check_for_update_and_download", lambda auto_download, orchestrator, dev_channel: p)
    assert o.check_and_download() == p


def test_install_if_ready_success_and_error(tmp_path, monkeypatch):
    o = make_orchestrator(tmp_path)
    # success path
    monkeypatch.setattr(orch, "install_bundle", lambda bundle_path: True)
    touched = {"ok": 0}
    monkeypatch.setattr(o, "_touch_reboot_flag", lambda: touched.__setitem__("ok", 1))
    assert o.install_if_ready(Path("/share/x.raucb")) is True and touched["ok"] == 1

    # error path
    from app.errors import InstallError
    o._notifier.sent.clear()
    monkeypatch.setattr(orch, "install_bundle", lambda bundle_path: (_ for _ in ()).throw(InstallError("bad")))
    assert o.install_if_ready(Path("/share/x.raucb")) is False and o._notifier.sent


def test_run_install_exception_and_notify_exception(tmp_path, monkeypatch):
    o = make_orchestrator(tmp_path)
    o.set_mqtt_service(FakeMQTT())
    o._installed_version = "1.0"
    o._latest_version = "1.1"
    # install_if_ready raises generic
    monkeypatch.setattr(o, "install_if_ready", lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    o.run_install(Path("/share/x.raucb"), latest_version="2.0")
    assert o._in_progress is False

    # success but notifier raises
    o.set_mqtt_service(FakeMQTT())
    o._installed_version = "1.0"
    o._latest_version = "1.1"
    monkeypatch.setattr(o, "install_if_ready", lambda p: True)
    def bad_notify(title, msg):
        raise RuntimeError("n")
    o._notifier.send_notification = bad_notify
    o.run_install(Path("/share/x.raucb"), latest_version="2.0")


def test_touch_reboot_flag(monkeypatch):
    # Ensure static method is executed without touching real FS
    calls = {"touch": 0}
    from app import orchestrator as orc
    orig_path = orc.Path
    class P(type(orc.Path("/"))):
        pass
    p = orig_path("/data/reboot_required")
    monkeypatch.setattr(p.__class__, "touch", lambda self, exist_ok=False: calls.__setitem__("touch", calls["touch"] + 1))
    orc.Path = orig_path  # keep class, we just patched method above
    orc.UpdateOrchestrator._touch_reboot_flag()
    assert calls["touch"] == 1
