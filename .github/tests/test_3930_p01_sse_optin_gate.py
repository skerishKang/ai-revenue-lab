"""Network-free #3930 P01 SSE opt-in source/served/secret-preservation matrix."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/b62_p01_sse_optin_gate.py"
WORKFLOW = ROOT / ".github/workflows/b62-claw-live-config-activation-gate.yml"
spec = importlib.util.spec_from_file_location("sse_optin", HELPER)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

SHA = "a" * 40
PRE = "049085b1-17ce-4775-ba5c-34c3748071cc"
POST = "149085b1-17ce-4775-ba5c-34c3748071cc"
PRIVATE = "do-not-print-this-user-secret"


def b(name, kind, **kwargs):
    return {"name": name, "type": kind, **kwargs}


def fixtures(flag=None, *, version_id=PRE, source=SHA):
    bs = [
        b("ASSETS", "assets"),
        b("PADIEM_CHAT_DB", "d1", id="11111111-1111-1111-1111-111111111111"),
        b("PADIEM_CHAT_RUNTIME_MODE", "plain_text", text="b14"),
        b("PADIEM_CHAT_LIVE_ENABLED", "plain_text", text="true"),
        b("P01_ENGINE_SERVICE", "service", service="padiem-ai-engine"),
        b("P01_ENGINE_CREDENTIAL", "secret_text"),
        b("P01_ENGINE_CALLER_ID", "plain_text", text="caller"),
        b("IDENTITY_AUTHORITY_SERVICE", "service", service="identity"),
        b("PADIEM_CHAT_SESSION_SECRET", "secret_text"),
        b("PADIEM_CHAT_QUOTA_SALT", "secret_text"),
        b("PADIEM_CLAW_P01_LIVE_CANARY_SUBJECT_ID", "secret_text"),
        b("OTHER_PROTECTED_SECRET", "secret_text", value=PRIVATE),
    ]
    if flag is not None:
        bs.append(b(gate.FLAG, "plain_text", text=flag))
    settings = {"success": True, "result": {"bindings": bs}}
    deployments = {"success": True, "result": {"deployments": [{
        "id": "current", "versions": [{"version_id": version_id, "percentage": 100}],
        "annotations": {"workers/message": f"B62 production code {source}"}
    }]}}
    version = {"id": version_id, "resources": {
        "script": {"etag": "script-unchanged"}, "script_runtime": {"compatibility_date": "2026-01-01"},
        "assets": {"etag": "assets-unchanged"}, "bindings": copy.deepcopy(bs),
    }}
    return settings, deployments, version


def post_from(before):
    s, d, v = copy.deepcopy(before)
    s["result"]["bindings"].append(b(gate.FLAG, "plain_text", text="true"))
    v["resources"]["bindings"].append(b(gate.FLAG, "plain_text", text="true"))
    v["id"] = POST
    d["result"]["deployments"][0]["versions"][0]["version_id"] = POST
    return s, d, v


def must_fail(fn, expected):
    try:
        fn()
    except gate.OptInRefused as exc:
        assert str(exc) == expected
    else:
        raise AssertionError(f"expected refusal: {expected}")


def test_absent_flag_preserves_every_binding_and_sets_only_true():
    baseline = fixtures()
    plan = gate.plan(*baseline, SHA)
    assert plan["no_op"] is False
    patch = plan["payload"]
    assert len(patch["bindings"]) == len(baseline[0]["result"]["bindings"]) + 1
    assert sum(x["type"] == "inherit" for x in patch["bindings"]) == len(baseline[0]["result"]["bindings"])
    assert [x for x in patch["bindings"] if x["type"] != "inherit"] == [
        b(gate.FLAG, "plain_text", text="true")
    ]
    assert PRIVATE not in repr(plan)
    assert patch["annotations"]["workers/message"] == f"B62 production code {SHA}"
    gate.verify(*baseline, *post_from(baseline), SHA)


def test_false_flag_replaced_once_without_other_mutations():
    before = fixtures("false")
    planned = gate.plan(*before, SHA)["payload"]
    assert len(planned["bindings"]) == len(before[0]["result"]["bindings"])
    post = list(post_from(fixtures()))
    gate.verify(*before, *post, SHA)


def test_true_flag_is_noop_and_second_patch_is_not_authorized():
    before = fixtures("true")
    p = gate.plan(*before, SHA)
    assert p["no_op"]
    assert all(x["type"] == "inherit" for x in p["payload"]["bindings"])
    gate.verify(*before, *before, SHA, no_op=True)
    must_fail(lambda: gate.verify(*before, *before, SHA), "NEW_SERVED_VERSION_NOT_OBSERVED")


def test_refuses_wrong_type_duplicate_absent_canary_and_stale_lineage():
    s, d, v = fixtures()
    for name in ("PADIEM_CLAW_P01_LIVE_CANARY_SUBJECT_ID", "P01_ENGINE_CREDENTIAL"):
        x = copy.deepcopy((s,d,v))
        x[0]["result"]["bindings"] = [q for q in x[0]["result"]["bindings"] if q["name"] != name]
        x[2]["resources"]["bindings"] = [q for q in x[2]["resources"]["bindings"] if q["name"] != name]
        must_fail(lambda x=x: gate.plan(*x, SHA), "REQUIRED_BINDING_MISSING_OR_RETYPED")
    x = copy.deepcopy((s,d,v))
    x[0]["result"]["bindings"].append(b(gate.FLAG,"secret_text"))
    x[2]["resources"]["bindings"].append(b(gate.FLAG,"secret_text"))
    must_fail(lambda: gate.plan(*x,SHA), "FLAG_WRONG_TYPE_OR_VALUE")
    x = copy.deepcopy((s,d,v))
    x[0]["result"]["bindings"].append(copy.deepcopy(x[0]["result"]["bindings"][0]))
    try:
        gate.plan(*x,SHA)
    except gate.config.ProductionConfigError:
        pass
    else:
        raise AssertionError("duplicate accepted")
    must_fail(lambda: gate.plan(*fixtures(source="b"*40),SHA), "SOURCE_SHA_MISMATCH")
    must_fail(lambda: gate.plan(*fixtures(), "bad"), "INVALID_TARGET_SHA")


def test_refuses_races_code_assets_type_drift_and_invalid_version():
    before = fixtures()
    changed = copy.deepcopy(before)
    changed[0]["result"]["bindings"].append(b("NEW", "plain_text", text="drift"))
    changed[2]["resources"]["bindings"].append(b("NEW", "plain_text", text="drift"))
    must_fail(lambda: gate.compare_before(*before, *changed, SHA), "PREMUTATION_STATE_CHANGED")
    after = list(post_from(before))
    after[2]["resources"]["script"]["etag"] = "different"
    must_fail(lambda: gate.verify(*before, *after, SHA), "WORKER_CODE_OR_RUNTIME_DRIFT")
    after = list(post_from(before))
    after[0]["result"]["bindings"].append(b("UNAPPROVED", "plain_text", text="x"))
    after[2]["resources"]["bindings"].append(b("UNAPPROVED", "plain_text", text="x"))
    must_fail(lambda: gate.verify(*before,*after,SHA), "POST_SETTINGS_DRIFT")
    after = list(post_from(before))
    after[1]["result"]["deployments"][0]["versions"][0]["percentage"] = 50
    must_fail(lambda: gate.verify(*before,*after,SHA), "ACTIVE_VERSION_NOT_UNIQUE")


def test_rollback_restores_or_removes_only_the_authorized_flag():
    rollback = gate.load("b62_rollback_authority", ROOT / ".github/scripts/b62_claw_live_config_activation.py")
    before = fixtures()[0]
    enabled = post_from(fixtures())[0]
    old_behavior = rollback.build_rollback_plan(
        before, enabled, credential_created_by_activation=False, target_sha=SHA)
    assert old_behavior["no_op"], "legacy rollback must not silently broaden its target scope"
    plan = rollback.build_rollback_plan(
        before, enabled, credential_created_by_activation=False,
        target_sha=SHA, sse_optin_rollback=True)
    assert not plan["no_op"]
    assert f"CONFIG_REMOVE_{gate.FLAG}" in plan["changes"]
    assert gate.FLAG not in [q["name"] for q in plan["payload"]["bindings"]]
    assert all(q["type"] == "inherit" for q in plan["payload"]["bindings"])
    before_false = fixtures("false")[0]
    plan_false = rollback.build_rollback_plan(
        before_false, enabled, credential_created_by_activation=False,
        target_sha=SHA, sse_optin_rollback=True)
    assert [q for q in plan_false["payload"]["bindings"] if q["type"] != "inherit"] == [
        b(gate.FLAG, "plain_text", text="false")
    ]
    assert PRIVATE not in repr(plan)
    assert PRIVATE not in repr(plan_false)


def test_workflow_authority():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "activate_p01_sse" in workflow
    assert "CONFIRM_ACTIVATE_B62_P01_SSE_OPTIN" in workflow
    assert "environment: production" in workflow
    assert "b62_p01_sse_optin_gate.py plan" in workflow
    assert "b62_p01_sse_optin_gate.py compare-before" in workflow
    assert "b62_p01_sse_optin_gate.py verify" in workflow
    assert "b62-claw-config-premutation-settings" in workflow
    assert "rollback_config" in workflow
    assert "P01_SSE_OPTIN_NO_OP" in workflow
    assert "P01_SSE_POST_SERVED_INTEGRITY" in workflow

if __name__ == "__main__":
    for name, func in sorted(globals().copy().items()):
        if name.startswith("test_") and callable(func):
            func()
            print(name + "=PASS")
