from pathlib import Path
import types

import pytest

import app.rauc_installer as ri
from app.errors import InstallError


def test_install_bundle_missing_file():
    with pytest.raises(InstallError):
        ri.install_bundle(Path("/share/umdu-haos-updater/missing.raucb"))


class FP:
    def __init__(self, lines=None, rc=0):
        self._lines = lines or ["line1", "line2"]
        self._rc = rc
        self.stdout = (l + "\n" for l in self._lines)

    def wait(self):
        return self._rc


def test_install_bundle_success(monkeypatch):
    # Make Path.exists True for /share/...
    orig_exists = ri.Path.exists
    monkeypatch.setattr(ri.Path, "exists", lambda p: True if str(p).startswith("/share/") else orig_exists(p))
    # no-op link creation
    monkeypatch.setattr(ri, "_ensure_share_link", lambda: None)

    def fake_popen(args, stdout=None, stderr=None, text=None):
        return FP(rc=0)

    monkeypatch.setattr(ri, "subprocess", types.SimpleNamespace(Popen=fake_popen, PIPE=object(), STDOUT=object()))

    assert ri.install_bundle(Path("/share/umdu-haos-updater/test.raucb")) is True


def test_install_bundle_error_rc(monkeypatch):
    orig_exists = ri.Path.exists
    monkeypatch.setattr(ri.Path, "exists", lambda p: True if str(p).startswith("/share/") else orig_exists(p))
    monkeypatch.setattr(ri, "_ensure_share_link", lambda: None)

    def fake_popen(args, stdout=None, stderr=None, text=None):
        return FP(rc=1)

    monkeypatch.setattr(ri, "subprocess", types.SimpleNamespace(Popen=fake_popen, PIPE=object(), STDOUT=object()))

    with pytest.raises(InstallError):
        ri.install_bundle(Path("/share/umdu-haos-updater/test.raucb"))


def test_install_bundle_file_not_found(monkeypatch):
    # Make Path.exists True for /share/...
    orig_exists = ri.Path.exists
    monkeypatch.setattr(ri.Path, "exists", lambda p: True if str(p).startswith("/share/") else orig_exists(p))
    monkeypatch.setattr(ri, "_ensure_share_link", lambda: None)

    def fake_popen(args, stdout=None, stderr=None, text=None):
        raise FileNotFoundError("rauc not found")

    monkeypatch.setattr(ri, "subprocess", types.SimpleNamespace(Popen=fake_popen, PIPE=object(), STDOUT=object()))
    with pytest.raises(InstallError):
        ri.install_bundle(Path("/share/umdu-haos-updater/test.raucb"))


def test_install_bundle_generic_exception(monkeypatch):
    orig_exists = ri.Path.exists
    monkeypatch.setattr(ri.Path, "exists", lambda p: True if str(p).startswith("/share/") else orig_exists(p))
    monkeypatch.setattr(ri, "_ensure_share_link", lambda: None)

    def fake_popen(args, stdout=None, stderr=None, text=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(ri, "subprocess", types.SimpleNamespace(Popen=fake_popen, PIPE=object(), STDOUT=object()))
    with pytest.raises(InstallError):
        ri.install_bundle(Path("/share/umdu-haos-updater/test.raucb"))


def test_ensure_share_link_paths(monkeypatch):
    # force non-existing, then simulate success
    calls = {"symlink": 0}

    class P(type(ri.Path("/"))):
        pass

    def fake_exists(self):
        return False

    def fake_mkdir(self, parents=False, exist_ok=False):
        return None

    def fake_symlink_to(self, target):
        calls["symlink"] += 1

    monkeypatch.setattr(ri, "Path", ri.Path)
    share_link = ri.Path("/mnt/data/supervisor/share")
    monkeypatch.setattr(share_link.__class__, "exists", lambda self: False)
    monkeypatch.setattr(share_link.parent.__class__, "mkdir", fake_mkdir)
    monkeypatch.setattr(share_link.__class__, "symlink_to", lambda self, t: calls.__setitem__("symlink", calls["symlink"] + 1))

    # Call private function
    ri._ensure_share_link()
    assert calls["symlink"] == 1


def test_ensure_share_link_symlink_error(monkeypatch):
    share_link = ri.Path("/mnt/data/supervisor/share")
    monkeypatch.setattr(share_link.__class__, "exists", lambda self: False)
    monkeypatch.setattr(share_link.parent.__class__, "mkdir", lambda self, parents=True, exist_ok=True: None)
    def raise_symlink(self, target):
        raise RuntimeError("x")
    monkeypatch.setattr(share_link.__class__, "symlink_to", raise_symlink)
    # Should not raise
    ri._ensure_share_link()
