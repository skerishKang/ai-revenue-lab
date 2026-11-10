"""#7286: expected keepwarm denials log as info, not as the failure line.

``engine_admission_authority_worker._safe_error`` printed one closed failure
line (``pc_admission_rpc_error``) for every contract error, including the
design-expected ``engine_entitlement_identity_unavailable`` denial the
padiem-ai-engine keepwarm ping receives. These tests pin the split and keep
the non-synthetic path byte-for-byte behaviour.

"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

from padiem_control_plane.contracts import ControlPlaneContractError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_ADAPTER = ROOT / "engine_admission_authority_worker.py"

_SYNTHETIC_SUBJECT = {
    "subject_type": "user",
    "subject_id": "padiem-engine-keepwarm-synthetic",
}
_OTHER_SUBJECT = {"subject_type": "user", "subject_id": "subject-other-7286"}


class _FakeResponse:
    def __init__(self, body="", status=200):
        self.body = body
        self.status = status


class _FakeWorkerEntrypoint:
    pass


class _FakeDurableObject:
    def __init__(self, ctx=None, env=None):
        self.ctx = ctx
        self.env = env


def _load_worker():
    fake = types.ModuleType("workers")
    fake.Response = _FakeResponse
    fake.WorkerEntrypoint = _FakeWorkerEntrypoint
    fake.DurableObject = _FakeDurableObject
    previous = sys.modules.get("workers")
    sys.modules["workers"] = fake
    try:
        spec = importlib.util.spec_from_file_location(
            "engine_admission_authority_worker_7286",
            _ADAPTER,
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


def _denied(code: str = "engine_entitlement_identity_unavailable"):
    return ControlPlaneContractError(code, "denied for this test")


def test_synthetic_subject_gets_info_event(capsys):
    module = _load_worker()
    module._safe_error(_denied(), "fetch_entitlement_snapshot", _SYNTHETIC_SUBJECT)
    captured = capsys.readouterr().out
    assert captured == (
        "keepwarm_probe fetch_entitlement_snapshot engine_entitlement_identity_unavailable\n"
    )


def test_other_subject_gets_failure_line_identical_to_before(capsys):
    module = _load_worker()
    module._safe_error(_denied(), "fetch_entitlement_snapshot", _OTHER_SUBJECT)
    captured = capsys.readouterr().out
    assert captured == (
        "pc_admission_rpc_error fetch_entitlement_snapshot engine_entitlement_identity_unavailable\n"
    )


def test_unparseable_subject_keeps_failure_line(capsys):
    module = _load_worker()
    module._safe_error(
        _denied(), "fetch_entitlement_snapshot", {"subject_id": "no-type"}
    )
    captured = capsys.readouterr().out
    assert "pc_admission_rpc_error fetch_entitlement_snapshot" in captured
    assert "keepwarm_probe" not in captured


def test_no_subject_keeps_failure_line(capsys):
    module = _load_worker()
    module._safe_error(_denied(), "reserve_usage")
    captured = capsys.readouterr().out
    assert (
        captured
        == "pc_admission_rpc_error reserve_usage engine_entitlement_identity_unavailable\n"
    )


def _durable_without_init(module):
    obj = module.CanonicalEngineAdmissionDurableObject.__new__(
        module.CanonicalEngineAdmissionDurableObject
    )
    obj._store = types.SimpleNamespace()
    obj._identity = types.SimpleNamespace()
    return obj


def test_canonical_subject_ref_is_recognized():
    from padiem_control_plane.engine_admission_authority import (
        canonical_subject_from_wire,
    )

    module = _load_worker()
    ref = canonical_subject_from_wire(_SYNTHETIC_SUBJECT)
    assert module._is_synthetic_keepwarm_subject(ref) is True
    assert (
        module._is_synthetic_keepwarm_subject(
            canonical_subject_from_wire(_OTHER_SUBJECT)
        )
        is False
    )


def test_fetch_endpoint_forwards_synthetic_subject(monkeypatch, capsys):
    module = _load_worker()

    async def deny(*, product_id, subject, now):
        raise _denied()

    obj = _durable_without_init(module)
    monkeypatch.setattr(obj, "_ensure_current_entitlement", deny)
    result = asyncio.run(
        obj.fetch_entitlement_snapshot(
            {"product_id": "b62", "subject": _SYNTHETIC_SUBJECT}
        )
    )
    captured = capsys.readouterr().out
    assert result == {
        "ok": False,
        "error": {
            "code": "engine_entitlement_identity_unavailable",
            "message": "Control Plane Engine admission request was rejected",
        },
    }
    assert "keepwarm_probe fetch_entitlement_snapshot" in captured
    assert "pc_admission_rpc_error" not in captured


def test_fetch_endpoint_response_is_unchanged_for_other_subject(monkeypatch, capsys):
    module = _load_worker()

    async def deny(*, product_id, subject, now):
        raise _denied()

    obj = _durable_without_init(module)
    monkeypatch.setattr(obj, "_ensure_current_entitlement", deny)
    result = asyncio.run(
        obj.fetch_entitlement_snapshot({"product_id": "b62", "subject": _OTHER_SUBJECT})
    )
    captured = capsys.readouterr().out
    assert result == {
        "ok": False,
        "error": {
            "code": "engine_entitlement_identity_unavailable",
            "message": "Control Plane Engine admission request was rejected",
        },
    }
    assert "pc_admission_rpc_error fetch_entitlement_snapshot" in captured
    assert "keepwarm_probe" not in captured
