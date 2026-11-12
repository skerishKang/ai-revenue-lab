"""#7542 stage 0: Chat counts the identity RPCs it sends, once a minute.

The journal already told a slow identity RPC (``identity_rpc_slow``) and a
cache hit from a miss (``identity_cache_minute``), but not how many times each
RPC was actually sent - the number a retirement step has to reach zero on.
The existing minute counter now prints a second line, ``identity_rpc_minute``:
RPC name, result kind and count. These tests pin that the line carries those
three things and nothing else, that every path to the binding is counted, that
the wake-up ping is counted apart, and that answers and errors are unchanged.
"""
from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest

from app import control_plane_identity_worker as worker_module
from app import identity_cache_metrics as metrics
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import (
    CloudflareControlPlaneIdentityAuthority,
    _product_user_cache,
)
from app.local_service_bridge import (
    IDENTITY_KEEPWARM_METHOD,
    IDENTITY_KEEPWARM_PAYLOAD,
    HttpRpcBinding,
)

# Shaped like a real identifier on purpose: a label filter that only checked
# the character set would let it through.
PRIVATE = "sess_private_value_not_for_logs"
PRIVATE_SUBJECT = "sub_0123456789abcdef0123456789abcdef"
SECRET = "com2-host-identity-secret-0123456789abcdef"
ORIGIN = "https://identity.example.test"

_ENTRY = re.compile(r"(?P<source>[a-z]+)\.(?P<method>[a-z_]+):(?P<kinds>[a-z_]+=\d+(?:,[a-z_]+=\d+)*)")


@pytest.fixture(autouse=True)
def _clean_counters():
    for store in (metrics._counts, metrics._rpc_counts, _product_user_cache):
        store.clear()
    yield
    for store in (metrics._counts, metrics._rpc_counts, _product_user_cache):
        store.clear()


def _rpc_line(capsys) -> str:
    """Flush the minute and return its one RPC line, checked against the grammar."""
    metrics.flush()
    lines = [line for line in capsys.readouterr().out.splitlines()
             if line.startswith("identity_rpc_minute ")]
    assert len(lines) == 1
    body = lines[0][len("identity_rpc_minute "):]
    if body != "empty":
        for token in body.split(" "):
            entry = _ENTRY.fullmatch(token)
            assert entry is not None, "entry is not source.method:kind=count"
            assert entry["source"] in metrics.RPC_SOURCES | {"other"}
            assert entry["method"] in metrics.RPC_METHODS | {"other"}
            for pair in entry["kinds"].split(","):
                assert pair.split("=")[0] in metrics.RPC_OUTCOME_KINDS | {"other"}
    return lines[0]


class _Binding:
    """Answers each named RPC with the envelope, or raises the error, it was given."""

    def __init__(self, **answers):
        self._answers = answers
        self.calls: list[str] = []

    def __getattr__(self, name):
        if name.startswith("_") or name not in self._answers:
            raise AttributeError(name)

        async def call(payload):
            self.calls.append(name)
            answer = self._answers[name]
            if isinstance(answer, BaseException):
                raise answer
            if answer is _NEVER:
                await asyncio.Event().wait()
            return answer

        return call


_NEVER = object()
_SCOPE_OK = {"ok": True, "scope": {"account_ref": "a", "workspace_ref": "w"}}


def _refusal(code: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": PRIVATE}}


def test_the_line_names_method_kind_and_count_and_the_cache_line_is_unchanged(capsys):
    metrics.record("wrapper", "resolve_auth_session", True)
    for kind in ("ok", "ok", "unauthorized"):
        metrics.record_rpc("call", "resolve_auth_session", kind)
    metrics.record_rpc("call", "create_tenant", "unavailable")
    metrics.record_rpc("keepwarm", "resolve_product_user_for_subject", "answered")
    metrics.flush()
    assert capsys.readouterr().out.splitlines() == [
        "identity_cache_minute wrapper.resolve_auth_session:hit=1,miss=0",
        "identity_rpc_minute call.create_tenant:unavailable=1 "
        "call.resolve_auth_session:ok=2,unauthorized=1 "
        "keepwarm.resolve_product_user_for_subject:answered=1",
    ]


def test_an_idle_minute_still_prints_one_line_and_counts_do_not_carry_over(capsys):
    metrics.record_rpc("call", "resolve_auth_session", "ok")
    assert _rpc_line(capsys) == "identity_rpc_minute call.resolve_auth_session:ok=1"
    assert _rpc_line(capsys) == "identity_rpc_minute empty"


@pytest.mark.parametrize("source, method, kind, expected", [
    (PRIVATE, "resolve_auth_session", "ok", "other.resolve_auth_session:ok=1"),
    ("call", PRIVATE, "ok", "call.other:ok=1"),
    ("call", PRIVATE_SUBJECT, "ok", "call.other:ok=1"),
    ("call", "resolve_auth_session", PRIVATE, "call.resolve_auth_session:other=1"),
    (None, 7, ["ok"], "other.other:other=1"),
])
def test_a_label_outside_the_fixed_sets_is_counted_as_other(capsys, source, method, kind, expected):
    metrics.record_rpc(source, method, kind)
    line = _rpc_line(capsys)
    assert line == "identity_rpc_minute " + expected
    assert PRIVATE not in line and PRIVATE_SUBJECT not in line


@pytest.mark.parametrize("answer, kind, status, code", [
    (_SCOPE_OK, "ok", None, None),
    (_refusal("inactive_auth_session"), "unauthorized", 401, "inactive_auth_session"),
    (_refusal("connector_context_session_mismatch"), "forbidden", 403,
     "connector_context_session_mismatch"),
    # The authority's own code is not a label: it is counted by kind only.
    (_refusal(PRIVATE), "rejected", 503, PRIVATE),
    (RuntimeError(PRIVATE), "unavailable", 503, "control_plane_identity_unavailable"),
    ({"ok": "yes", "detail": PRIVATE}, "invalid", 503, "control_plane_rpc_invalid"),
])
async def test_the_adapter_counts_each_call_by_kind_and_changes_nothing(
    capsys, answer, kind, status, code,
):
    binding = _Binding(resolve_connector_owner_scope=answer)
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    payload = {"session_id": PRIVATE}
    if status is None:
        assert await authority._rpc_envelope("resolve_connector_owner_scope", payload) == answer
    else:
        with pytest.raises(IdentityBridgeError) as info:
            await authority._rpc_envelope("resolve_connector_owner_scope", payload)
        assert (info.value.status_code, info.value.code) == (status, code)
    assert binding.calls == ["resolve_connector_owner_scope"]
    line = _rpc_line(capsys)
    assert line == f"identity_rpc_minute call.resolve_connector_owner_scope:{kind}=1"
    assert PRIVATE not in line


async def test_a_binding_without_the_method_is_counted_as_unavailable(capsys):
    authority = CloudflareControlPlaneIdentityAuthority(_Binding())
    with pytest.raises(IdentityBridgeError) as info:
        await authority._rpc_envelope("resolve_auth_session", {"session_id": PRIVATE})
    assert info.value.code == "control_plane_identity_unavailable"
    assert _rpc_line(capsys) == "identity_rpc_minute call.resolve_auth_session:unavailable=1"


async def test_a_cancelled_call_is_counted_as_interrupted(capsys):
    binding = _Binding(resolve_auth_session=_NEVER)
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    task = asyncio.ensure_future(
        authority._rpc_envelope("resolve_auth_session", {"session_id": PRIVATE}))
    while not binding.calls:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _rpc_line(capsys) == "identity_rpc_minute call.resolve_auth_session:interrupted=1"


@pytest.mark.parametrize("answer, kind", [
    ({"ok": True, "tenant_ids": ["ten_1", "ten_2"]}, "ok"),
    (RuntimeError(PRIVATE), "unavailable"),
    ({"ok": True, "tenant_ids": PRIVATE}, "invalid"),
])
async def test_the_membership_read_outside_the_envelope_is_counted_too(capsys, answer, kind):
    authority = CloudflareControlPlaneIdentityAuthority(_Binding(resolve_active_memberships=answer))
    if kind == "ok":
        assert await authority.resolve_active_memberships(
            canonical_subject_id=PRIVATE_SUBJECT) == ("ten_1", "ten_2")
    else:
        with pytest.raises(IdentityBridgeError) as info:
            await authority.resolve_active_memberships(canonical_subject_id=PRIVATE_SUBJECT)
        assert info.value.status_code == 503
    line = _rpc_line(capsys)
    assert line == f"identity_rpc_minute call.resolve_active_memberships:{kind}=1"
    assert PRIVATE not in line and PRIVATE_SUBJECT not in line


async def test_a_cache_hit_is_not_a_call(capsys):
    binding = _Binding(resolve_product_user_for_subject={"ok": True, "product_user_id": "usr_1"})
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    for _ in range(3):
        assert await authority.resolve_product_user_for_subject(
            product_id="b62", canonical_subject_id=PRIVATE_SUBJECT) == "usr_1"
    assert binding.calls == ["resolve_product_user_for_subject"]
    assert _rpc_line(capsys) == "identity_rpc_minute call.resolve_product_user_for_subject:ok=1"


class _Client:
    """The pooled client of the HTTPS binding, with no socket behind it."""

    def __init__(self, warm_status: int | None):
        self.warm_status = warm_status
        self.warm_body = None

    async def post(self, url: str, content=None, headers=None) -> httpx.Response:
        if content == self.warm_body:
            if self.warm_status is None:
                raise httpx.ConnectError("refused", request=httpx.Request("POST", url))
            return httpx.Response(self.warm_status, json=_refusal("canonical_product_identity_link_not_found"))
        return httpx.Response(200, json={"ok": True, "product_user_id": "usr_1"})


@pytest.mark.parametrize("warm_status, kind", [(200, "answered"), (503, "bad_status"), (None, "unavailable")])
async def test_the_wake_up_ping_is_counted_apart_from_a_real_call(capsys, warm_status, kind):
    client = _Client(warm_status)
    client.warm_body = json.dumps(
        IDENTITY_KEEPWARM_PAYLOAD, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    binding = HttpRpcBinding(ORIGIN, SECRET, client=client)
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    try:
        await binding._warm_once()
        assert await authority.resolve_product_user_for_subject(
            product_id="b62", canonical_subject_id=PRIVATE_SUBJECT) == "usr_1"
    finally:
        await binding.aclose()
    assert IDENTITY_KEEPWARM_METHOD == "resolve_product_user_for_subject"
    assert _rpc_line(capsys) == (
        "identity_rpc_minute call.resolve_product_user_for_subject:ok=1 "
        f"keepwarm.resolve_product_user_for_subject:{kind}=1"
    )


def test_no_label_is_a_word_the_journal_error_patrol_counts():
    """The patrol counts journal lines by keyword; a count line must not look like one."""
    labels = metrics.RPC_SOURCES | metrics.RPC_METHODS | metrics.RPC_OUTCOME_KINDS | {"other", "empty"}
    for word in ("refused", "timeout", "traceback"):
        assert not [label for label in labels if word in label.lower()]
        assert word not in "identity_rpc_minute"


async def test_the_minute_tick_prints_the_line_and_rearms(capsys):
    metrics.stop()
    metrics.arm()
    try:
        first = metrics._timer
        assert first is not None
        first.cancel()  # fire the tick by hand instead of waiting a minute
        metrics._tick()
        assert metrics._timer is not None and metrics._timer is not first
        assert capsys.readouterr().out.splitlines()[-1] == "identity_rpc_minute empty"
    finally:
        metrics.stop()


# --- every path to the binding is a counted one ---------------------------------

def _adapter_class() -> ast.ClassDef:
    tree = ast.parse(Path(worker_module.__file__).read_text(encoding="utf-8"))
    return next(node for node in tree.body
                if isinstance(node, ast.ClassDef)
                and node.name == "CloudflareControlPlaneIdentityAuthority")


def _self_calls(scope: ast.AST, names: set[str]) -> list[ast.Call]:
    return [node for node in ast.walk(scope)
            if isinstance(node, ast.Call)
            and ((isinstance(node.func, ast.Attribute) and node.func.attr in names
                  and isinstance(node.func.value, ast.Name) and node.func.value.id == "self")
                 or (isinstance(node.func, ast.Name) and node.func.id in names))]


def test_every_rpc_name_the_adapter_sends_is_a_countable_label():
    """A new RPC must be added to ``RPC_METHODS`` or it is counted as ``other``."""
    adapter = _adapter_class()
    sent: set[str] = set()
    forwarded: list[str] = []
    for function in (node for node in adapter.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        for call in _self_calls(function, {"_rpc", "_rpc_envelope", "_CountedIdentityRpc"}):
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                sent.add(first.value)
            else:
                forwarded.append(function.name)
    # Only the two internal hops pass the name on instead of naming it.
    assert sorted(forwarded) == ["_rpc", "_rpc_envelope"]
    assert sent == set(metrics.RPC_METHODS)
    assert IDENTITY_KEEPWARM_METHOD in metrics.RPC_METHODS


def test_the_binding_is_reached_only_through_counted_functions():
    adapter = _adapter_class()
    touching = {
        function.name
        for function in adapter.body
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(isinstance(node, ast.Attribute) and node.attr == "_binding"
                for node in ast.walk(function))
    }
    assert touching == {
        "__init__",
        "_rpc_envelope_unmeasured",
        "_resolve_active_memberships_uncounted",
        # Reads whether the method exists; sends nothing.
        "supports_ensure_personal_tenant_membership",
    }
    # Each uncounted body has exactly one caller, and that caller counts.
    for body, counted_caller in (
        ("_rpc_envelope_unmeasured", "_rpc_envelope"),
        ("_resolve_active_memberships_uncounted", "resolve_active_memberships"),
    ):
        callers = [
            function.name
            for function in adapter.body
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _self_calls(function, {body})
        ]
        assert callers == [counted_caller]
        caller = next(function for function in adapter.body
                      if getattr(function, "name", None) == counted_caller)
        counted = [
            node for node in ast.walk(caller)
            if isinstance(node, ast.With)
            and any(isinstance(item.context_expr, ast.Call)
                    and getattr(item.context_expr.func, "id", None) == "_CountedIdentityRpc"
                    for item in node.items)
            and _self_calls(node, {body})
        ]
        assert len(counted) == 1
