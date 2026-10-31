"""#6417: signed request ids with replay refusal, and the staging identity instance.

The verifier must refuse a byte-identical replay inside the clock window, which
v1 could not do. An id is only an identity when it is part of the signature, so
a v1 proof carrying an id header is refused too. The staging instance is checked
to hold nothing that names production.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from internal_rpc_ingress import (  # noqa: E402
    SERVICE_ID_HEADER,
    handle_internal_rpc,
    proof_for,
    proof_for_v2,
    service_id_policy_from_env,
)
from service_id_replay import MemoryServiceIdReplayStore  # noqa: E402

SECRET = "replay-test-secret-" + "x" * 32
SERVICE_ID = "req-0000000000000001"
OTHER_ID = "req-0000000000000002"
PATH = "/internal/rpc/allowed_method"
BODY = b'{"a":1}'


class _URL:
    def __init__(self, url: str) -> None:
        self._url = url

    def __str__(self) -> str:
        return self._url


class _Headers(dict):
    def get(self, name, default=None):
        return super().get(str(name).lower(), default)


class _Request:
    def __init__(
        self, *, path: str = PATH, headers=None, body: bytes = BODY, method: str = "POST"
    ):
        self.url = _URL("https://w" + path)
        self.method = method
        self.headers = _Headers({k.lower(): v for k, v in (headers or {}).items()})
        self._body = body

    async def text(self) -> str:
        return self._body.decode("utf-8")


class _Dispatcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def allowed_method(self, payload: dict) -> dict:
        self.calls.append("allowed_method")
        return {"ok": True, "value": payload}


ALLOWED = frozenset({"allowed_method"})


def _signed(
    service_id: str | None = SERVICE_ID,
    *,
    at: int | None = None,
    version: int = 2,
    body: bytes = BODY,
):
    at = int(time.time()) if at is None else at
    headers = {"x-padiem-service-at": str(at)}
    if version == 2:
        assert service_id is not None
        headers[SERVICE_ID_HEADER] = service_id
        headers["x-padiem-service-proof"] = proof_for_v2(
            SECRET, method="POST", path=PATH, at=at, service_id=service_id, body=body
        )
    else:
        if service_id is not None:
            headers[SERVICE_ID_HEADER] = service_id
        headers["x-padiem-service-proof"] = proof_for(
            SECRET, method="POST", path=PATH, at=at, body=body
        )
    return _Request(headers=headers, body=body)


def _run(coro):
    return asyncio.run(coro)


def _call(request, *, policy="required", guard=None):
    return _run(
        handle_internal_rpc(
            request,
            secret=SECRET,
            allowed_methods=ALLOWED,
            dispatcher=_Dispatcher(),
            service_id_policy=policy,
            replay_guard=guard if guard is not None else MemoryServiceIdReplayStore(),
        )
    )


def test_an_id_must_be_present_and_signed() -> None:
    status, payload, _ = _call(_signed(None, version=1))
    assert status == 403 and payload["error"]["code"] == "rpc_service_id_required"

    # v1 proof + id header: the id is not inside the signature, so it is not an
    # identity. This is the difference between "names itself" and "is bound to".
    status, payload, _ = _call(_signed(version=1))
    assert status == 403 and payload["error"]["code"] == "rpc_service_id_unsigned"

    status, payload, _ = _call(_signed("bad id with spaces 000000000"))
    assert status == 403 and payload["error"]["code"] == "rpc_service_id_invalid"


def test_a_replay_inside_the_window_is_refused_and_a_new_id_is_not() -> None:
    guard = MemoryServiceIdReplayStore()
    request = _signed()

    first = _call(request, guard=guard)
    replay = _call(_signed(), guard=guard)
    fresh = _call(_signed(OTHER_ID), guard=guard)

    assert first[0] == 200
    assert replay[0] == 409 and replay[1]["error"]["code"] == "rpc_replay_detected"
    assert fresh[0] == 200


def test_outside_the_window_is_stale_before_replay_matters() -> None:
    guard = MemoryServiceIdReplayStore()
    assert _call(_signed(at=int(time.time()) - 3600), guard=guard)[0] == 403
    assert _call(_signed(at=int(time.time()) - 3600), guard=guard)[0] == 403


def test_a_missing_guard_fails_closed() -> None:
    status, payload, _ = _run(
        handle_internal_rpc(
            _signed(),
            secret=SECRET,
            allowed_methods=ALLOWED,
            dispatcher=_Dispatcher(),
            service_id_policy="required",
            replay_guard=None,
        )
    )
    assert status == 503 and payload["error"]["code"] == "rpc_replay_guard_unavailable"


def test_the_transitional_policy_still_accepts_an_unsigned_idless_request() -> None:
    assert _call(_signed(None, version=1), policy="optional")[0] == 200
    assert service_id_policy_from_env(None) == "optional"
    assert service_id_policy_from_env("REQUIRED") == "required"
    assert service_id_policy_from_env("nonsense") == "optional"


def test_memory_store_forgets_expired_ids() -> None:
    clock = [1_000_000]
    guard = MemoryServiceIdReplayStore(clock=lambda: clock[0])
    assert _run(guard.claim(SERVICE_ID, expires_at=1_000_010)) is True
    assert _run(guard.claim(SERVICE_ID, expires_at=1_000_010)) is False
    clock[0] = 1_000_011
    assert _run(guard.claim(SERVICE_ID, expires_at=1_000_020)) is True


# --- the identity Worker's own wiring ---------------------------------------

class _FakeResponse:
    def __init__(self, body="", *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, env=None):
        self.env = env


class _FakeDurableObject:
    def __init__(self, ctx=None, env=None):
        self.ctx = ctx
        self.env = env


class _ClaimStub:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    async def claim_service_id(self, payload: dict) -> dict:
        sid = payload["service_id"]
        if sid in self.seen:
            return {"ok": True, "claimed": False}
        self.seen.add(sid)
        return {"ok": True, "claimed": True}

    def __getattr__(self, name):
        async def call(payload):
            return {"ok": True, "called": name}

        return call


class _Namespace:
    def __init__(self, stub) -> None:
        self._stub = stub

    def idFromName(self, name):
        return name

    def get(self, object_id):
        return self._stub


def _load_identity_worker():
    fake = types.ModuleType("workers")
    fake.Response = _FakeResponse
    fake.WorkerEntrypoint = _FakeWorkerEntrypoint
    fake.DurableObject = _FakeDurableObject
    previous = sys.modules.get("workers")
    sys.modules["workers"] = fake
    try:
        spec = importlib.util.spec_from_file_location(
            "identity_worker_replay_test", ROOT / "identity_authority_worker.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            del sys.modules["workers"]
        else:
            sys.modules["workers"] = previous


def test_the_identity_worker_refuses_a_replayed_request() -> None:
    module = _load_identity_worker()
    stub = _ClaimStub()
    env = types.SimpleNamespace(
        CONTROL_PLANE_IDENTITY=_Namespace(stub),
        PADIEM_IDENTITY_RPC_INGRESS_SECRET=SECRET,
        PADIEM_RPC_SERVICE_ID_POLICY="required",
    )
    # The DO itself is not constructed here; the gateway's guard is what is
    # exercised, through the same stub the binding surface uses.
    default = module.Default(env=env)

    def identity_request(service_id: str) -> _Request:
        # One of the methods the identity ingress actually allowlists; the
        # replay decision is made before dispatch, so the payload is minimal.
        path = "/internal/rpc/resolve_auth_session"
        at = int(time.time())
        body = b'{"session_id":"s"}'
        return _Request(
            path=path,
            headers={
                "x-padiem-service-at": str(at),
                SERVICE_ID_HEADER: service_id,
                "x-padiem-service-proof": proof_for_v2(
                    SECRET,
                    method="POST",
                    path=path,
                    at=at,
                    service_id=service_id,
                    body=body,
                ),
            },
            body=body,
        )

    first = _run(default.fetch(identity_request(SERVICE_ID)))
    replay = _run(default.fetch(identity_request(SERVICE_ID)))
    fresh = _run(default.fetch(identity_request(OTHER_ID)))

    assert first.status == 201 or first.status == 200
    assert replay.status == 409
    assert json.loads(replay.body)["error"]["code"] == "rpc_replay_detected"
    assert fresh.status in (200, 201)


# The staging-instance config assertion lives outside this package, in
# .github/tests/test_identity_staging_config_261031.py: the foundation package
# gate refuses the config tool's name in any .py inside it.
