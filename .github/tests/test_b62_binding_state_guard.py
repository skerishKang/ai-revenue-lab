from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "b62_binding_state_guard.py"
spec = importlib.util.spec_from_file_location("b62_binding_state_guard", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def settings(*bindings):
    return {"success": True, "result": {"bindings": list(bindings)}}


def base_bindings():
    return [
        {"type": "assets", "name": "ASSETS"},
        {"type": "service", "name": "IDENTITY_AUTHORITY_SERVICE", "service": "padiem-control-plane-identity"},
        {"type": "service", "name": "B14_SERVICE", "service": "ai-revenue-korean-ai-platform", "environment": "production"},
        {"type": "d1", "name": "PADIEM_CHAT_DB", "id": "db-id"},
        {"type": "r2_bucket", "name": "PADIEM_WORKSPACE_FILES", "bucket_name": "private-claw", "jurisdiction": "us"},
        {"type": "plain_text", "name": "PADIEM_CHAT_RUNTIME_MODE", "text": "b14"},
        {"type": "secret_text", "name": "PADIEM_CHAT_QUOTA_SALT"},
    ]


def test_exact_binding_authority_preservation_passes():
    before = settings(*base_bindings())
    after = settings(*reversed(base_bindings()))
    mod.assert_preserved(before, after)


def test_r2_bucket_name_drift_is_rejected():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[4] = {**changed[4], "bucket_name": "wrong-bucket"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_r2_jurisdiction_drift_is_rejected():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[4] = {**changed[4], "jurisdiction": "eu"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_service_environment_drift_is_rejected():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[2] = {**changed[2], "environment": "staging"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_d1_id_drift_is_rejected():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[3] = {**changed[3], "id": "other-db"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_plain_text_drift_is_rejected():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[5] = {**changed[5], "text": "mock"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_secret_name_presence_only_is_compared():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[6] = {"type": "secret_text", "name": "OTHER_SECRET"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_unknown_type_and_duplicate_names_fail_closed():
    with pytest.raises(mod.BindingStateError):
        mod.canonical_state(settings({"type": "kv_namespace", "name": "X"}))
    with pytest.raises(mod.BindingStateError):
        mod.canonical_state(settings(
            {"type": "secret_text", "name": "X"},
            {"type": "plain_text", "name": "X", "text": "x"},
        ))
