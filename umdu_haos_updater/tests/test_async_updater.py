"""Async tests for updater module."""

from __future__ import annotations

import asyncio
from pathlib import Path
import hashlib

import pytest  # type: ignore

from app import updater as upd


class FakeResp:
    def __init__(self, payload):  # type: ignore[no-untyped-def]
        self._payload = payload
        self.status = 200

    async def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError("error")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, payload):  # type: ignore[no-untyped-def]
        self._payload = payload

    def get(self, *a, **kw):  # noqa: D401
        return FakeResp(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_async_fetch_available_update(monkeypatch):
    versions = {"hassos": {"umdu-k1": {"version": "16.0.0", "sha256": "deadbeef"}}}
    monkeypatch.setattr("aiohttp.ClientSession", lambda: FakeSession(versions))

    info = await upd.async_fetch_available_update()
    assert info.version == "16.0.0"
    assert info.sha256 == "deadbeef"


@pytest.mark.asyncio
async def test_async_verify_sha256(tmp_path: Path):
    data = b"hello-world"
    f = tmp_path / "test.bin"
    f.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert await upd._async_verify_sha256(f, expected) is True