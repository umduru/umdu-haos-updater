import json
import types
import pytest

import app.mqtt_service as ms


class FakeMQTTClient:
    MQTTv311 = object()

    def __init__(self, client_id=None, protocol=None, clean_session=True):
        self.client_id = client_id
        self.protocol = protocol
        self.clean_session = clean_session
        self._logger = None
        self._published = []  # list of tuples: (topic, payload, retain, qos)
        self._subscriptions = []
        self._disconnected = False
        # callbacks set by service
        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None

    def enable_logger(self, logger):
        self._logger = logger

    def reconnect_delay_set(self, min_delay, max_delay):
        self._reconnect = (min_delay, max_delay)

    def will_set(self, topic, payload, retain=False, qos=0):
        # store will for inspection if needed
        self._will = (topic, payload, retain, qos)

    def username_pw_set(self, username, password):
        self._username = username
        self._password = password
    def tls_set(self, *a, **k):
        self._tls = True

    def connect(self, host, port, keepalive):
        self._conn = (host, port, keepalive)

    def loop_start(self):
        pass

    def subscribe(self, topic, qos=0):
        self._subscriptions.append((topic, qos))

    class _Info:
        def __init__(self, rc=0):
            self.rc = rc

        def wait_for_publish(self, timeout=None):
            return True

    def publish(self, topic, payload, retain=False, qos=0):
        self._published.append((topic, payload, retain, qos))
        return FakeMQTTClient._Info(rc=0)

    def disconnect(self):
        self._disconnected = True

    def loop_stop(self):
        pass


def patch_mqtt(monkeypatch, fake_cls=FakeMQTTClient):
    fake_mod = types.SimpleNamespace(Client=fake_cls, MQTTv311=FakeMQTTClient.MQTTv311)
    monkeypatch.setattr(ms, "mqtt", fake_mod, raising=True)


def test_stop_publishes_offline_before_disconnect(monkeypatch):
    patch_mqtt(monkeypatch)

    svc = ms.MqttService(host="h", port=1883, username=None, password=None, discovery=True)
    # replace client with fake instance to capture publishes
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = True
    svc._update_entity_active = True

    svc.stop()

    # offline must be retained with qos=1 before disconnect
    assert (ms.UPDATE_AVAIL_TOPIC, "offline", True, 1) in client._published
    assert client._disconnected is True


def test_publish_update_state_respects_connectivity(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = False
    svc.publish_update_state("1", "2", False)
    assert client._published == []  # nothing when not ready

    svc._connected = True
    svc.publish_update_state("1", "2", True)
    # state is not retained and qos=1 per implementation
    topic, payload, retain, qos = client._published[-1]
    assert topic == ms.STATE_TOPIC
    assert json.loads(payload) == {"installed_version": "1", "latest_version": "2", "in_progress": True}
    assert retain is False and qos == 1


def test_on_connect_subscribes_and_publishes_discovery(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client

    called = {"disc": False}
    def fake_disc():
        called["disc"] = True
    svc._publish_discovery = fake_disc

    svc._on_connect(client, None, None, 0)
    assert svc._connected is True
    assert (ms.COMMAND_TOPIC, 1) in client._subscriptions
    assert called["disc"] is True


def test_commands_install_and_clear(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = True

    called = {"install": 0, "clear": 0}
    svc.on_install_cmd = lambda: called.__setitem__("install", called["install"] + 1)

    # clear should publish to both retained topics and then discovery again
    svc.clear_retained_messages = lambda: called.__setitem__("clear", called["clear"] + 1)
    svc._publish_discovery = lambda: called.__setitem__("disc", called.get("disc", 0) + 1)

    svc._handle_command("install")
    svc._handle_command("clear")

    assert called["install"] == 1
    assert called["clear"] == 1


def test_publish_discovery_payload_and_initial_state(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = True
    svc.set_initial_versions("1.0", "2.0")

    svc._publish_discovery()

    # Discovery config retained publish
    disc = [p for p in client._published if p[0] == ms.UPDATE_DISC_TOPIC]
    assert disc, "Discovery config not published"
    payload = json.loads(disc[-1][1])
    assert payload["state_topic"] == ms.STATE_TOPIC
    assert payload["command_topic"] == ms.COMMAND_TOPIC
    assert payload["availability_topic"] == ms.UPDATE_AVAIL_TOPIC

    # Availability online publish
    avail = [p for p in client._published if p[0] == ms.UPDATE_AVAIL_TOPIC]
    assert avail and avail[-1][1] == "online"

    # Initial state published retained so HA doesn't miss it
    st = [p for p in client._published if p[0] == ms.STATE_TOPIC]
    assert st and st[-1][2] is True


def test_requires_discovery_decorator_skips(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h", discovery=False)
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = True
    # decorated methods should no-op
    svc.clear_retained_messages()
    svc.deactivate_update_entity()
    assert client._published == []


def test_username_password_set(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h", username="user", password="pass")
    assert svc._client._username == "user"


def test_start_success_and_error_paths(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h", use_tls=True)
    client = FakeMQTTClient()
    svc._client = client
    svc.start()  # should not raise
    assert getattr(client, "_tls", False) is True

    # error path
    class BadClient(FakeMQTTClient):
        def connect(self, host, port, keepalive):
            raise RuntimeError("boom")

    patch_mqtt(monkeypatch, BadClient)
    svc = ms.MqttService(host="h")
    with pytest.raises(Exception):
        svc.start()


def test_start_tls_set_failure(monkeypatch):
    class BadTLSClient(FakeMQTTClient):
        def tls_set(self, *a, **k):
            raise RuntimeError("tls")

    patch_mqtt(monkeypatch, BadTLSClient)
    svc = ms.MqttService(host="h", use_tls=True)
    client = BadTLSClient()
    svc._client = client
    # Should not raise despite tls_set failure
    svc.start()
    # Connected anyway
    assert getattr(client, "_conn", None) is not None


def test_availability_publish_and_deactivate(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = False
    svc.publish_update_availability(True)  # early return when not ready
    assert client._published == []

    svc._connected = True
    svc.deactivate_update_entity()
    # offline retained published and entity deactivated
    assert any(t == ms.UPDATE_AVAIL_TOPIC and p == "offline" for (t, p, *_ ) in client._published)


def test_connect_and_disconnect_callbacks(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    # failure rc
    svc._on_connect(client, None, None, 1)
    assert svc._connected is False
    # disconnect path
    svc._connected = True
    svc._on_disconnect(client, None, 0)
    assert svc._connected is False


def test_on_message_and_publish_variants(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = False
    # _publish early return when not connected
    svc._publish("x", "y")

    # non-zero rc warning branch
    svc._connected = True

    class Info:
        def __init__(self, rc):
            self.rc = rc

        def wait_for_publish(self, timeout=None):
            return True

    def bad_publish(topic, payload, retain=False, qos=0):
        return Info(1)

    client.publish = bad_publish
    svc._publish("x", "y")

    # on_message with command
    class Msg:
        def __init__(self, topic, payload):
            self.topic = topic
            self.payload = payload

    called = {"ok": 0}
    svc.on_install_cmd = lambda: called.__setitem__("ok", 1)
    svc._on_message(client, None, Msg(ms.COMMAND_TOPIC, b"install"))
    assert called["ok"] == 1


def test_stop_exceptions_are_swallowed(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = True

    def raise_publish(*a, **k):
        raise RuntimeError("pub")

    def raise_loop_stop():
        raise RuntimeError("loop")

    client.publish = raise_publish
    client.loop_stop = raise_loop_stop
    # should not raise
    svc.stop()


def test_clear_retained_messages_body(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = True
    svc.clear_retained_messages()
    topics = [t for t, *_ in client._published]
    assert ms.STATE_TOPIC in topics and ms.UPDATE_AVAIL_TOPIC in topics and ms.UPDATE_DISC_TOPIC in topics


def test_on_disconnect_offline_publish_error_handled(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = True
    svc.publish_update_availability = lambda online: (_ for _ in ()).throw(RuntimeError("x"))
    svc._on_disconnect(client, None, 0)
    assert svc._connected is False


def test_stop_disconnect_exception(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = True

    def bad_disconnect():
        raise RuntimeError("x")

    client.disconnect = bad_disconnect
    svc.stop()


def test_on_connect_non_int_rc(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    # rc as non-int triggers except branch in conversion
    svc._on_connect(client, None, None, object())
    assert svc._connected is False


def test_on_disconnect_non_int_rc(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    svc._connected = True
    # rc as non-int; should not raise
    svc._on_disconnect(client, None, object())
    assert svc._connected is False


def test_maybe_migrate_discovery_marker_exists_noop(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    # Force marker.exists() -> True so method returns early without publish
    marker = ms.Path("/data/.umdu_haos_updater_discovery_migrated_v1")
    orig_exists = marker.__class__.exists
    def exists_only_marker(self):
        # Return True only for the migration marker path
        try:
            return str(self) == str(marker)
        except Exception:
            return orig_exists(self)
    monkeypatch.setattr(marker.__class__, "exists", exists_only_marker)
    # Invoke private method
    svc._maybe_migrate_discovery()
    # No publish should happen
    assert client._published == []


def test_migrate_discovery_publish_exception_handled(monkeypatch):
    patch_mqtt(monkeypatch)
    svc = ms.MqttService(host="h")
    client = FakeMQTTClient()
    svc._client = client
    # Ensure marker does not exist so publish is attempted
    marker = ms.Path("/data/.umdu_haos_updater_discovery_migrated_v1")
    monkeypatch.setattr(marker.__class__, "exists", lambda self: False)

    def raise_publish(*a, **k):
        raise RuntimeError("pub")
    client.publish = raise_publish

    # Should swallow exception and not raise
    svc._maybe_migrate_discovery()
