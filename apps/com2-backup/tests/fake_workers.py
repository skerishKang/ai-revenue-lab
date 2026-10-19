"""Minimal in-process Workers runtime plus an R2 double.

The double is a small in-memory object store that mirrors the R2 calls the
Worker actually makes: ``head``, ``get``, ``put``. There is deliberately no
``delete`` method, so a delete call would fail loudly instead of passing.
"""

from __future__ import annotations

import sys
import types
from typing import Any


class FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, headers: dict | None = None):
        self.body = body
        self.status = status
        self.headers = dict(headers or {})


class FakeHeaders(dict):
    def get(self, key, default=None):
        return dict.get(self, key.lower(), default)


class FakeRequest:
    def __init__(self, method="GET", url="https://backup.internal/", headers=None, body=b"", chunk=4096):
        self.method = types.SimpleNamespace(name=str(method).upper())
        self.url = url
        self.headers = FakeHeaders({k.lower(): v for k, v in (headers or {}).items()})
        self.body = _Stream(body, chunk=chunk)


class _Stream:
    def __init__(self, data: bytes, chunk: int = 4096):
        self._chunks = [data[i : i + chunk] for i in range(0, len(data), chunk)] or [b""]
        self._reader = None

    def getReader(self):
        if self._reader is None:
            self._reader = _Reader(self._chunks)
        return self._reader


class _Reader:
    def __init__(self, chunks):
        self._chunks = chunks
        self._index = 0

    async def read(self):
        if self._index >= len(self._chunks):
            return types.SimpleNamespace(done=True, value=None)
        value = self._chunks[self._index]
        self._index += 1
        return types.SimpleNamespace(done=False, value=value)

    def releaseLock(self):
        return None


class FakeWorkerEntrypoint:
    def __init__(self, env=None):
        self.env = env


class FakeR2:
    """In-memory R2 bucket exposing only the operations this slice uses."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict] = {}
        self.put_calls: list[str] = []
        self.fail_put = False
        self.fail_get = False

    async def get(self, key):
        if self.fail_get:
            raise RuntimeError("r2 unavailable")
        data = self.objects.get(key)
        if data is None:
            return None
        return types.SimpleNamespace(
            size=len(data), arrayBuffer=lambda: data, customMetadata={}
        )

    async def put(self, key, data, **kwargs):
        if self.fail_put:
            raise RuntimeError("r2 unavailable")
        self.put_calls.append(key)
        self.objects[key] = bytes(data)
        self.metadata[key] = dict(kwargs or {})
        return types.SimpleNamespace(key=key)


class FakeSecret:
    def __init__(self, value):
        self._value = value

    async def get(self):
        return self._value


def install_workers_module():
    module = types.ModuleType("workers")
    module.Response = FakeResponse
    module.WorkerEntrypoint = FakeWorkerEntrypoint
    module.Request = FakeRequest
    sys.modules["workers"] = module
    sys.modules.pop("worker", None)

    import importlib

    return importlib.import_module("worker")


TOKEN = "fixture-token-value"


def enabled_env(**overrides):
    env = types.SimpleNamespace(
        COM2_BACKUP_ENABLED="true",
        COM2_BACKUP_BUCKET=FakeR2(),
        COM2_BACKUP_WRITE_TOKEN=FakeSecret(TOKEN),
    )
    for key, value in overrides.items():
        setattr(env, key, value)
    return env


def disabled_env(**overrides):
    env = types.SimpleNamespace(
        COM2_BACKUP_ENABLED="false",
        COM2_BACKUP_BUCKET=FakeR2(),
        COM2_BACKUP_WRITE_TOKEN=FakeSecret(TOKEN),
    )
    for key, value in overrides.items():
        setattr(env, key, value)
    return env


def auth_headers(token=TOKEN, **overrides):
    headers = {"authorization": f"Bearer {token}"}
    headers.update(overrides)
    return headers
