"""#3930 source-only Production preflight: no provider call or mutation."""
import importlib.util
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[3] / ".github/scripts/b62_p01_live_sse_readiness.py"
spec=importlib.util.spec_from_file_location("claw_p01_live_canary_readiness", SCRIPT)
assert spec is not None and spec.loader is not None
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

MAIN="a"*40
DEPLOYED="b"*40
VERSION="049085b1-17ce-4775-ba5c-34c3748071cc"


def status(sha=MAIN, *, percent=100, version=VERSION, message=None):
    return {
        "id":"current_active",
        "annotations":{"workers/message":message or f"B62 production code {sha}"},
        "versions":[{"version_id":version,"percentage":percent}],
    }


def version(*, flag="true", source_id=VERSION):
    names={
        **gate.EXPECTED_TYPES,
        "PADIEM_CHAT_RUNTIME_MODE":"plain_text",
        "PADIEM_CHAT_LIVE_ENABLED":"plain_text",
    }
    bindings=[{"name":name,"type":kind} for name,kind in names.items()]
    bindings.append(
        {"name":"UNRELATED_SECRET","type":"secret_text","text":"do-not-print-me"}
    )
    # Set the allowlisted flag texts, never inspect unknown binding values.
    for b in bindings:
        if b["name"] == "PADIEM_CHAT_RUNTIME_MODE":
            b["text"]="b14"
        if b["name"] == "PADIEM_CHAT_LIVE_ENABLED":
            b["text"]="true"
    if flag is not None:
        bindings.append({"name":"PADIEM_CLAW_P01_LIVE_SSE_ENABLED","type":"plain_text","text":flag})
    return {"id":source_id,"resources":{"bindings":bindings}}


def test_exact_served_version_and_opt_in_only_marks_preflight_not_actual_canary():
    out=gate.assess(status(),version(),target_sha=MAIN)
    assert out["disposition"]=="CANARY_PREFLIGHT_READY"
    assert out["blockers"]==[]
    assert out["provider_requests"]==0
    assert out["settings_mutations"]==0
    assert out["user_canary_executed"] is False


def test_actual_observed_configuration_blocks_on_source_and_missing_flag():
    out=gate.assess(status(DEPLOYED),version(flag=None),target_sha=MAIN)
    assert out["disposition"]=="CANARY_BLOCKED"
    assert set(out["blockers"])=={
        "SERVED_SOURCE_OUTDATED","MISSING_PADIEM_CLAW_P01_LIVE_SSE_ENABLED"
    }
    assert "do-not-print-me" not in repr(out)


def test_absent_or_false_explicit_flag_never_promotes_chat_live_flag():
    for flag,expected in ((None,"MISSING_PADIEM_CLAW_P01_LIVE_SSE_ENABLED"),
                          ("false","NOT_READY_PADIEM_CLAW_P01_LIVE_SSE_ENABLED")):
        out=gate.assess(status(),version(flag=flag),target_sha=MAIN)
        assert expected in out["blockers"]
        assert out["disposition"]=="CANARY_BLOCKED"


def test_core_authority_dependency_cannot_be_faked_by_live_flag():
    for name in gate.EXPECTED_TYPES:
        cfg=version()
        cfg["resources"]["bindings"]=[
            b for b in cfg["resources"]["bindings"] if b["name"]!=name
        ]
        out=gate.assess(status(),cfg,target_sha=MAIN)
        assert f"MISSING_{name}" in out["blockers"]


def test_wrong_type_duplicate_or_wrong_runtime_refused():
    cfg=version()
    cfg["resources"]["bindings"][0]["type"]="plain_text"
    assert "WRONG_TYPE_P01_ENGINE_SERVICE" in gate.assess(status(),cfg,target_sha=MAIN)["blockers"]
    cfg=version()
    cfg["resources"]["bindings"].append(dict(cfg["resources"]["bindings"][0]))
    assert "DUPLICATE_BINDING_NAME" in gate.assess(status(),cfg,target_sha=MAIN)["blockers"]
    cfg=version()
    for b in cfg["resources"]["bindings"]:
        if b["name"]=="PADIEM_CHAT_RUNTIME_MODE":b["text"]="mock"
    assert "NOT_READY_PADIEM_CHAT_RUNTIME_MODE" in gate.assess(status(),cfg,target_sha=MAIN)["blockers"]


def test_active_deployment_and_lineage_cannot_be_guessed():
    assert "ACTIVE_VERSION_MISMATCH" in gate.assess(
        status(),version(source_id="other"),target_sha=MAIN
    )["blockers"]
    assert "UNVERIFIED_ACTIVE_DEPLOYMENT" in gate.assess(
        status(percent=50),version(),target_sha=MAIN
    )["blockers"]
    assert "INVALID_EVIDENCE_SHAPE" in gate.assess(
        [status()],version(),target_sha=MAIN
    )["blockers"]
    assert "SOURCE_LINEAGE_UNVERIFIED" in gate.assess(
        status(message="manual"),version(),target_sha=MAIN
    )["blockers"]
    assert "INVALID_TARGET_SHA" in gate.assess(
        status(),version(),target_sha="HEAD"
    )["blockers"]
