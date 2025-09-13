import asyncio
import builtins
import types
import pytest

import app.main as m


def test_handle_install_cmd_skips_when_in_progress(monkeypatch):
    class Orch:
        def __init__(self):
            self._in_progress = True
            self.called = False

        def get_versions(self):
            return ("1.0", "1.1")

        def run_install(self, *a, **k):
            self.called = True

    o = Orch()
    m.handle_install_cmd(o)
    assert o.called is False


def test_initialize_skip_after_delay_exception_guard(monkeypatch):
    class DummyLoop:
        async def run_in_executor(self, executor, func, *args):
            return func(*args)

    class Cfg:
        def get_mqtt_params(self):
            return (None, 1883, None, None, False)

    class ErrReady:
        def is_ready(self):
            raise RuntimeError("boom")

    class Orch:
        def __init__(self):
            self._mqtt_service = ErrReady()

    async def fast_sleep(*a, **k):
        return None

    loop = DummyLoop()
    orch = Orch()
    cfg = Cfg()
    monkeypatch.setattr(m.asyncio, "sleep", fast_sleep)

    # Should handle exception in readiness check and proceed without raising
    res = asyncio.run(m.initialize_and_setup_mqtt(cfg, orch, loop, retry_delay=1))
    assert res is None


def test_handle_mqtt_reconnection_uses_existing_ready(monkeypatch):
    class DummyLoop:
        async def run_in_executor(self, executor, func, *args):
            return func(*args)

    class Ready:
        def is_ready(self):
            return True

    async def init_none(*a, **k):
        return None

    cfg = types.SimpleNamespace()
    orch = types.SimpleNamespace(_mqtt_service=Ready())
    loop = DummyLoop()
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", init_none)

    svc, cnt = asyncio.run(m.handle_mqtt_reconnection(cfg, orch, loop, 0))
    assert isinstance(svc, Ready.__class__) or svc is orch._mqtt_service
    assert cnt == 0


def test_main_signal_handler_and_inner_except(monkeypatch):
    # Token present
    monkeypatch.setattr(m, "TOKEN", "tkn", raising=False)

    # Fast config
    class Cfg:
        def __init__(self):
            self.check_interval = 0
            self.auto_update = False
            self.debug = False
            self.dev_channel = False
            self.notifications = False

    monkeypatch.setattr(m, "AddonConfig", Cfg)
    monkeypatch.setattr(m, "NotificationService", lambda enabled: None)

    # Orchestrator with existing service so shutdown handler calls stop()
    class Service:
        def __init__(self):
            self.stopped = 0
        def stop(self):
            self.stopped += 1

    class Orch:
        def __init__(self, *a, **k):
            self._cfg = types.SimpleNamespace(dev_channel=False)
            self._mqtt_service = Service()
        def auto_cycle_once(self):
            # Should not be reached because stop_event is set by handler
            raise SystemExit(0)
        def set_mqtt_service(self, svc):
            self._mqtt_service = svc

    monkeypatch.setattr(m, "UpdateOrchestrator", Orch)

    # Skip initial MQTT init
    async def init_none(*a, **k):
        return None
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", init_none)
    monkeypatch.setattr(m, "handle_mqtt_reconnection", lambda *a, **k: asyncio.sleep(0, result=(None, 0)))

    # Dummy loop captures handler; second registration raises to hit inner except
    class DummyLoop:
        def __init__(self):
            self.count = 0
        async def run_in_executor(self, executor, func, *args):
            return func(*args)
        def add_signal_handler(self, sig, cb):
            self.count += 1
            if self.count == 2:
                # invoke handler to set stop_event, then raise to trigger inner except
                cb()
                raise RuntimeError("no handler")

    monkeypatch.setattr(m.asyncio, "get_running_loop", lambda: DummyLoop())

    # Should exit cleanly without raising
    asyncio.run(m.main())


def test_main_mqtt_init_grace_branch(monkeypatch):
    monkeypatch.setattr(m, "TOKEN", "tkn", raising=False)

    class Cfg:
        def __init__(self):
            self.check_interval = 0
            self.auto_update = False
            self.debug = False
            self.dev_channel = False
            self.notifications = False

    monkeypatch.setattr(m, "AddonConfig", Cfg)
    monkeypatch.setattr(m, "NotificationService", lambda enabled: None)

    class FlappySvc:
        def __init__(self):
            self.calls = 0
        def is_ready(self):
            self.calls += 1
            return self.calls >= 2

    class Orch:
        def __init__(self, *a, **k):
            self._cfg = types.SimpleNamespace(dev_channel=False)
            self._mqtt_service = None
            self.calls = 0
        def auto_cycle_once(self):
            self.calls += 1
            if self.calls >= 2:
                raise SystemExit(0)
        def set_mqtt_service(self, svc):
            self._mqtt_service = svc

    monkeypatch.setattr(m, "UpdateOrchestrator", Orch)

    async def init_flappy(*a, **k):
        return FlappySvc()
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", init_flappy)

    # fast sleep
    async def fast_sleep(*a, **k):
        return None
    monkeypatch.setattr(m.asyncio, "sleep", fast_sleep)

    with pytest.raises(SystemExit):
        asyncio.run(m.main())


def test_main_reconnect_sets_service_and_wait_for_timeout(monkeypatch):
    monkeypatch.setattr(m, "TOKEN", "tkn", raising=False)

    class Cfg:
        def __init__(self):
            self.check_interval = 10
            self.auto_update = False
            self.debug = False
            self.dev_channel = False
            self.notifications = False

    monkeypatch.setattr(m, "AddonConfig", Cfg)
    monkeypatch.setattr(m, "NotificationService", lambda enabled: None)

    class Svc:
        def is_ready(self):
            return True

    class Orch:
        def __init__(self, *a, **k):
            self._cfg = types.SimpleNamespace(dev_channel=False)
            self._mqtt_service = None
            self.set_called = 0
            self.calls = 0
        def auto_cycle_once(self):
            self.calls += 1
            if self.calls >= 2:
                raise SystemExit(0)
        def set_mqtt_service(self, svc):
            self.set_called += 1
            self._mqtt_service = svc

    monkeypatch.setattr(m, "UpdateOrchestrator", Orch)

    async def init_none(*a, **k):
        return None
    async def recon(*a, **k):
        return Svc(), 0
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", init_none)
    monkeypatch.setattr(m, "handle_mqtt_reconnection", recon)

    # Make wait_for timeout immediately to cover the except TimeoutError branch
    def instant_timeout(awaitable, timeout=None):
        raise asyncio.TimeoutError()
    monkeypatch.setattr(m.asyncio, "wait_for", instant_timeout)

    with pytest.raises(SystemExit):
        asyncio.run(m.main())


def test_main_graceful_shutdown_event_set_raises(monkeypatch):
    # Ensure TOKEN present
    monkeypatch.setattr(m, "TOKEN", "tkn", raising=False)

    class Cfg:
        def __init__(self):
            self.check_interval = 0
            self.auto_update = False
            self.debug = False
            self.dev_channel = False
            self.notifications = False

    monkeypatch.setattr(m, "AddonConfig", Cfg)
    monkeypatch.setattr(m, "NotificationService", lambda enabled: None)

    class Service:
        def __init__(self):
            self.stopped = 0
        def stop(self):
            self.stopped += 1

    class Orch:
        def __init__(self, *a, **k):
            self._cfg = types.SimpleNamespace(dev_channel=False)
            self._mqtt_service = Service()
        def auto_cycle_once(self):
            raise SystemExit(0)

    monkeypatch.setattr(m, "UpdateOrchestrator", Orch)

    # Event whose set() raises to cover except branch inside shutdown handler
    class FakeEvent:
        def __init__(self):
            self._flag = False
        def set(self):
            raise RuntimeError("fail set")
        def is_set(self):
            return self._flag
        async def wait(self):
            return None

    monkeypatch.setattr(m.asyncio, "Event", FakeEvent)

    async def init_none(*a, **k):
        return None
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", init_none)

    class DummyLoop:
        async def run_in_executor(self, executor, func, *args):
            return func(*args)
        def add_signal_handler(self, sig, cb):
            # Invoke shutdown handler immediately
            cb()

    monkeypatch.setattr(m.asyncio, "get_running_loop", lambda: DummyLoop())

    with pytest.raises(SystemExit):
        asyncio.run(m.main())


def test_main_mqtt_init_grace_sleep_raises(monkeypatch):
    monkeypatch.setattr(m, "TOKEN", "tkn", raising=False)

    class Cfg:
        def __init__(self):
            self.check_interval = 0
            self.auto_update = False
            self.debug = False
            self.dev_channel = False
            self.notifications = False

    monkeypatch.setattr(m, "AddonConfig", Cfg)
    monkeypatch.setattr(m, "NotificationService", lambda enabled: None)

    class FlappySvc:
        def __init__(self):
            self.calls = 0
        def is_ready(self):
            self.calls += 1
            return self.calls >= 2

    class Orch:
        def __init__(self, *a, **k):
            self._cfg = types.SimpleNamespace(dev_channel=False)
            self._mqtt_service = None
            self.calls = 0
        def auto_cycle_once(self):
            self.calls += 1
            if self.calls >= 2:
                raise SystemExit(0)
        def set_mqtt_service(self, svc):
            self._mqtt_service = svc

    monkeypatch.setattr(m, "UpdateOrchestrator", Orch)

    async def init_flappy(*a, **k):
        return FlappySvc()
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", init_flappy)

    # Sleep that raises only for the 2-second grace sleep
    async def sleep_cond(delay, *a, **k):
        if delay == 2:
            raise RuntimeError("boom")
        return None
    monkeypatch.setattr(m.asyncio, "sleep", sleep_cond)

    with pytest.raises(SystemExit):
        asyncio.run(m.main())


def test_main_outer_try_except_import_signal_failure(monkeypatch):
    monkeypatch.setattr(m, "TOKEN", "tkn", raising=False)

    class Cfg:
        def __init__(self):
            self.check_interval = 0
            self.auto_update = False
            self.debug = False
            self.dev_channel = False
            self.notifications = False

    monkeypatch.setattr(m, "AddonConfig", Cfg)
    monkeypatch.setattr(m, "NotificationService", lambda enabled: None)

    class Orch:
        def __init__(self, *a, **k):
            self._cfg = types.SimpleNamespace(dev_channel=False)
            self._mqtt_service = None
        def auto_cycle_once(self):
            raise SystemExit(0)

    monkeypatch.setattr(m, "UpdateOrchestrator", Orch)
    async def init_none(*a, **k):
        return None
    monkeypatch.setattr(m, "initialize_and_setup_mqtt", init_none)
    monkeypatch.setattr(m, "handle_mqtt_reconnection", lambda *a, **k: asyncio.sleep(0, result=(None, 0)))

    orig_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "signal":
            raise ImportError("no signal")
        return orig_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(SystemExit):
        asyncio.run(m.main())
