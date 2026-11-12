"""#7542 P0-C — every identity RPC entry point writes one countable line.

Retiring the old identity authority needs per-method call counts. The gateway
forwards each RPC to the Durable Object and prints the method name and whether
the object answered. The payload and the answer carry subjects, product users
and sessions, so neither may appear in the line.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from test_lovetree_identity_registration import _worker_mod  # noqa: E402

SECRET_SUBJECT = "provider-subject-must-not-be-logged"
SECRET_USER = "usr_user_must_not_be_logged"


class _Stub:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        async def call(payload):
            self.calls.append(name)
            if self.fail:
                raise RuntimeError("object unavailable " + SECRET_SUBJECT)
            return {"ok": True, "echo": payload}

        return call


def _gateway(stub: _Stub):
    gateway = _worker_mod.Default.__new__(_worker_mod.Default)
    gateway._stub = lambda: stub  # type: ignore[method-assign]
    return gateway


def _rpc_methods() -> list[str]:
    return sorted(
        name
        for name, member in vars(_worker_mod.Default).items()
        if inspect.iscoroutinefunction(member) and not name.startswith("_") and name != "fetch"
    )


def test_every_rpc_entry_point_goes_through_the_counting_forwarder() -> None:
    methods = _rpc_methods()
    assert len(methods) == 26
    assert set(_worker_mod.IDENTITY_RPC_INGRESS_METHODS) <= set(methods)


def test_each_call_writes_the_method_name_and_nothing_from_the_payload(capsys) -> None:
    stub = _Stub()
    gateway = _gateway(stub)
    payload = {"provider_subject": SECRET_SUBJECT, "product_user_id": SECRET_USER}
    for method in _rpc_methods():
        answer = asyncio.run(getattr(gateway, method)(payload))
        assert answer == {"ok": True, "echo": payload}
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert stub.calls == _rpc_methods()
    assert lines == [{"identity_rpc": m, "outcome": "returned"} for m in _rpc_methods()]
    assert SECRET_SUBJECT not in out and SECRET_USER not in out


def test_a_failing_object_is_counted_and_the_error_still_propagates(capsys) -> None:
    gateway = _gateway(_Stub(fail=True))
    with pytest.raises(RuntimeError):
        asyncio.run(gateway.resolve_auth_session({"session_id": "sess_x"}))
    out = capsys.readouterr().out
    assert json.loads(out.strip()) == {"identity_rpc": "resolve_auth_session", "outcome": "raised"}
    assert SECRET_SUBJECT not in out


def test_an_unexpected_method_name_is_not_echoed(capsys) -> None:
    _worker_mod._journal_rpc("Bad Name <x>", "returned")
    assert json.loads(capsys.readouterr().out) == {"identity_rpc": "other", "outcome": "returned"}


def test_no_gateway_method_reaches_the_object_around_the_forwarder() -> None:
    source = (pathlib.Path(__file__).resolve().parents[1] / "identity_authority_worker.py").read_text(encoding="utf-8")
    gateway = source.split("class Default", 1)[1].split("async def fetch", 1)[0]
    assert "getattr(self._stub(), method)" in gateway
    assert "self._stub()." not in gateway
