"""#6919: a slow identity RPC names itself in the journal.

On 2026-11-05 the ``identity`` timing bucket of a PC read's ``/api/mcp``
request ran 0.35-6.9 s and nothing in the journal said which of the identity
calls behind it was slow. Each RPC slower than ``PADIEM_CHAT_IDENTITY_SLOW_MS``
(default 250) now leaves one bounded line: method name, milliseconds, outcome,
request id - never a payload or response value.
"""
from __future__ import annotations

import asyncio

import pytest

from app import control_plane_identity_worker as module
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import (
    IDENTITY_SLOW_RPC_MS_ENV,
    CloudflareControlPlaneIdentityAuthority,
    journal_identity_rpc,
)
from app.request_telemetry import _CURRENT_REQUEST_ID

PRIVATE = "private-session-value-not-for-logs"


class _Binding:
    def __init__(self, delay: float = 0.0, answer=None, raise_error=False):
        self.delay, self.answer, self.raise_error = delay, answer, raise_error
        self.calls = 0

    async def resolve_connector_owner_scope(self, payload):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_error:
            return {"ok": False, "error": {"code": "service_rpc_forbidden", "message": PRIVATE}}
        return self.answer if self.answer is not None else {
            "ok": True, "scope": {"subject_id": "sub_" + "a" * 32, "product_user_id": "u" * 32}}


@pytest.fixture(autouse=True)
def _traced_request(monkeypatch):
    monkeypatch.delenv(IDENTITY_SLOW_RPC_MS_ENV, raising=False)
    token = _CURRENT_REQUEST_ID.set("req_identity" + "a" * 16)
    try:
        yield
    finally:
        _CURRENT_REQUEST_ID.reset(token)


def test_a_fast_call_leaves_no_line(capsys):
    journal_identity_rpc("resolve_connector_owner_scope", 120.0, "ok")
    assert capsys.readouterr().out == ""


def test_a_slow_call_names_method_ms_outcome_and_request(capsys):
    journal_identity_rpc("resolve_connector_owner_scope", 1843.4, "ok")
    assert capsys.readouterr().out.strip() == (
        "identity_rpc_slow method=resolve_connector_owner_scope ms=1843 outcome=ok "
        "request_id=req_identityaaaaaaaaaaaaaaaa"
    )


def test_labels_are_bounded_and_the_request_id_is_checked(capsys):
    _CURRENT_REQUEST_ID.set("not a safe id " + PRIVATE)
    journal_identity_rpc("weird method; " + PRIVATE, 900.0, "code with spaces " + PRIVATE)
    out = capsys.readouterr().out
    assert out.strip() == "identity_rpc_slow method=other ms=900 outcome=other request_id=none"
    assert PRIVATE not in out


@pytest.mark.parametrize("raw, expected", [
    ("", 250), ("abc", 250), ("0", 0), ("500", 500), ("-5", 0), ("999999", 60000),
])
def test_the_threshold_is_read_and_clamped(monkeypatch, raw, expected):
    monkeypatch.setenv(IDENTITY_SLOW_RPC_MS_ENV, raw)
    assert module._identity_slow_rpc_ms() == expected


@pytest.mark.asyncio
async def test_the_adapter_journals_a_slow_rpc_and_not_a_fast_one(capsys, monkeypatch):
    monkeypatch.setenv(IDENTITY_SLOW_RPC_MS_ENV, "50")
    slow = CloudflareControlPlaneIdentityAuthority(_Binding(delay=0.12))
    await slow._rpc_envelope("resolve_connector_owner_scope", {"session_id": PRIVATE})
    out = capsys.readouterr().out
    assert out.startswith("identity_rpc_slow method=resolve_connector_owner_scope ms=")
    assert "outcome=ok" in out and PRIVATE not in out

    fast = CloudflareControlPlaneIdentityAuthority(_Binding())
    await fast._rpc_envelope("resolve_connector_owner_scope", {"session_id": PRIVATE})
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_a_slow_refusal_carries_its_closed_code(capsys, monkeypatch):
    monkeypatch.setenv(IDENTITY_SLOW_RPC_MS_ENV, "0")
    authority = CloudflareControlPlaneIdentityAuthority(_Binding(raise_error=True))
    with pytest.raises(IdentityBridgeError) as info:
        await authority._rpc_envelope("resolve_connector_owner_scope", {"session_id": PRIVATE})
    assert info.value.code == "service_rpc_forbidden"
    out = capsys.readouterr().out
    assert "outcome=service_rpc_forbidden" in out
    assert PRIVATE not in out


@pytest.mark.asyncio
async def test_the_envelope_contract_is_unchanged(capsys):
    binding = _Binding()
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    result = await authority._rpc_envelope("resolve_connector_owner_scope", {"session_id": "s"})
    assert result["ok"] is True and binding.calls == 1
    with pytest.raises(IdentityBridgeError):
        await authority._rpc_envelope("no_such_method", {})
