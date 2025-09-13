import json
from pathlib import Path

import app.config as cfg_mod


def write_opts(tmp_path: Path, data: dict):
    p = tmp_path / "options.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_config_defaults_and_validation(tmp_path, monkeypatch):
    # no file -> defaults
    ac = cfg_mod.AddonConfig(options_path=tmp_path / "missing.json")
    assert ac.check_interval == 86400
    assert ac.mqtt_port == 1883

    # invalid port -> reset to 1883
    p = write_opts(tmp_path, {"mqtt_port": "notnum"})
    ac = cfg_mod.AddonConfig(options_path=p)
    assert ac.mqtt_port == 1883


def test_get_mqtt_params_uses_supervisor_when_needed(tmp_path, monkeypatch):
    p = write_opts(tmp_path, {
        "mqtt_host": "core-mosquitto",
        "mqtt_user": "",
        "mqtt_password": "",
    })

    ac = cfg_mod.AddonConfig(options_path=p)

    # supervisor returns config
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tkn")
    called = {}

    import app.supervisor_api as sup

    def fake_get_mqtt_service():
        called["get"] = True
        return {"host": "broker", "port": 1884, "username": "u", "password": "p"}

    monkeypatch.setattr(sup, "get_mqtt_service", fake_get_mqtt_service, raising=True)

    host, port, user, pwd, tls = ac.get_mqtt_params()
    assert host == "broker" and port == 1884 and user == "u" and pwd == "p" and tls is False


def test_validate_port_out_of_range(tmp_path):
    p = write_opts(tmp_path, {"mqtt_port": 70000})
    ac = cfg_mod.AddonConfig(options_path=p)
    assert ac.mqtt_port == 1883


def test_get_mqtt_params_supervisor_none(tmp_path, monkeypatch):
    p = write_opts(tmp_path, {"mqtt_host": "", "mqtt_user": "", "mqtt_password": ""})
    ac = cfg_mod.AddonConfig(options_path=p)
    import app.supervisor_api as sup
    monkeypatch.setattr(sup, "get_mqtt_service", lambda: None)
    host, port, user, pwd, tls = ac.get_mqtt_params()
    # нет учёток -> host None
    assert host is None and user is None and pwd is None


def test_get_mqtt_params_supervisor_error_branches(tmp_path, monkeypatch):
    p = write_opts(tmp_path, {"mqtt_host": "", "mqtt_user": "", "mqtt_password": ""})
    ac = cfg_mod.AddonConfig(options_path=p)
    import app.supervisor_api as sup
    from app.errors import SupervisorError

    # not ready path
    monkeypatch.setattr(sup, "get_mqtt_service", lambda: (_ for _ in ()).throw(SupervisorError("not ready yet")))
    host, *_ = ac.get_mqtt_params()
    assert host is None

    # other error path
    monkeypatch.setattr(sup, "get_mqtt_service", lambda: (_ for _ in ()).throw(SupervisorError("boom")))
    host, *_ = ac.get_mqtt_params()
    assert host is None


def test_get_mqtt_params_tls_from_supervisor(tmp_path, monkeypatch):
    p = write_opts(tmp_path, {"mqtt_host": "core-mosquitto"})
    ac = cfg_mod.AddonConfig(options_path=p)
    import app.supervisor_api as sup
    def fake_sup():
        return {"host": "h", "port": 8883, "username": "u", "password": "p", "ssl": True}
    monkeypatch.setattr(sup, "get_mqtt_service", fake_sup)
    host, port, user, pwd, tls = ac.get_mqtt_params()
    assert host == "h" and port == 8883 and tls is True
