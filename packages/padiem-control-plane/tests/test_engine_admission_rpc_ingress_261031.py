"""The admission authority's default-off HTTPS ingress for the COM2 Engine host.

The Engine on Cloudflare calls this Worker through the private
``CONTROL_PLANE_ENGINE_ADMISSION`` Service Binding. The COM2 Engine host has no
binding, so it signs the same #5573 A2 proof the identity ingress already
verifies. Three properties are pinned here:

* only the three Engine calls are reachable over HTTPS; the CP-owned
  ``install_entitlement_snapshot`` seam stays binding-only, because installing
  entitlement is not something the Engine gateway has ever been able to do;
* without the secret binding the door is not registered at all — every path,
  including the RPC prefix, keeps today's plain 404;
* the binding-shaped RPC surface itself is unchanged.

The proof below is written out literally (the same formula the host client
signs); if either side drifts these tests fail.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import json
import sys
import time
import types
from pathlib import Path

ADAPTER_ROOT = Path(__file__).resolve().parents[1]
if str(ADAPTER_ROOT) not in sys.path:
    sys.path.insert(0, str(ADAPTER_ROOT))

SECRET = "engine-admission-ingress-secret-0123456789abcdef"
ENGINE_CALLS = ("fetch_entitlement_snapshot", "reserve_usage", "record_usage")
FETCH_BODY = (
    b'{"product_id":"b62","subject":{"subject_type":"user",'
    b'"subject_id":"subject:padiem:user:com2"}}'
)


def _client_proof(secret: str, method: str, path: str, at: int, body: bytes) -> str:
    signed = b"\n".join(
        (b"v1", method.encode(), path.encode(), str(at).encode(), body)
    )
    return "v1=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


class _URL:
    def __init__(self, url: str) -> None:
        self._url = url

    def __str__(self) -> str:
        return self._url


class _Headers(dict):
    def get(self, name, default=None):
        return super().get(str(name).lower(), default)


class _Request:
    def __init__(self, url: str, *, method: str = "POST", headers=None, body: bytes = b""):
        self.url = _URL(url)
        self.method = method
        self.headers = _Headers(
            {key.lower(): value for key, value in (headers or {}).items()}
        )
        self._body = body

    async def text(self) -> str:
        return self._body.decode("utf-8")


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


class _Stub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, name):
        async def call(payload):
            self.calls.append((name, payload))
            return {"ok": True, "called": name}

        return call


class _Namespace:
    def __init__(self, stub: _Stub) -> None:
        self._stub = stub

    def idFromName(self, name):
        return name

    def get(self, object_id):
        return self._stub


def _load_worker():
    fake = types.ModuleType("workers")
    fake.Response = _FakeResponse
    fake.WorkerEntrypoint = _FakeWorkerEntrypoint
    fake.DurableObject = _FakeDurableObject
    previous = sys.modules.get("workers")
    sys.modules["workers"] = fake
    try:
        spec = importlib.util.spec_from_file_location(
            "engine_admission_worker_ingress_test",
            ADAPTER_ROOT / "engine_admission_authority_worker.py",
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


def _run(coro):
    return asyncio.run(coro)


def _signed(
    method: str,
    *,
    body: bytes = FETCH_BODY,
    at: int | None = None,
    secret: str = SECRET,
    proof: str | None = None,
):
    at = int(time.time()) if at is None else at
    path = f"/internal/rpc/{method}"
    return _Request(
        "https://padiem-control-plane-engine-admission" + path,
        headers={
            "x-padiem-service-at": str(at),
            "x-padiem-service-proof": proof
            or _client_proof(secret, "POST", path, at, body),
        },
        body=body,
    )


def _module_with_stub():
    module = _load_worker()
    stub = _Stub()
    env = types.SimpleNamespace(
        CONTROL_PLANE_ENGINE_ADMISSION=_Namespace(stub),
    )
    return module, stub, env


def test_the_door_is_not_registered_without_the_secret() -> None:
    module, stub, env = _module_with_stub()
    default = module.Default(env=env)

    response = _run(default.fetch(_signed("fetch_entitlement_snapshot")))

    assert response.status == 404
    assert response.body == "Not Found"
    assert stub.calls == []


def test_the_three_engine_calls_round_trip_over_https() -> None:
    module, stub, env = _module_with_stub()
    env.PADIEM_ENGINE_ADMISSION_RPC_INGRESS_SECRET = SECRET
    default = module.Default(env=env)

    for name in ENGINE_CALLS:
        response = _run(default.fetch(_signed(name)))
        assert response.status == 200, name
        assert json.loads(response.body) == {"ok": True, "called": name}

    assert [call[0] for call in stub.calls] == list(ENGINE_CALLS)


def test_install_entitlement_stays_binding_only() -> None:
    module, stub, env = _module_with_stub()
    env.PADIEM_ENGINE_ADMISSION_RPC_INGRESS_SECRET = SECRET
    default = module.Default(env=env)

    assert not hasattr(module.Default, "install_entitlement_snapshot")

    response = _run(default.fetch(_signed("install_entitlement_snapshot")))

    assert response.status == 404
    assert json.loads(response.body)["error"]["code"] == "rpc_unknown_method"
    assert stub.calls == []


def test_other_private_methods_are_not_reachable_over_https() -> None:
    module, stub, env = _module_with_stub()
    env.PADIEM_ENGINE_ADMISSION_RPC_INGRESS_SECRET = SECRET
    default = module.Default(env=env)

    for name in ("resolve_product_user_for_subject", "fetch_entitlement_snapsho"):
        response = _run(default.fetch(_signed(name)))
        assert response.status == 404, name
        assert json.loads(response.body)["error"]["code"] == "rpc_unknown_method"

    assert stub.calls == []


def test_every_proof_failure_is_refused_and_never_dispatches() -> None:
    module, stub, env = _module_with_stub()
    env.PADIEM_ENGINE_ADMISSION_RPC_INGRESS_SECRET = SECRET
    default = module.Default(env=env)

    missing = _Request(
        "https://padiem-control-plane-engine-admission/internal/rpc/fetch_entitlement_snapshot",
        headers={},
        body=FETCH_BODY,
    )
    response = _run(default.fetch(missing))
    assert response.status == 403
    assert json.loads(response.body)["error"]["code"] == "rpc_proof_required"

    wrong = _run(
        default.fetch(
            _signed(
                "fetch_entitlement_snapshot",
                proof=_client_proof(
                    "another-secret-0123456789abcdef",
                    "POST",
                    "/internal/rpc/fetch_entitlement_snapshot",
                    int(time.time()),
                    FETCH_BODY,
                ),
            )
        )
    )
    assert wrong.status == 403
    assert json.loads(wrong.body)["error"]["code"] == "rpc_proof_invalid"

    tampered = _signed("fetch_entitlement_snapshot")
    tampered._body = FETCH_BODY.replace(b"b62", b"b54")
    response = _run(default.fetch(tampered))
    assert response.status == 403
    assert json.loads(response.body)["error"]["code"] == "rpc_proof_invalid"

    stale = _run(
        default.fetch(_signed("fetch_entitlement_snapshot", at=int(time.time()) - 3600))
    )
    assert stale.status == 403
    assert json.loads(stale.body)["error"]["code"] == "rpc_proof_stale"

    assert stub.calls == []
    assert SECRET not in response.body


def test_a_replay_inside_the_window_is_the_identity_ingress_behaviour() -> None:
    """#6410's ingress has no nonce cache: the guard is the clock window.

    A byte-identical replay inside 300 s therefore answers again, exactly as the
    identity ingress does. Duplicate usage is covered by the reservation
    idempotency key the DO already stores, not by a second verifier here.
    """

    module, stub, env = _module_with_stub()
    env.PADIEM_ENGINE_ADMISSION_RPC_INGRESS_SECRET = SECRET
    default = module.Default(env=env)
    request = _signed("reserve_usage", body=b'{"reservation":{"idempotency_key":"res-1"}}')

    first = _run(default.fetch(request))
    second = _run(default.fetch(request))

    assert (first.status, second.status) == (200, 200)
    assert [call[0] for call in stub.calls] == ["reserve_usage", "reserve_usage"]


def test_the_service_binding_surface_is_unchanged() -> None:
    module, stub, env = _module_with_stub()
    env.PADIEM_ENGINE_ADMISSION_RPC_INGRESS_SECRET = SECRET
    default = module.Default(env=env)

    answer = _run(default.fetch_entitlement_snapshot({"product_id": "b62", "subject": {}}))

    assert answer == {"ok": True, "called": "fetch_entitlement_snapshot"}
    assert stub.calls == [("fetch_entitlement_snapshot", {"product_id": "b62", "subject": {}})]


def test_the_staging_instance_is_its_own_worker_with_its_own_namespace() -> None:
    config = json.loads(
        (ADAPTER_ROOT / "wrangler.engine-admission-authority.jsonc").read_text(
            encoding="utf-8"
        )
    )
    staging = config["env"]["staging"]

    assert config["name"] == "padiem-control-plane-engine-admission"
    assert config["workers_dev"] is False
    assert staging["name"] == "padiem-control-plane-engine-admission-staging"
    assert staging["name"] != config["name"]
    # workers.dev only: no zone route may exist on the staging instance.
    assert staging["workers_dev"] is True
    assert "routes" not in staging and "routes" not in config
    # Its own Durable Object namespace, same reviewed class and binding name.
    assert staging["durable_objects"] == config["durable_objects"]
    # Staging never reads the production identity authority.
    staging_identity = {
        entry["binding"]: entry["service"] for entry in staging["services"]
    }
    assert staging_identity["CONTROL_PLANE_IDENTITY"] != "padiem-control-plane-identity"
    # Same reviewed product boundary in both instances.
    assert staging["vars"] == config["vars"]
