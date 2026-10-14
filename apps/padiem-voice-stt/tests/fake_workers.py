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
from datetime import datetime, timedelta, timezone
from typing import Any


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


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
    def __init__(self, method="GET", url="https://voice.internal/", headers=None, body=b"", chunk=4096):
        # The real ``workers.Request`` exposes ``method`` as an
        # ``http.HTTPMethod`` member, so the fake does the same shape.
        self.method = _as_method(method)
        self.url = url
        self.headers = FakeHeaders({k.lower(): v for k, v in (headers or {}).items()})
        self._body = body
        self.body = _Stream(body, chunk=chunk)
        self._read = False


class FakeUpstream:
    """Upstream response stand-in.

    ``payload`` may be a dict (serialised as JSON) or a raw string. ``hang_body``
    mimics the failure the end-to-end deadline must catch: headers are already
    "answered", then the body never finishes, which is exactly what a
    header-only timeout would miss.
    """

    def __init__(self, status=200, payload=None, hang_body=False, raw=None):
        self.status = status
        self._payload = payload if payload is not None else {}
        self.hang_body = hang_body
        self._raw = raw
        self.body_reads = 0
        # Model the production Response.body stream, not a body.text() shortcut.
        self.body = types.SimpleNamespace(getReader=lambda: _ResponseReader(self))

    async def text(self):
        self.body_reads += 1
        if self.hang_body:
            await asyncio.sleep(3600)
        if self._raw is not None:
            return self._raw
        import json

        return json.dumps(self._payload)

    async def json(self):
        self.body_reads += 1
        if self.hang_body:
            await asyncio.sleep(3600)
        return self._payload


class _ResponseReader:
    """Provider stream: count each actual read and support a hanging body."""

    def __init__(self, upstream):
        import json

        self._upstream = upstream
        content = upstream._raw if upstream._raw is not None else json.dumps(upstream._payload)
        self._reader = _Stream(content.encode("utf-8"), chunk=4096).getReader()

    async def read(self):
        self._upstream.body_reads += 1
        if self._upstream.hang_body:
            await asyncio.sleep(3600)
        return await self._reader.read()

    def releaseLock(self):
        self._reader.releaseLock()


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


#: Sentinel so ``decision=None`` means an explicit "no verdict" rather than
#: "fall back to the approving decoy default".
_NO_DECISION = object()

#: Canonical Control Plane facts the fakes below mirror. The real values come from
#: ``packages/padiem-control-plane``; nothing here is production data. The
#: timestamps are derived from the current UTC clock so a fixture can never go
#: stale, while remaining unambiguous about which instant each test manipulates.
CP_PRODUCT = "b62"
CP_SESSION = "sess-local3-fixture"
CP_SUBJECT = "user-local3-fixture"
CP_TENANT = "tenant_local3fixture0000000000000000ab"
CP_SNAPSHOT_REVISION = "voice-e1.s7.deadbeef"
CP_RESERVATION_REF = "res-local3-fixture"
#: The instant a fixture claims it was issued at (roughly "now").
CP_NOW = _iso(_clock() - timedelta(seconds=5))
#: A comfortably future instant, so a fixture is active until a test says else.
CP_SESSION_EXPIRES = _iso(_clock() + timedelta(hours=1))
#: Two clearly past instants, so an "expired" fixture stays internally consistent
#: (issued before expiry) instead of tripping the malformed-timestamp check.
CP_RESERVED_PAST = _iso(_clock() - timedelta(hours=2))
CP_PAST = _iso(_clock() - timedelta(hours=1))


def cp_session_payload(**overrides):
    """A canonical ACTIVE session as ``CONTROL_PLANE_IDENTITY`` returns it."""
    payload = {
        "session_id": CP_SESSION,
        "product_id": CP_PRODUCT,
        "subject": {"subject_type": "user", "subject_id": CP_SUBJECT},
        "issued_at": CP_NOW,
        "expires_at": CP_SESSION_EXPIRES,
        "state": "active",
        "revision": 7,
        "tenant_id": CP_TENANT,
    }
    payload.update(overrides)
    return payload


def cp_snapshot_payload(*grants, **overrides):
    """An entitlement snapshot carrying exactly ``grants``."""
    payload = {
        "snapshot_id": "ent-local3-fixture",
        "product_id": CP_PRODUCT,
        "subject": {"subject_type": "user", "subject_id": CP_SUBJECT},
        "revision": CP_SNAPSHOT_REVISION,
        "issued_at": CP_NOW,
        "expires_at": CP_SESSION_EXPIRES,
        "grants": [
            {"key": key, "allowed": allowed, "limit": limit} for key, allowed, limit in grants
        ],
    }
    payload.update(overrides)
    return payload


def cp_reservation_payload(**overrides):
    payload = {
        "reservation_ref": CP_RESERVATION_REF,
        "admitted": True,
        "reserved_at": CP_NOW,
        "expires_at": CP_SESSION_EXPIRES,
    }
    payload.update(overrides)
    return payload


def voice_grant(limit=None):
    return ("voice.stt.transcribe", True, limit)


def live_token_grant(limit=None):
    return ("voice.stt.live_token", True, limit)


class FakeIdentityBinding:
    """Stands in for the private ``CONTROL_PLANE_IDENTITY`` Service Binding."""

    def __init__(self, session=None, *, missing=False, raises=None):
        self.session = cp_session_payload() if session is None else session
        self.missing = missing
        self.raises = raises
        self.calls: list[dict] = []

    async def resolve_auth_session(self, payload):
        self.calls.append(dict(payload or {}))
        if self.raises is not None:
            raise self.raises
        if self.missing or self.session is None:
            return {"ok": False, "error": {"code": "auth_session_not_found"}}
        return {"ok": True, "session": self.session}


class FakeAdmissionBinding:
    """Stands in for ``CONTROL_PLANE_ENGINE_ADMISSION``: snapshot + reservation."""

    def __init__(self, *, snapshot=None, reservation=None, raises=None, admitted=True):
        self.snapshot = cp_snapshot_payload(voice_grant(), live_token_grant()) if snapshot is None else snapshot
        self.reservation = (
            cp_reservation_payload(admitted=admitted) if reservation is None else reservation
        )
        self.raises = raises
        self.snapshot_calls: list[dict] = []
        self.reservation_calls: list[dict] = []

    async def fetch_entitlement_snapshot(self, payload):
        self.snapshot_calls.append(dict(payload or {}))
        if self.raises is not None:
            raise self.raises
        return {"ok": True, "snapshot": self.snapshot}

    async def reserve_usage(self, payload):
        self.reservation_calls.append(dict(payload or {}))
        if self.raises is not None:
            raise self.raises
        return {"ok": True, "reservation": self.reservation}


class FakeApprovingDecoyGuard:
    """A **decoy** bound to the retired ``VOICE_STT_CALLER_GUARD`` name.

    It would approve anything it is asked. The Worker must ignore it entirely:
    the paid-route authority is the Control Plane pair, so this object — however
    approving — may not open a route. ``calls`` therefore stays empty and the
    tests assert exactly that.
    """

    def __init__(self, decision=_NO_DECISION):
        self.decision = (
            decision
            if decision is not _NO_DECISION
            else {"allowed": True, "caller": "acct-fixture", "cost_scope": {"daily_usd_cap": 5}}
        )
        self.calls: list[dict] = []

    async def authorize(self, request_context):
        self.calls.append(dict(request_context or {}))
        return self.decision

    def authorize_caller(self, request_context):  # pragma: no cover - must never be reached
        self.calls.append(dict(request_context or {}))
        return self.decision

    async def verify(self, request_context):  # pragma: no cover - must never be reached
        self.calls.append(dict(request_context or {}))
        return self.decision


def caller_headers(**overrides):
    """The two opaque clues a product Worker presents; never an identity."""
    headers = {
        "x-padiem-product-id": CP_PRODUCT,
        "x-padiem-auth-session-id": CP_SESSION,
    }
    headers.update(overrides)
    return headers


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
    """An env that passes the deployment flag and carries both CP bindings.

    The bindings are **fakes** standing in for the canonical Control Plane. Tests
    that must prove a denial set ``CONTROL_PLANE_ENGINE_ADMISSION``/``CONTROL_PLANE_IDENTITY``
    to ``None`` or swap in a refusing payload.
    """
    env = types.SimpleNamespace(
        PADIEM_VOICE_STT_ENABLED="true",
        CONTROL_PLANE_IDENTITY=FakeIdentityBinding(),
        CONTROL_PLANE_ENGINE_ADMISSION=FakeAdmissionBinding(),
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
