"""Offline Chat cookie -> host P01 -> signed authorities -> B14 regression.

Both apps use the top-level ``app`` package. Each scenario runs in a child
interpreter, with an isolated Engine import scope around its ASGI dispatch.
Only HTTP authority/storage answers are fakes; the Chat route, host composition,
canonical resolver, Engine admission/Core and all wire transports run unchanged.
No listener is opened and every external request uses MockTransport.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("scenario", ["connected", "reverted_chat_wiring", "bad_identity_proof", "no_cookie"])
def test_chat_p01_identity_roundtrip(scenario):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), scenario],
        cwd=ROOT, env={**os.environ, "PYTHONPATH": ""},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    # Product fail-closed guards must not hide a broken authority fixture.
    assert report["fixture_errors"] == []
    if scenario == "connected":
        assert report["status"] == 200
        assert report["answer"] == "합성 B14 답변"
        assert report["b14_calls"] == 1
        assert report["admission_subjects"] == ["subject:padiem:user:p01-roundtrip"]
        assert report["history_owner"] == "usr_" + "a" * 32
        assert report["identity_calls"] >= 3
    elif scenario == "reverted_chat_wiring":
        assert report["status"] == 503
        assert report["code"] == "entitlement_unavailable"
        assert report["producer_codes"] == ["engine_entitlement_identity_unavailable"]
        assert report["admission_subjects"] == ["usr_" + "a" * 32]
        assert report["b14_calls"] == 0
    elif scenario == "bad_identity_proof":
        assert report["status"] == 503
        assert report["b14_calls"] == 0
        assert report["admission_subjects"] == []
    else:
        assert report["status"] == 401
        assert report["code"] == "unauthorized"
        assert report["b14_calls"] == 0
        assert report["identity_calls"] == 0


async def _exercise(scenario):
    from contextlib import contextmanager
    from datetime import datetime, timedelta, timezone
    import hashlib
    import hmac
    import importlib
    import socket
    import tempfile

    for relative in (
        "packages/padiem-ai-core", "packages/padiem-control-plane",
        "apps/padiem-ai-engine/clients/python", "apps/korean-ai-code-agent/src", "tools",
    ):
        sys.path.insert(0, str(ROOT / relative))

    import httpx
    from padiem_control_plane.contracts import ControlPlaneContractError
    from padiem_control_plane.engine_entitlement_producer import (
        canonical_user_subject_from_wire,
        produce_authenticated_user_engine_entitlement,
        resolve_authenticated_user_session,
    )
    from internal_rpc_ingress import handle_internal_rpc

    def no_socket(*args, **kwargs):
        records["fixture_errors"].append("unexpected_network_connection")
        raise AssertionError("offline roundtrip must not open a network connection")

    socket.socket.connect = no_socket
    owner = "usr_" + "a" * 32
    subject = "subject:padiem:user:p01-roundtrip"
    caller_secret = "test-only-engine-caller-0123456789abcdef"
    identity_secret = "test-only-identity-rpc-0123456789abcdef"
    admission_secret = "test-only-admission-rpc-0123456789abcdef"
    b14_secret = "test-only-b14-proof-0123456789abcdef"
    now = datetime.now(timezone.utc)
    session = {
        "session_id": "session:p01-roundtrip", "product_id": "b62",
        "subject": {"subject_type": "user", "subject_id": subject},
        "issued_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "state": "active", "revision": 1,
    }
    records = {"identity_calls": 0, "b14_calls": 0, "admission_subjects": [], "producer_codes": [], "fixture_errors": []}

    def record_fixture_errors(function):
        async def checked(*args, **kwargs):
            try:
                return await function(*args, **kwargs)
            except Exception as exc:
                # No payload/credential/exception text is reported. This out of
                # band record survives a real ingress/client's error mapping.
                records["fixture_errors"].append(f"{function.__name__}:{type(exc).__name__}")
                raise
        return checked

    class Identity:
        @record_fixture_errors
        async def resolve_current_auth_session(self, payload):
            records["identity_calls"] += 1
            assert payload == {"product_id": "b62", "product_user_id": owner}
            return {"ok": True, "session": session}

        @record_fixture_errors
        async def resolve_product_user_for_subject(self, payload):
            records["identity_calls"] += 1
            assert payload["product_id"] == "b62"
            if payload["canonical_subject_id"] != subject:
                return {"ok": False, "error": {"code": "canonical_product_identity_link_not_found"}}
            return {"ok": True, "product_user_id": owner}

    identity = Identity()

    class Admission:
        @record_fixture_errors
        async def fetch_entitlement_snapshot(self, payload):
            records["admission_subjects"].append(payload["subject"]["subject_id"])
            try:
                current = await resolve_authenticated_user_session(
                    identity, product_id=payload["product_id"],
                    subject=canonical_user_subject_from_wire(payload["subject"]), now=now,
                )
                snapshot = produce_authenticated_user_engine_entitlement(current, now=now)
            except ControlPlaneContractError as exc:
                records["producer_codes"].append(exc.code)
                return {"ok": False, "error": {"code": exc.code}}
            return {"ok": True, "snapshot": snapshot.to_policy_dict()}

        @record_fixture_errors
        async def reserve_usage(self, payload):
            assert payload["reservation"]["subject"]["subject_id"] == subject
            return {"ok": True, "reservation": {
                "reservation_ref": "res-p01-roundtrip", "admitted": True,
                "reserved_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
            }}

        @record_fixture_errors
        async def record_usage(self, payload):
            return {"ok": True, "receipt": {"accepted": True, "event_id": payload["usage_event"]["event_id"]}}

    class Replay:
        def __init__(self):
            self.seen = set()

        @record_fixture_errors
        async def claim(self, service_id, *, expires_at):
            assert expires_at > 0
            if service_id in self.seen:
                return False
            self.seen.add(service_id)
            return True

    class RpcRequest:
        def __init__(self, request):
            self.url, self.method, self.headers = request.url, request.method, request.headers
            self._content = request.content

        async def text(self):
            return self._content.decode()

    authorities = {
        "identity.example.invalid": (identity, identity_secret, Replay(), frozenset({"resolve_current_auth_session", "resolve_product_user_for_subject"})),
        "admission.example.invalid": (Admission(), admission_secret, Replay(), frozenset({"fetch_entitlement_snapshot", "reserve_usage", "record_usage"})),
    }

    @record_fixture_errors
    async def external_http(request):
        if request.url.host in authorities:
            dispatcher, secret, replay, methods = authorities[request.url.host]
            # Real ingress verifies v2 HMAC, fresh service id, clock and replay.
            status, body, headers = await handle_internal_rpc(
                RpcRequest(request), secret=secret, allowed_methods=methods,
                dispatcher=dispatcher, service_id_policy="required", replay_guard=replay,
            )
            return httpx.Response(status, json=body, headers=headers)
        assert request.url.host == "127.0.0.1" and request.url.port == 8789
        assert request.url.path == "/api/pilot/v1/chat/completions"
        timestamp = request.headers["x-padiem-b14-time"]
        expected = hmac.new(b14_secret.encode(), timestamp.encode() + b"." + request.content, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(request.headers["x-padiem-b14-proof"], expected)
        records["b14_calls"] += 1
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "합성 B14 답변"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        })

    original_client = httpx.AsyncClient

    def offline_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(external_http))
        return original_client(*args, **kwargs)

    httpx.AsyncClient = offline_client
    engine_modules = {}

    def scoped(name):
        return name == "app" or name.startswith("app.") or name in {"worker", "worker_identity"}

    @contextmanager
    def engine_scope():
        previous = {name: module for name, module in list(sys.modules.items()) if scoped(name)}
        previous_path = list(sys.path)
        for name in previous:
            del sys.modules[name]
        sys.modules.update(engine_modules)
        sys.path.insert(0, str(ROOT / "apps/padiem-ai-engine"))
        try:
            yield
        finally:
            engine_modules.update({name: module for name, module in list(sys.modules.items()) if scoped(name)})
            for name in list(sys.modules):
                if scoped(name):
                    del sys.modules[name]
            sys.modules.update(previous)
            sys.path[:] = previous_path

    with tempfile.TemporaryDirectory() as temporary:
        with engine_scope():
            runtime = importlib.import_module("app.local_runtime")
            engine = runtime.create_local_app({
                "PADIEM_ENGINE_CPYTHON_HOST": "1",
                "PADIEM_ENGINE_CALLER_ID": "b62-roundtrip",
                "PADIEM_ENGINE_CALLER_SECRET": caller_secret,
                "PADIEM_ENGINE_ALLOWED_APPS": "padiem-chat",
                "PADIEM_ENGINE_LOCAL_B14_ORIGIN": "http://127.0.0.1:8789",
                "PADIEM_B14_SERVICE_PROOF_SECRET": b14_secret,
                "PADIEM_ENGINE_LOCAL_DB": str(Path(temporary) / "engine.sqlite3"),
                "PADIEM_ENGINE_LOCAL_ADMISSION_ORIGIN": "https://admission.example.invalid",
                "PADIEM_ENGINE_LOCAL_ADMISSION_SECRET": admission_secret,
            })

        async def engine_asgi(scope, receive, send):
            with engine_scope():
                await engine(scope, receive, send)

        sys.path.insert(0, str(ROOT / "apps/padiem-chat"))
        from starlette.applications import Starlette
        from app.auth import SESSION_COOKIE, create_session_token
        from app.config import Settings
        from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
        from app.local_service_bridge import HttpRpcBinding
        from app import local_cpython

        class History:
            async def append_exchange(self, user_id, *args, **kwargs):
                records["history_owner"] = user_id
                return "chat_" + "b" * 32

        class Db:
            def prepare(self, sql):
                records["fixture_errors"].append("unexpected_continuation_sql")
                raise AssertionError("a completed non-paused turn needs no continuation SQL")

        chat = Starlette()
        settings = Settings(runtime_mode="b14", auth_mode="hybrid", session_secret="test-only-chat-session-0123456789abcdef")
        chat.state.settings = settings
        chat.state.history_store = History()
        chat.state.usage_gate_enforced = False
        chat.state.identity_shadow_store = None
        chat.state.control_plane_identity_authority = CloudflareControlPlaneIdentityAuthority(
            HttpRpcBinding("https://identity.example.invalid", identity_secret if scenario != "bad_identity_proof" else "test-only-wrong-secret-0123456789abcdef")
        )
        if scenario == "reverted_chat_wiring":
            original_compose = local_cpython.compose_orchestration_bridge

            def reverted(*args, **kwargs):
                kwargs.pop("canonical_subject_resolver", None)
                return original_compose(*args, **kwargs)

            local_cpython.compose_orchestration_bridge = reverted

        async with original_client(transport=httpx.ASGITransport(app=engine_asgi)) as engine_client:
            bridge = local_cpython.compose_host_orchestration(
                chat, env={
                    "PADIEM_CHAT_ORCHESTRATION_ENABLED": "true",
                    "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN": "http://127.0.0.1:8811",
                    "PADIEM_CHAT_LOCAL_P01_CALLER_ID": "b62-roundtrip",
                    "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL": caller_secret,
                }, settings=settings, db_binding=Db(), client=engine_client,
            )
            assert bridge is not None
            headers = {"origin": "https://chat.example.invalid"}
            if scenario != "no_cookie":
                headers["cookie"] = f"{SESSION_COOKIE}={create_session_token(settings, owner)}"
            async with original_client(transport=httpx.ASGITransport(app=chat), base_url="https://chat.example.invalid") as client:
                response = await client.post("/api/orchestration", headers=headers, json={"messages": [{"role": "user", "content": "안녕"}]})
            body = response.json()
            return {**records, "status": response.status_code, "answer": body.get("answer"), "code": body.get("error", {}).get("code")}


if __name__ == "__main__":
    import asyncio

    print(json.dumps(asyncio.run(_exercise(sys.argv[1])), ensure_ascii=False))
