"""In-process fake of the Cloudflare Workers runtime.

``worker.py`` imports ``workers``, which cannot be imported on CPython (it needs
the Pyodide ``js`` module). This module installs a minimal, honest stand-in so
the actual ``Default.fetch`` dispatch path can be exercised on a developer
machine: routes, the OFF gate, body bounds, the bound-route error envelopes and
the upstream call budget are all driven through the real handler code.

The fake is deliberately *hostile in the right ways*: it mimics a request whose
body is a readable stream with no ``Content-Length``, a Secrets-Store-style
binding handle that must be awaited, and an upstream that can be made to hang or
to fail.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any


class FakeResponse:
    """Mimics ``workers.Response``: positional body + keyword status/headers."""

    def __init__(self, body: Any = None, status: int = 200, headers: dict | None = None):
        self.body = body
        self.status = status
        self.headers = dict(headers or {})

    async def json(self):
        import json

        return json.loads(self.body)

    async def text(self):
        return self.body


class FakeHeaders(dict):
    def get(self, key, default=None):
        return dict.get(self, key.lower(), default)


class FakeRequest:
    def __init__(self, method="GET", url="https://voice.internal/", headers=None, body=b""):
        # The real ``workers.Request`` exposes ``method`` as an
        # ``http.HTTPMethod`` member, so the fake does the same shape.
        self.method = _as_method(method)
        self.url = url
        self.headers = FakeHeaders({k.lower(): v for k, v in (headers or {}).items()})
        self._body = body
        self.body = _Stream(body)
        self._read = False


class FakeUpstream:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload if payload is not None else {}

    async def json(self):
        return self._payload


class _Stream:
    """A JS-ReadableStream-like object exposing ``getReader()``.

    The reader is memoised: a real stream advances one consumer, and returning a
    fresh reader per call would replay the body from byte zero, which is a fake
    bug rather than a realistic stand-in.
    """

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


def _as_method(method):
    return types.SimpleNamespace(name=str(method).upper())


class FetchBudget:
    """Records every upstream call the Worker actually attempted."""

    def __init__(self):
        self.calls: list[dict] = []
        self.response = FakeUpstream()
        self.hang = False
        self.raise_exc = False

    def make_fetch(self):
        budget = self

        async def _fetch(resource, **kwargs):
            budget.calls.append(
                {
                    "url": resource if isinstance(resource, str) else str(resource),
                    "method": kwargs.get("method"),
                    "headers": dict(kwargs.get("headers") or {}),
                    "body": kwargs.get("body"),
                    "signal": kwargs.get("signal"),
                }
            )
            if budget.hang:
                await asyncio.sleep(3600)
            if budget.raise_exc:
                raise OSError("upstream refused")
            return budget.response

        return _fetch


class FakeWorkerEntrypoint:
    """Mimics ``workers.WorkerEntrypoint``: the runtime assigns ``env``."""

    def __init__(self, env=None):
        self.env = env


class FakeSecretsBinding:
    """A Cloudflare Secrets Store binding handle: async ``get()``, never a str."""

    def __init__(self, value):
        self._value = value
        self.reads = 0

    async def get(self):
        self.reads += 1
        if self._value is None:
            raise RuntimeError("binding unavailable")
        return self._value


def install_workers_module():
    """Install the fake ``workers`` module and import the real ``worker``."""
    module = types.ModuleType("workers")
    module.Response = FakeResponse
    module.WorkerEntrypoint = FakeWorkerEntrypoint
    module.FormData = object
    module.Blob = object
    module.Request = FakeRequest

    def _fetch(*args, **kwargs):
        raise AssertionError("worker.fetch must be patched per test")

    module.fetch = _fetch
    sys.modules["workers"] = module
    sys.modules.pop("worker", None)

    import importlib

    return importlib.import_module("worker")


def enabled_env(**overrides):
    """An env that passes the deployment gate (only reachable with a caller guard)."""
    env = types.SimpleNamespace(
        PADIEM_VOICE_STT_ENABLED="true",
        VOICE_STT_CALLER_GUARD=types.SimpleNamespace(),
        PADIEM_GROQ_API_KEY=FakeSecretsBinding("groq-key-value"),
        PADIEM_GEMINI_API_KEY=FakeSecretsBinding("gemini-key-value"),
    )
    for key, value in overrides.items():
        setattr(env, key, value)
    return env


def disabled_env(**overrides):
    """The shipped default: the gate is closed and nothing is readable."""
    env = types.SimpleNamespace(
        PADIEM_VOICE_STT_ENABLED="false",
        PADIEM_GROQ_API_KEY=FakeSecretsBinding("groq-key-value"),
        PADIEM_GEMINI_API_KEY=FakeSecretsBinding("gemini-key-value"),
    )
    for key, value in overrides.items():
        setattr(env, key, value)
    return env
