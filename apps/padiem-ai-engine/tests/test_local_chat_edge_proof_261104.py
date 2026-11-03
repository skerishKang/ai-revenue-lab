"""Host Chat binding signs with the COM2 edge scheme the real verifier checks.

#6666 follow-up: ``LocalChatServiceBinding`` must attach the four
``x-padiem-edge-*`` headers Chat's ``EdgeProofMiddleware`` requires, sign them
with the shared ``PADIEM_COM2_EDGE_SECRET_FILE`` material, and refuse to
forward an unsigned request. Every assertion here runs the produced headers
through the real ``EdgeProofVerifier`` from the Chat app, so the contract under
test is the deployed one, not a local re-implementation.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app import local_runtime as rt

_EDGE_MODULE = Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane" / "com2_edge_proof.py"
_spec = importlib.util.spec_from_file_location("_com2_edge_proof_actual", _EDGE_MODULE)
assert _spec and _spec.loader
edge = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = edge
_spec.loader.exec_module(edge)

TEST_SECRET = "synthetic-edge-" + "z" * 40
STAMP = 1794045000
ORIGIN = "http://127.0.0.1:8798"
ROUTE = "/internal/claw/engine-desktop"


class Response:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = b"{}"


class CapturingClient:
    def __init__(self, record):
        self.record = record

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aclose(self):
        pass

    async def request(self, method, url, headers, content):
        self.record.update(method=method, url=url, headers=headers, body=content)
        return Response()


def _secret_file(tmp_path, secret=TEST_SECRET):
    f = tmp_path / "com2-edge-secret"
    f.write_text(secret + "\n", encoding="utf-8")
    f.chmod(0o600)
    return f


def binding(monkeypatch, tmp_path, extra_values=None, *, with_secret=True):
    values = {
        rt.CHAT_SERVICE_ENV: ORIGIN,
        rt.CHAT_EDGE_SECRET_FILE_ENV: str(_secret_file(tmp_path)) if with_secret else "",
        "CLAW_ENGINE_DESKTOP_SECRET": TEST_SECRET,
    }
    values.update(extra_values or {})
    record = {}
    monkeypatch.setattr(rt.time, "time", lambda: STAMP)
    monkeypatch.setattr(rt.httpx, "AsyncClient", lambda **kw: CapturingClient(record))
    return rt.LocalChatServiceBinding(ORIGIN, values=values), record


async def test_binding_attaches_edge_headers_the_real_verifier_accepts(monkeypatch, tmp_path):
    b, record = binding(monkeypatch, tmp_path)
    await b.fetch(rt.LocalRequest(
        f"https://chat.internal{ROUTE}", method="POST",
        headers={"content-type": "application/json"}, body=b'{"x":1}'))
    headers = record["headers"]
    for name in ("x-padiem-edge-at", "x-padiem-edge-id", "x-padiem-edge-tls", "x-padiem-edge-proof"):
        assert name in headers, name
    verifier = edge.EdgeProofVerifier(TEST_SECRET, str(tmp_path / "replay.db"))
    assert verifier.verify(method="POST", path=ROUTE, headers=headers, now=STAMP)


async def test_replayed_id_is_rejected_and_a_retry_signs_a_fresh_id(monkeypatch, tmp_path):
    b, record = binding(monkeypatch, tmp_path)
    await b.fetch(rt.LocalRequest(
        f"https://chat.internal{ROUTE}", method="POST", body=b"{}"))
    verifier = edge.EdgeProofVerifier(TEST_SECRET, str(tmp_path / "replay.db"))
    assert verifier.verify(method="POST", path=ROUTE, headers=record["headers"], now=STAMP)
    # The same id a second time is the replay the durable store exists to stop.
    assert not verifier.verify(method="POST", path=ROUTE, headers=record["headers"], now=STAMP)
    # A retry of the same engine request calls fetch again: a fresh id verifies.
    first_id = record["headers"]["x-padiem-edge-id"]
    await b.fetch(rt.LocalRequest(
        f"https://chat.internal{ROUTE}", method="POST", body=b"{}"))
    assert record["headers"]["x-padiem-edge-id"] != first_id
    assert verifier.verify(method="POST", path=ROUTE, headers=record["headers"], now=STAMP)


async def test_wrong_secret_is_rejected(monkeypatch, tmp_path):
    b, record = binding(monkeypatch, tmp_path)
    await b.fetch(rt.LocalRequest(
        f"https://chat.internal{ROUTE}", method="POST", body=b"{}"))
    verifier = edge.EdgeProofVerifier("another-edge-secret-" + "w" * 32, str(tmp_path / "replay.db"))
    assert not verifier.verify(method="POST", path=ROUTE, headers=record["headers"], now=STAMP)


async def test_missing_secret_file_refuses_the_forward_loudly(monkeypatch, tmp_path):
    b, record = binding(monkeypatch, tmp_path, with_secret=False)
    with pytest.raises(rt.LocalRuntimeError, match="p01_local_chat_edge_unconfigured"):
        await b.fetch(rt.LocalRequest(
            f"https://chat.internal{ROUTE}", method="POST", body=b"{}"))
    assert record == {}


def test_local_bindings_publishes_the_binding_only_with_edge_material(monkeypatch, tmp_path, caplog):
    missing = {rt.CHAT_SERVICE_ENV: ORIGIN}
    with caplog.at_level("WARNING"):
        bindings = rt._local_bindings(missing)
    assert rt.CHAT_SERVICE_BINDING_NAME not in bindings
    assert any(r.message == "p01_local_chat_edge_unconfigured" for r in caplog.records)

    complete = {
        rt.CHAT_SERVICE_ENV: ORIGIN,
        rt.CHAT_EDGE_SECRET_FILE_ENV: str(_secret_file(tmp_path)),
        "CLAW_ENGINE_DESKTOP_SECRET": TEST_SECRET,
    }
    bindings = rt._local_bindings(complete)
    assert isinstance(bindings[rt.CHAT_SERVICE_BINDING_NAME], rt.LocalChatServiceBinding)


def test_env_view_satisfies_the_desktop_registration_condition(monkeypatch, tmp_path):
    # worker_identity.py registers the desktop tools only when the
    # PADIEM_CHAT_SERVICE binding exists and the desktop secret is a string of
    # 32+ chars — both must come from env alone on this host.
    complete = {
        rt.CHAT_SERVICE_ENV: ORIGIN,
        rt.CHAT_EDGE_SECRET_FILE_ENV: str(_secret_file(tmp_path)),
        "CLAW_ENGINE_DESKTOP_SECRET": TEST_SECRET,
    }
    env = rt._env_view(complete)
    chat_service = getattr(env, rt.CHAT_SERVICE_BINDING_NAME)
    desktop_secret = getattr(env, "CLAW_ENGINE_DESKTOP_SECRET")
    assert isinstance(chat_service, rt.LocalChatServiceBinding)
    assert isinstance(desktop_secret, str) and len(desktop_secret) >= 32
    # worker_identity.py:1310 — the exact gate shape.
    assert chat_service is not None and isinstance(desktop_secret, str) and len(desktop_secret) >= 32

    without = {k: v for k, v in complete.items() if k != rt.CHAT_EDGE_SECRET_FILE_ENV}
    env = rt._env_view(without)
    chat_service = getattr(env, rt.CHAT_SERVICE_BINDING_NAME)
    desktop_secret = getattr(env, "CLAW_ENGINE_DESKTOP_SECRET")
    assert chat_service is None
    assert not (chat_service is not None and isinstance(desktop_secret, str) and len(desktop_secret) >= 32)


def test_secret_file_permission_is_enforced(tmp_path):
    if sys.platform == "win32":
        pytest.skip("POSIX permission bits")
    loose = tmp_path / "loose"
    loose.write_text(TEST_SECRET + "\n", encoding="utf-8")
    loose.chmod(0o644)
    assert rt._chat_edge_secret_from_file(str(loose)) == ""
    tight = tmp_path / "tight"
    tight.write_text(TEST_SECRET + "\n", encoding="utf-8")
    tight.chmod(0o600)
    assert rt._chat_edge_secret_from_file(str(tight)) == TEST_SECRET
