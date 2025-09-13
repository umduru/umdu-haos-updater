import asyncio
from pathlib import Path

import app.main as m
import pytest


class DummyOrchestrator:
    def __init__(self):
        self._cfg = type("C", (), {"dev_channel": False})()
        self.set = []
        self._mqtt_service = None

    def get_versions(self):
        return ("1.0", "1.1")

    def publish_state(self, latest=None):
        self.set.append("pub")

    def run_install(self, path, latest):
        self.set.append(("install", str(path), latest))

    def auto_cycle_once(self):
        # break the main loop after first call
        raise SystemExit(0)

    def set_mqtt_service(self, svc):
        self._mqtt_service = svc


class DummyCfg:
    def __init__(self):
        self.check_interval = 0
        self.auto_update = False
        self.debug = False
        self.dev_channel = False
        self.notifications = False

    def get_mqtt_params(self):
        return ("h", 1883, "u", "p", False)


class IdleOrchestrator(DummyOrchestrator):
    def auto_cycle_once(self):
        # do nothing, let loop proceed
        return None


class DummyLoop:
    async def run_in_executor(self, executor, func, *args):
        return func(*args)


def test_handle_install_cmd_paths(monkeypatch, tmp_path):
    orch = DummyOrchestrator()
    # bundle missing -> publish_state called
    monkeypatch.setattr(m, "check_for_update_and_download", lambda auto_download, orchestrator, dev_channel: None)
    m.handle_install_cmd(orch)
    assert "pub" in orch.set

    # bundle present -> run_install called
    p = tmp_path / "a.raucb"
    monkeypatch.setattr(m, "check_for_update_and_download", lambda auto_download, orchestrator, dev_channel: p)
    orch.set.clear()
    m.handle_install_cmd(orch)
    assert orch.set and orch.set[0][0] == "install"


def test_initialize_and_setup_mqtt_variants(monkeypatch):
    cfg = DummyCfg()
    orch = DummyOrchestrator()
    loop = DummyLoop()

    # no host -> None
    monkeypatch.setattr(cfg, "get_mqtt_params", lambda: (None, 1883, None, None, False))
    res = asyncio.run(m.initialize_and_setup_mqtt(cfg, orch, loop))
    assert res is None

    # success path
    monkeypatch.setattr(cfg, "get_mqtt_params", lambda: ("h", 1883, None, None, False))

    class FakeService:
        def __init__(self, host, port, username, password, use_tls=False, discovery=True):
            self.host = host
            self.port = port
            self.discovery = discovery
            self.started = False
            self.initial = None
            self.on_install_cmd = None

        def set_initial_versions(self, inst, latest):
            self.initial = (inst, latest)

        def start(self):
            self.started = True

    monkeypatch.setattr(m, "MqttService", FakeService)
    svc = asyncio.run(m.initialize_and_setup_mqtt(cfg, orch, loop))
    assert isinstance(svc, FakeService) and svc.started and svc.initial == ("1.0", "1.1")

    # exception path
    class BadService(FakeService):
        def start(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(m, "MqttService", BadService)
    res = asyncio.run(m.initialize_and_setup_mqtt(cfg, orch, loop))
    assert res is None

    # with retry delay branch (patch asyncio.sleep to fast async)
    async def fast_sleep(s):
        return None
    monkeypatch.setattr(m.asyncio, "sleep", fast_sleep)
    asyncio.run(m.initialize_and_setup_mqtt(cfg, orch, loop, retry_delay=1))


def test_initialize_skip_if_already_ready_after_delay(monkeypatch):
    cfg = DummyCfg()
    orch = DummyOrchestrator()
    loop = DummyLoop()

    class Ready:
        def is_ready(self):
            return True

    orch._mqtt_service = Ready()

    # ensure sleep is quick
    async def fast_sleep(s):
        return None
    monkeypatch.setattr(m.asyncio, "sleep", fast_sleep)

    # guard to ensure get_mqtt_params is not called
    called = {"get": 0}
    def boom():
        called["get"] += 1
        raise AssertionError("get_mqtt_params should not be called when already ready")
    monkeypatch.setattr(cfg, "get_mqtt_params", boom)

    res = asyncio.run(m.initialize_and_setup_mqtt(cfg, orch, loop, retry_delay=1))
    assert res is None and called["get"] == 0


def test_handle_mqtt_reconnection_branches(monkeypatch):
    cfg = DummyCfg()
    orch = DummyOrchestrator()
    loop = DummyLoop()

    # success -> reset counter
    fake_service = object()
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", lambda cfg, orch, loop, retry_delay=0: asyncio.sleep(0, result=fake_service))
    svc, cnt = asyncio.run(m.handle_mqtt_reconnection(cfg, orch, loop, 0))
    assert svc is fake_service and cnt == 0

    # max retries reached
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", lambda cfg, orch, loop, retry_delay=0: asyncio.sleep(0, result=None))
    svc, cnt = asyncio.run(m.handle_mqtt_reconnection(cfg, orch, loop, 4))
    assert svc is None and cnt == 0

    # increment counter
    svc, cnt = asyncio.run(m.handle_mqtt_reconnection(cfg, orch, loop, 1))
    assert svc is None and cnt == 2


def test_main_exits_without_token(monkeypatch):
    monkeypatch.setattr(m, "TOKEN", None, raising=False)
    with pytest.raises(SystemExit):
        asyncio.run(m.main())


def test_main_one_iteration(monkeypatch):
    # token present
    monkeypatch.setattr(m, "TOKEN", "tkn", raising=False)
    # avoid real classes
    monkeypatch.setattr(m, "AddonConfig", DummyCfg)
    monkeypatch.setattr(m, "NotificationService", lambda enabled: None)
    orch = DummyOrchestrator()
    monkeypatch.setattr(m, "UpdateOrchestrator", lambda cfg, notifier: orch)
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", lambda cfg, o, loop, retry_delay=30: asyncio.sleep(0, result=None))
    monkeypatch.setattr(m, "handle_mqtt_reconnection", lambda cfg, o, loop, cnt: asyncio.sleep(0, result=(None, 0)))
    # run main and expect SystemExit from our orchestrator
    with pytest.raises(SystemExit):
        asyncio.run(m.main())

    # cover both branches in the while loop
    orch2 = IdleOrchestrator()
    orch2._mqtt_service = type("S", (), {"is_ready": lambda self: True})()
    monkeypatch.setattr(m, "UpdateOrchestrator", lambda cfg, notifier: orch2)
    # sleep triggers exit after else branch executed
    async def exit_sleep(*args, **kwargs):
        raise SystemExit(0)
    class ReadySvc:
        def is_ready(self):
            return True
    async def init_none(*args, **kwargs):
        return ReadySvc()
    monkeypatch.setattr(m.asyncio, "sleep", exit_sleep)
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", init_none)
    with pytest.raises(SystemExit):
        asyncio.run(m.main())

    # and the if-branch where service is None
    orch3 = IdleOrchestrator()
    orch3._mqtt_service = None
    monkeypatch.setattr(m, "UpdateOrchestrator", lambda cfg, notifier: orch3)
    async def init_none2(*args, **kwargs):
        return None
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", init_none2)
    async def recon(*args, **kwargs):
        return (None, 0)
    monkeypatch.setattr(m, "handle_mqtt_reconnection", recon)
    async def exit_sleep2(*args, **kwargs):
        raise SystemExit(0)
    monkeypatch.setattr(m.asyncio, "sleep", exit_sleep2)
    with pytest.raises(SystemExit):
        asyncio.run(m.main())

def test_main_dunder_block(monkeypatch):
    # Run module as __main__ to cover the bottom guard
    import runpy, asyncio as aio
    # make asyncio.run raise to abort quickly
    def abort(coro):
        raise SystemExit(0)
    monkeypatch.setattr(aio, "run", abort)
    with pytest.raises(SystemExit):
        runpy.run_module("app.main", run_name="__main__")
    # and KeyboardInterrupt path
    def kbi(coro):
        raise KeyboardInterrupt()
    monkeypatch.setattr(aio, "run", kbi)
    # Should not raise
    runpy.run_module("app.main", run_name="__main__")


def test_main_debug_flag(monkeypatch):
    class DebugCfg(DummyCfg):
        def __init__(self):
            super().__init__()
            self.debug = True
    monkeypatch.setattr(m, "TOKEN", None, raising=False)
    monkeypatch.setattr(m, "AddonConfig", DebugCfg)
    with pytest.raises(SystemExit):
        asyncio.run(m.main())
