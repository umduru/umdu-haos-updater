import hashlib
from pathlib import Path
import types

import pytest

import app.updater as upd
from app.errors import NetworkError, DownloadError


class FakeResp:
    def __init__(self, payload=None, status=200, content=b""):
        self._payload = payload
        self.status_code = status
        self._content = content

    # context manager support
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(response=types.SimpleNamespace(status_code=self.status_code))

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


def test_fetch_available_update_variants(monkeypatch):
    # stable: string value
    def fake_get(url, timeout=None):
        return FakeResp({"hassos": {"umdu-k1": "16.0.0"}})

    monkeypatch.setattr(upd, "requests", types.SimpleNamespace(get=fake_get))
    info = upd.fetch_available_update()
    assert info.version == "16.0.0" and info.sha256 is None

    # dict with sha256
    def fake_get2(url, timeout=None):
        return FakeResp({"hassos": {"umdu-k1": {"version": "16.1.0", "sha256": "abc"}}})

    monkeypatch.setattr(upd, "requests", types.SimpleNamespace(get=fake_get2))
    info = upd.fetch_available_update()
    assert info.version == "16.1.0" and info.sha256 == "abc"


def test_fetch_available_update_error_raises_network(monkeypatch):
    def fake_get(url, timeout=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(upd, "requests", types.SimpleNamespace(get=fake_get))
    with pytest.raises(NetworkError):
        upd.fetch_available_update()


def test_is_newer_logic():
    assert upd.is_newer("2.0.0", "1.0.0") is True
    assert upd.is_newer("1.0.0", "1.0.0") is False
    # fallback lexicographic branch
    assert upd.is_newer("b", "a") is True


def test_download_update_with_sha_ok_and_cleanup(tmp_path, monkeypatch):
    # Point SHARE_DIR to temp
    monkeypatch.setattr(upd, "SHARE_DIR", tmp_path)
    content = b"abc" * 1024
    sha = hashlib.sha256(content).hexdigest()

    # make an old bundle to be cleaned up
    old = tmp_path / "haos_umdu-k1-old.raucb"
    old.write_bytes(b"old")

    def fake_get(url, stream=True, timeout=None):
        return FakeResp(status=200, content=content)

    monkeypatch.setattr(upd, "requests", types.SimpleNamespace(get=fake_get))

    info = upd.UpdateInfo("16.0.0", sha256=sha)
    path = upd.download_update(info)

    assert path.exists()
    assert not old.exists(), "Old bundle was not cleaned"


def test_download_update_sha_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(upd, "SHARE_DIR", tmp_path)
    content = b"abc"

    def fake_get(url, stream=True, timeout=None):
        return FakeResp(status=200, content=content)

    monkeypatch.setattr(upd, "requests", types.SimpleNamespace(get=fake_get))
    info = upd.UpdateInfo("16.0.1", sha256="deadbeef")

    with pytest.raises(DownloadError):
        upd.download_update(info)


def test_check_for_update_and_download(monkeypatch, tmp_path):
    # current older than available
    monkeypatch.setattr(upd, "get_current_haos_version", lambda: "1.0.0")
    monkeypatch.setattr(upd, "fetch_available_update", lambda dev_channel=False: upd.UpdateInfo("1.1.0"))

    called = {}
    fake_path = tmp_path / "f.raucb"
    monkeypatch.setattr(upd, "download_update", lambda info, orchestrator=None: fake_path)

    p = upd.check_for_update_and_download(auto_download=True)
    assert p == fake_path

    # when not auto_download -> None
    p2 = upd.check_for_update_and_download(auto_download=False)
    assert p2 is None

    # Network error path -> None
    def raise_net(*a, **k):
        raise NetworkError("err")

    monkeypatch.setattr(upd, "fetch_available_update", raise_net)
    assert upd.check_for_update_and_download() is None


def test_download_progress_context_manager():
    class O:
        def __init__(self):
            self._in_progress = False
            self.calls = 0

        def publish_state(self, latest=None):
            self.calls += 1

    o = O()
    with upd._download_progress(o, "1.0"):
        assert o._in_progress is True
    assert o._in_progress is False and o.calls == 2


def test_download_update_path_exists_no_sha(tmp_path, monkeypatch):
    monkeypatch.setattr(upd, "SHARE_DIR", tmp_path)
    info = upd.UpdateInfo("16.2.0")
    p = info.download_path
    p.write_bytes(b"x")
    assert upd.download_update(info).exists()


def test_download_update_request_and_generic_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(upd, "SHARE_DIR", tmp_path)
    info = upd.UpdateInfo("16.3.0", sha256="deadbeef")

    class RqErr(Exception):
        pass

    import requests

    def raise_requests(url, stream=True, timeout=None):
        raise requests.RequestException("boom")

    def raise_generic(url, stream=True, timeout=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(upd.requests, "get", raise_requests)
    with pytest.raises(DownloadError):
        upd.download_update(info)

    monkeypatch.setattr(upd.requests, "get", raise_generic)
    with pytest.raises(DownloadError):
        upd.download_update(info)


def test_download_update_existing_with_sha_and_mismatch_precheck(tmp_path, monkeypatch):
    monkeypatch.setattr(upd, "SHARE_DIR", tmp_path)
    info = upd.UpdateInfo("16.4.0", sha256="00")
    p = info.download_path
    p.write_bytes(b"data")
    # make requests return something small to continue
    def fake_get(url, stream=True, timeout=None):
        return FakeResp(status=200, content=b"x")
    monkeypatch.setattr(upd.requests, "get", fake_get)
    # should unlink and attempt redownload, then fail hash check
    with pytest.raises(DownloadError):
        upd.download_update(info)


def test_download_update_existing_with_sha_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(upd, "SHARE_DIR", tmp_path)
    content = b"abc" * 1024
    sha = hashlib.sha256(content).hexdigest()
    info = upd.UpdateInfo("16.5.0", sha256=sha)
    p = info.download_path
    p.write_bytes(content)
    # Should return existing without redownload
    assert upd.download_update(info) == p


def test_check_for_update_none_current(monkeypatch):
    monkeypatch.setattr(upd, "get_current_haos_version", lambda: None)
    assert upd.check_for_update_and_download() is None


def test_check_for_update_download_error(monkeypatch):
    monkeypatch.setattr(upd, "get_current_haos_version", lambda: "1.0")
    monkeypatch.setattr(upd, "fetch_available_update", lambda dev_channel=False: upd.UpdateInfo("1.1"))
    def raise_dl(info, orchestrator=None):
        raise DownloadError("x")
    monkeypatch.setattr(upd, "download_update", raise_dl)
    assert upd.check_for_update_and_download(auto_download=True) is None


def test_check_for_update_uptodate(monkeypatch):
    monkeypatch.setattr(upd, "get_current_haos_version", lambda: "1.0")
    monkeypatch.setattr(upd, "fetch_available_update", lambda dev_channel=False: upd.UpdateInfo("1.0"))
    assert upd.check_for_update_and_download() is None
