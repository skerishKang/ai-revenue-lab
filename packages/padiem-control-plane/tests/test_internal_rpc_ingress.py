"""#5573 A2 — the default-off HTTPS RPC ingress, with the binding path untouched.

The v1 proof below is written out literally (the same formula the Chat CPython
client signs, PR #6142); if either side drifts, these tests fail. The worker
fetch tests drive the real `Default.fetch` with a fake workers runtime, and the
same `Default` object's RPC methods are invoked directly afterwards to prove
the Service Binding surface did not change.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import json
import sys
import types
from pathlib import Path

ADAPTER_ROOT = Path(__file__).resolve().parents[1]
if str(ADAPTER_ROOT) not in sys.path:
    sys.path.insert(0, str(ADAPTER_ROOT))

from internal_rpc_ingress import (  # noqa: E402
    MAX_BODY_BYTES,
    handle_internal_rpc,
    proof_for,
    resolve_ingress_secret,
    rpc_method_from_path,
)

SECRET = "identity-ingress-secret-0123456789abcdef"


def _client_proof(secret: str, method: str, path: str, at: int, body: bytes) -> str:
    """The literal v1 contract as the CPython client writes it (#6142)."""

    signed = b"\n".join((b"v1", method.encode(), path.encode(), str(at).encode(), body))
    return "v1=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


class _URL:
    def __init__(self, url: str):
        self._url = url

    def __str__(self) -> str:
        return self._url


class _Headers(dict):
    def get(self, name, default=None):
        return super().get(name.lower(), default)


class _Request:
    def __init__(self, url: str, *, method: str = "POST", headers=None, body: bytes = b""):
        self.url = _URL(url)
        self.method = method
        self.headers = _Headers({key.lower(): value for key, value in (headers or {}).items()})
        self._body = body

    async def text(self) -> str:
        return self._body.decode("utf-8")


class _Dispatcher:
    def __init__(self, answer=None, *, raises: bool = False):
        self.answer = answer if answer is not None else {"ok": True, "value": 1}
        self.raises = raises
        self.calls: list[tuple[str, dict]] = []

    async def allowed_method(self, payload: dict) -> dict:
        self.calls.append(("allowed_method", payload))
        if self.raises:
            raise RuntimeError("upstream detail that must never surface")
        return self.answer

    async def other_method(self, payload: dict) -> dict:  # pragma: no cover - not reachable
        raise AssertionError("an unlisted method must never run")


ALLOWED = frozenset({"allowed_method"})


def _run(coro):
    return asyncio.run(coro)


def _signed_request(method="allowed_method", *, body=b'{"a":1}', at=1_000_000,
                    secret=SECRET, proof=None, http_method="POST", extra_headers=None):
    path = f"/internal/rpc/{method}"
    headers = {
        "x-padiem-service-at": str(at),
        "x-padiem-service-proof": proof or _client_proof(secret, http_method.upper(), path, at, body),
    }
    headers.update(extra_headers or {})
    return _Request("https://padiem-control-plane-identity" + path, method=http_method,
                    headers=headers, body=body)


def test_the_client_formula_and_the_target_verifier_agree():
    body = b'{"a":1}'
    path = "/internal/rpc/allowed_method"
    assert proof_for(SECRET, method="POST", path=path, at=7, body=body) == _client_proof(
        SECRET, "POST", path, 7, body
    )
    assert rpc_method_from_path(path) == "allowed_method"
    assert rpc_method_from_path("/internal/store") is None
    assert rpc_method_from_path("/internal/rpc/Upper") is None


def test_a_valid_proof_reaches_the_dispatcher():
    dispatcher = _Dispatcher()
    result = _run(handle_internal_rpc(
        _signed_request(), secret=SECRET, allowed_methods=ALLOWED,
        dispatcher=dispatcher, now=1_000_010,
    ))
    assert result is not None
    status, payload, headers = result
    assert status == 200 and payload == {"ok": True, "value": 1}
    assert headers.get("cache-control") == "no-store"
    assert dispatcher.calls == [("allowed_method", {"a": 1})]


def test_every_drift_is_refused_with_a_generic_envelope():
    tampered = _signed_request()
    tampered._body = b'{"a":2}'
    status, payload, _ = _run(handle_internal_rpc(
        tampered, secret=SECRET, allowed_methods=ALLOWED, dispatcher=_Dispatcher(), now=1_000_000
    ))
    assert status == 403 and payload["error"]["code"] == "rpc_proof_invalid"

    stale = _signed_request(at=1_000_000)
    status, payload, _ = _run(handle_internal_rpc(
        stale, secret=SECRET, allowed_methods=ALLOWED, dispatcher=_Dispatcher(), now=1_000_401
    ))
    assert status == 403 and payload["error"]["code"] == "rpc_proof_stale"

    wrong_put = _signed_request(
        method="allowed_method",
        proof=_client_proof(SECRET, "PUT", "/internal/rpc/allowed_method", 1_000_000, b'{"a":1}'),
    )
    status, payload, _ = _run(handle_internal_rpc(
        wrong_put, secret=SECRET, allowed_methods=ALLOWED, dispatcher=_Dispatcher(), now=1_000_000
    ))
    assert status == 403 and payload["error"]["code"] == "rpc_proof_invalid"

    missing = _Request("https://w/internal/rpc/allowed_method", headers={}, body=b"{}")
    status, payload, _ = _run(handle_internal_rpc(
        missing, secret=SECRET, allowed_methods=ALLOWED, dispatcher=_Dispatcher(), now=0
    ))
    assert status == 403 and payload["error"]["code"] == "rpc_proof_required"
    assert SECRET not in json.dumps(payload)


def test_unlisted_methods_look_exactly_like_typos_and_never_dispatch():
    dispatcher = _Dispatcher()
    unlisted = _signed_request(method="other_method")
    status, payload, _ = _run(handle_internal_rpc(
        unlisted, secret=SECRET, allowed_methods=ALLOWED, dispatcher=dispatcher, now=1_000_000
    ))
    assert status == 404 and payload["error"]["code"] == "rpc_unknown_method"
    typo = _signed_request(method="allowed_metho")
    status, payload, _ = _run(handle_internal_rpc(
        typo, secret=SECRET, allowed_methods=ALLOWED, dispatcher=dispatcher, now=1_000_000
    ))
    assert status == 404 and payload["error"]["code"] == "rpc_unknown_method"
    assert dispatcher.calls == []


def test_bounds_and_verbs():
    big = b'{"a":"' + b"x" * (MAX_BODY_BYTES) + b'"}'
    status, payload, _ = _run(handle_internal_rpc(
        _signed_request(body=big), secret=SECRET, allowed_methods=ALLOWED, dispatcher=_Dispatcher(), now=1_000_000
    ))
    assert status == 413

    declared = _signed_request()
    declared.headers["content-length"] = str(MAX_BODY_BYTES + 1)
    status, payload, _ = _run(handle_internal_rpc(
        declared, secret=SECRET, allowed_methods=ALLOWED, dispatcher=_Dispatcher(), now=1_000_000
    ))
    assert status == 413

    status, payload, _ = _run(handle_internal_rpc(
        _signed_request(http_method="GET"), secret=SECRET, allowed_methods=ALLOWED,
        dispatcher=_Dispatcher(), now=1_000_000,
    ))
    assert status == 405

    non_json = _signed_request(body=b"not-json")
    status, payload, _ = _run(handle_internal_rpc(
        non_json, secret=SECRET, allowed_methods=ALLOWED, dispatcher=_Dispatcher(), now=1_000_000
    ))
    assert status == 400

    broken = _run(handle_internal_rpc(
        _signed_request(), secret=SECRET, allowed_methods=ALLOWED,
        dispatcher=_Dispatcher(raises=True), now=1_000_000,
    ))
    assert broken[0] == 500 and "upstream detail" not in json.dumps(broken[1])


def test_stale_proof_is_rejected_against_the_real_clock_by_default():
    # The worker path calls without `now`; a proof minted an hour ago must be
    # refused by the real clock, not compared with its own timestamp.
    stale = _signed_request(at=int(__import__("time").time()) - 3600)
    status, payload, _ = _run(handle_internal_rpc(
        stale, secret=SECRET, allowed_methods=ALLOWED, dispatcher=_Dispatcher(),
    ))
    assert status == 403 and payload["error"]["code"] == "rpc_proof_stale"

    fresh = _signed_request(at=int(__import__("time").time()))
    status, _, _ = _run(handle_internal_rpc(
        fresh, secret=SECRET, allowed_methods=ALLOWED, dispatcher=_Dispatcher(),
    ))
    assert status == 200


def test_non_ingress_paths_are_left_to_the_worker_404():
    assert _run(handle_internal_rpc(
        _Request("https://w/health", headers={}, body=b""),
        secret=SECRET, allowed_methods=ALLOWED, dispatcher=_Dispatcher(), now=0,
    )) is None


def test_secret_resolution_handles_plain_binding_and_store_capability():
    class _Store:
        async def get(self):
            return SECRET

    assert _run(resolve_ingress_secret(SECRET)) == SECRET
    assert _run(resolve_ingress_secret(_Store())) == SECRET
    assert _run(resolve_ingress_secret("")) is None
    assert _run(resolve_ingress_secret(None)) is None


# --- the real Default.fetch, with a fake workers runtime ---------------------

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
    def __init__(self, answer):
        self._answer = answer
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, name):
        async def call(payload):
            self.calls.append((name, payload))
            return dict(self._answer)
        return call


class _Namespace:
    def __init__(self, stub):
        self._stub = stub

    def idFromName(self, name):
        return name

    def get(self, object_id):
        return self._stub


def _load_worker(path: Path, module_name: str):
    fake = types.ModuleType("workers")
    fake.Response = _FakeResponse
    fake.WorkerEntrypoint = _FakeWorkerEntrypoint
    fake.DurableObject = _FakeDurableObject
    previous = sys.modules.get("workers")
    sys.modules["workers"] = fake
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            del sys.modules["workers"]
        else:
            sys.modules["workers"] = previous


def _env(**values):
    return types.SimpleNamespace(**values)


def test_identity_fetch_is_absent_without_the_secret_and_gated_with_it():
    module = _load_worker(
        ADAPTER_ROOT / "identity_authority_worker.py", "identity_worker_ingress_test"
    )
    stub = _Stub({"ok": True, "link": {"product_user_id": "usr_1"}})
    env = _env(CONTROL_PLANE_IDENTITY=_Namespace(stub), CONTROL_PLANE_ALLOWED_PRODUCTS=None)

    # No secret: the door is not registered — every path, including the RPC
    # prefix, keeps the plain 404 the Worker has today.
    default = module.Default(env=env)
    response = _run(default.fetch(_signed_request(at=int(__import__("time").time()))))
    assert response.status == 404 and response.body == "Not Found"

    env.PADIEM_IDENTITY_RPC_INGRESS_SECRET = SECRET
    default = module.Default(env=env)
    response = _run(default.fetch(_signed_request(
        method="resolve_or_create_product_link", at=int(__import__("time").time()),
        body=b'{"product_id":"b62","product_user_id":"usr_1","auth_provider":"password","provider_subject":"a@example.com"}',
    )))
    assert response.status == 200
    assert json.loads(response.body)["ok"] is True
    assert stub.calls and stub.calls[0][0] == "resolve_or_create_product_link"

    # The unlisted and tenant methods stay unreachable through HTTPS.
    for name in ("create_tenant", "issue_google_connect_ticket", "install_connector_enrollment_schema"):
        denied = _run(default.fetch(_signed_request(method=name, at=int(__import__("time").time()))))
        assert denied.status == 404, name

    # The Service Binding RPC method itself is untouched.
    assert stub.calls  # already used through HTTPS
    binding_result = _run(default.resolve_connector_workspace({"session_id": "s"}))
    assert binding_result == {"ok": True, "link": {"product_user_id": "usr_1"}}


def test_google_state_fetch_exposes_only_workspace_connector_state():
    module = _load_worker(
        ADAPTER_ROOT / "google_oauth_worker.py", "google_worker_ingress_test"
    )
    stub = _Stub({"ok": True, "state": {"connectors": []}})
    env = _env(GOOGLE_OAUTH_STATE=_Namespace(stub))

    default = module.Default(env=env)
    response = _run(default.fetch(_signed_request(method="workspace_connector_state", at=int(__import__("time").time()))))
    assert response.status == 404

    env.PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET = SECRET
    default = module.Default(env=env)
    ok = _run(default.fetch(_signed_request(
        method="workspace_connector_state", body=b'{"workspace_ref":"w"}', at=int(__import__("time").time())
    )))
    assert ok.status == 200 and json.loads(ok.body)["ok"] is True
    assert stub.calls[0][0] == "workspace_connector_state"

    for name in ("begin_connect", "complete_callback", "issue_access_lease", "disconnect_drive"):
        assert _run(default.fetch(_signed_request(method=name, at=int(__import__("time").time())))).status == 404, name
    assert isinstance(_run(default.workspace_connector_state({"workspace_ref": "w"})), dict)
