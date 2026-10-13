"""Network-free #3930 P01 SSE opt-in source/served/secret-preservation matrix."""
from __future__ import annotations
import copy
import importlib.util
import json
import subprocess
from contextlib import redirect_stdout
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
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
    assert patch["annotations"] == {"workers/message": f"B62 production code {SHA}"}
    assert "workers/triggered_by" not in patch["annotations"]
    gate.verify(*baseline, *post_from(baseline), SHA)


def test_sse_patch_never_sends_cloudflare_server_owned_annotation():
    # Cloudflare official PATCH /workers/scripts/{name}/settings contract:
    # workers/triggered_by is READ-ONLY and is set by Cloudflare.
    # The 10210 rollback incident already demonstrated this incompatibility.
    for flag in (None, "false", "true"):
        planned = gate.plan(*fixtures(flag), SHA)
        annotations = planned["payload"]["annotations"]
        assert set(annotations) == {"workers/message"}
        assert annotations["workers/message"] == "B62 production code " + SHA
        assert "workers/triggered_by" not in json.dumps(planned["payload"])
        assert len(planned["payload"]["bindings"]) == len(fixtures(flag)[0]["result"]["bindings"]) + (flag is None)


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


def test_refuses_wrong_type_duplicate_required_secret_and_stale_lineage():
    s, d, v = fixtures()
    for name in ("P01_ENGINE_CREDENTIAL", "IDENTITY_AUTHORITY_SERVICE"):
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


def test_real_cloudflare_postpatch_last_deployed_from_is_provenance_not_code():
    # Cloudflare GET-only #38440681029: old (43) -> failed PATCH version (44)
    # changed only P01 SSE flag + resources.script.last_deployed_from.
    # Script etag, runtime, assets and all existing bindings were identical.
    before = fixtures()
    before[2]["resources"]["script"]["last_deployed_from"] = "wrangler"
    after = post_from(before)
    after[2]["resources"]["script"]["last_deployed_from"] = "api"
    gate.verify(*before, *after, SHA)

    # The exception cannot hide an actual script update or other metadata.
    mutated = copy.deepcopy(after)
    mutated[2]["resources"]["script"]["etag"] = "changed-source"
    must_fail(lambda: gate.verify(*before, *mutated, SHA),
              "WORKER_CODE_OR_RUNTIME_DRIFT")

    mutated = copy.deepcopy(after)
    mutated[2]["resources"]["script"]["unexpected"] = "changed-source-field"
    must_fail(lambda: gate.verify(*before, *mutated, SHA),
              "WORKER_CODE_OR_RUNTIME_DRIFT")

    mutated = copy.deepcopy(after)
    mutated[2]["resources"]["script_runtime"]["compatibility_date"] = "different"
    must_fail(lambda: gate.verify(*before, *mutated, SHA),
              "WORKER_CODE_OR_RUNTIME_DRIFT")

    mutated = copy.deepcopy(after)
    mutated[2]["resources"]["assets"]["etag"] = "different"
    must_fail(lambda: gate.verify(*before, *mutated, SHA),
              "WORKER_CODE_OR_RUNTIME_DRIFT")

    mutated = copy.deepcopy(after)
    mutated[2]["resources"]["bindings"].append(
        b("UNAUTHORIZED_BINDING", "plain_text", text="new"))
    must_fail(lambda: gate.verify(*before, *mutated, SHA),
              "SERVED_BINDING_INVENTORY_DRIFT")


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
    assert plan["payload"]["annotations"] == {
        "workers/message": f"B62 Claw config rollback from pre-activation snapshot {SHA}"
    }
    assert "workers/triggered_by" not in json.dumps(plan["payload"])
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



def test_pr_source_ci_cannot_evict_queued_protected_b62_dispatch():
    # #38441362836 was cancelled before jobs while burst PR checks competed
    # for the original static concurrency group. Keep all protected Production
    # workflow_dispatch modes in ONE serialized group; isolate PR source CI.
    for name in ("b62-production-code-deploy-gate.yml",
                 "b62-claw-live-config-activation-gate.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        block = workflow.split("\nconcurrency:\n", 1)[1].split("\nenv:\n", 1)[0]
        assert "github.event_name == 'pull_request'" in block
        assert "github.event.pull_request.number" in block
        assert "|| 'production'" in block
        assert "cancel-in-progress: false" in block
        assert "cancel-in-progress: true" not in block
        assert "environment: production" in workflow
        # No additional human reviewer is ever required by this queue fix.
        assert "independent_review" not in block


def test_cloudflare_patch_http_refusal_is_code_only_and_never_retried():
    # #38442601251: PATCH was rejected but HTTP/error codes were not logged.
    # Keep the existing single mutation, fail closed and sanitize evidence.
    text = WORKFLOW.read_text(encoding="utf-8")
    start = "      - name: Apply one explicit SSE plain-text binding through existing Worker settings API"
    end = "      - name: Prove post-PATCH served version and exactly one allowed configuration change"
    block = text.split(start, 1)[1].split(end, 1)[0]
    assert "P01_SSE_PATCH_HTTP_STATUS=" in block
    assert "P01_SSE_PATCH_CLOUDFLARE_ERROR_CODES=" in block
    assert "P01_SSE_PATCH_AUTOMATIC_RETRY=NO" in block
    assert "SECRET_RESPONSE_DUMP=NO" in block
    assert "[0-9]+(,[0-9]+)*" in block
    assert 'select(type=="number")' in block
    assert "P01_SSE_PATCH=BLOCKED" in block
    assert "if [ " in block and "accepted" in block
    assert block.count("-X PATCH") == 1
    assert ".message" not in block
    assert "B62_P01_ENGINE_CREDENTIAL" not in block


def test_owner_single_approval_does_not_require_independent_reviewer():
    # Owner-delegated release: no second GitHub user or deployment-review gate.
    # Exact SHA, confirmation, rollback snapshot and served integrity remain.
    workflow = WORKFLOW.read_text(encoding="utf-8")
    block = workflow.split("\n  activate-p01-sse:\n", 1)[1]
    assert "b62_p01_sse_independent_review.py" not in block
    assert "/actions/runs/\u0024{GITHUB_RUN_ID}/approvals" not in block
    assert "Verify independent production deployment review" not in block
    assert "CONFIRM_ACTIVATE_B62_P01_SSE_OPTIN" in block
    assert "b62_p01_sse_optin_gate.py plan" in block
    assert "b62_p01_sse_optin_gate.py compare-before" in block
    assert "b62_p01_sse_optin_gate.py verify" in block
    assert "b62-claw-config-premutation-settings" in block

def test_cloudflare_10210_rollback_deployment_omits_unsupported_trigger_annotation():
    # Production #38432026154: Cloudflare POST /deployments returned 400/10210
    # because workers/triggered_by is not a supported deployment annotation.
    text = WORKFLOW.read_text(encoding="utf-8")
    start = "      - name: Restore the recorded pre-activation code version (CODE_VERSION_ROLLBACK)"
    end = "      - name: Read back the restored active code version"
    assert text.count(start) == 1 and text.count(end) == 1
    block = text.split(start, 1)[1].split(end, 1)[0]
    assert '"strategy": "percentage"' in block
    assert '"percentage": 100' in block
    assert '"workers/message"' in block
    assert '"workers/triggered_by"' not in block
    assert 'B62_CLAW_CONFIG_ROLLBACK_HTTP_STATUS=' in block
    assert 'jq -e' in block and '.success == true' in block


def test_cloudflare_10214_requires_snapshot_before_code_version_rollback():
    # Live #38432624306: code-first rollback left latest != active, and
    # subsequent settings PATCH was rejected HTTP 400 / 10214.
    workflow = WORKFLOW.read_text(encoding="utf-8")
    block = workflow.split("\n  rollback-config:\n", 1)[1].split(
        "\n  # #3930 SSE-only opt-in.", 1
    )[0]
    stages = [
        "Guard Cloudflare 10214 before configuration restoration",
        "Download the bounded pre-mutation settings snapshot",
        "Read current live settings for the config rollback plan",
        "Plan the snapshot-bounded config restore (CONFIG_ROLLBACK)",
        "Apply the snapshot-bounded config restore through the settings API",
        "Read back the restored config against the pre-mutation snapshot",
        "Restore the recorded pre-activation code version (CODE_VERSION_ROLLBACK)",
        "Read back the restored active code version",
        "Final config parity after restoring the pre-activation code version",
    ]
    positions = [block.index(name) for name in stages]
    assert positions == sorted(positions)
    assert "CONFIG_ROLLBACK_BLOCKED_LATEST_NOT_SERVED_CLOUDFLARE_10214=YES" in block
    assert "DO_NOT_REDEPLOY_UNACCEPTED_SSE_TO_FORCE_REPAIR=YES" in block
    assert "CONFIG_ROLLBACK_AFTER_CODE_VERSION=EXACT" in block
    assert "b62_binding_state_guard.py" in block




def _cli_evidence_paths(folder, before, after):
    paths = {}
    for prefix, triplet in (("before", before), ("after", after)):
        for key, value in zip(("settings", "deployments", "version"), triplet):
            path = folder / f"{prefix}-{key}.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            paths[f"{prefix}-{key}"] = str(path)
    return [
        "verify",
        "--before-settings", paths["before-settings"],
        "--before-deployments", paths["before-deployments"],
        "--before-version", paths["before-version"],
        "--settings", paths["after-settings"],
        "--deployments", paths["after-deployments"],
        "--version", paths["after-version"],
        "--target-sha", SHA,
    ]


def test_cli_postverify_reports_only_allowlisted_safe_reason():
    before = fixtures()
    after = post_from(before)
    extra = b("UNAPPROVED_EXTRA", "plain_text", text=PRIVATE)
    after[0]["result"]["bindings"].append(copy.deepcopy(extra))
    after[2]["resources"]["bindings"].append(copy.deepcopy(extra))
    with TemporaryDirectory() as td:
        argv = _cli_evidence_paths(Path(td), before, after)
        output = StringIO()
        with redirect_stdout(output):
            assert gate.main(argv) == 1
    result = output.getvalue()
    assert "P01_SSE_OPTIN_GATE_REASON=POST_SETTINGS_DRIFT" in result
    assert "P01_SSE_OPTIN_GATE=BLOCKED" in result
    assert "SECRET_VALUES_EMITTED=0" in result
    assert PRIVATE not in result


def test_cli_unknown_exception_never_exposes_sensitive_text():
    before = fixtures()
    with TemporaryDirectory() as td:
        argv = _cli_evidence_paths(Path(td), before, before)
        output = StringIO()
        with patch.object(gate, "verify", side_effect=gate.OptInRefused(PRIVATE)):
            with redirect_stdout(output):
                assert gate.main(argv) == 1
    result = output.getvalue()
    assert "P01_SSE_OPTIN_GATE_REASON=UNCLASSIFIED" in result
    assert PRIVATE not in result


def test_postpatch_workflow_prints_only_bounded_reason_after_failed_verification():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    verifier = workflow.split(
        "- name: Prove post-PATCH served version and exactly one allowed configuration change",
        1
    )[1].split("\n      - name:", 1)[0]
    assert "P01_SSE_OPTIN_GATE_REASON=[A-Z0-9_]{1,64}" in verifier
    assert 'sse-verify.log" | tail -n 1 || true' in verifier
    assert "P01_SSE_POST_SERVED_INTEGRITY=BLOCKED" in verifier
    assert "cat \"${RUNNER_TEMP}/sse-verify.log\"" in verifier  # only on success
    assert verifier.index("grep -E '^P01_SSE_OPTIN_GATE_REASON=") < verifier.index(
        "P01_SSE_POST_SERVED_INTEGRITY=BLOCKED"
    )


def test_rollback_http_500_10013_is_bounded_and_stays_fail_closed():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    rollback = workflow.split("\n  rollback-config:\n", 1)[1].split(
        "\n  # #3930 SSE-only opt-in.", 1)[0]
    apply = rollback.split(
        "- name: Apply the snapshot-bounded config restore through the settings API", 1
    )[1].split("\n      - name: Read back the restored config", 1)[0]
    assert apply.count("-X PATCH") == 1
    assert "--connect-timeout 8 --max-time 40 -X PATCH" in apply
    assert "-D \"${headers}\" -o \"${response}\"" in apply
    assert "CONFIG_ROLLBACK_PATCH_CLOUDFLARE_ERROR_CODES=" in apply
    assert "CONFIG_ROLLBACK_PATCH_CF_RAY=" in apply
    assert "CONFIG_ROLLBACK_PATCH_AUTOMATIC_RETRY=NO" in apply
    assert "CONFIG_ROLLBACK_POSTERROR_SINGLE_READ=SNAPSHOT_EXACT" in apply
    assert "CONFIG_ROLLBACK_POSTERROR_SINGLE_READ=NOT_EXACT_OR_UNAVAILABLE" in apply
    assert "--connect-timeout 8 --max-time 20" in apply
    assert "b62_binding_state_guard.py" in apply
    assert "CONFIG_ROLLBACK_POSTERROR_ACCEPTANCE=NO" in apply
    assert "FULL_CONFIG_ROLLBACK_CLAIM=NO" in apply
    assert "CONFIG_ROLLBACK=FAIL" in apply
    assert "exit 1" in apply
    assert "| {code, message}" not in apply
    # The follow-up GET is observation only; never jump to code rollback
    # after a rejected PATCH or claim full configuration restoration.
    assert apply.index("CONFIG_ROLLBACK_POSTERROR_ACCEPTANCE=NO") < apply.index("exit 1")
    assert rollback.index("Apply the snapshot-bounded config restore") < rollback.index(
        "Restore the recorded pre-activation code version")


def test_cloudflare_error_code_filter_ignores_secret_bearing_error_messages():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    apply = workflow.split(
        "- name: Apply the snapshot-bounded config restore through the settings API", 1
    )[1].split("\n      - name: Read back the restored config", 1)[0]
    expression = '[.errors[]? | objects | .code | select(type=="number") | tostring] | unique | join(",")'
    assert expression in apply
    payload = {"success": False, "errors": [
        {"code": 10013, "message": PRIVATE},
        {"code": 10013, "message": "unknown error"},
        {"code": "10057", "message": "must not print"},
    ]}
    result = subprocess.run(["jq", "-r", expression],
                            input=json.dumps(payload), text=True, capture_output=True,
                            check=True)
    assert result.stdout.strip() == "10013"
    assert PRIVATE not in result.stdout



def _settings_generated_post(before):
    post = post_from(before)
    post[1]["result"]["deployments"][0]["annotations"]["workers/message"] = (
        "Cloudflare settings update; no source SHA")
    post[2]["annotations"] = {"workers/message": f"B62 production code {SHA}"}
    return post


def test_actual_second_incident_provider_deployment_note_uses_immutable_version_sha():
    # GET-only Actions #38454872275 proved deployment note OTHER while the
    # newly served immutable version message is exactly the original source SHA.
    before = fixtures()
    post = _settings_generated_post(before)
    gate.verify(*before, *post, SHA)
    # PRE-PATCH readiness and concurrent-mutation guards remain strict.
    must_fail(lambda: gate.plan(*post, SHA), "SOURCE_LINEAGE_UNVERIFIED")
    must_fail(lambda: gate.compare_before(*before, *post, SHA),
              "SOURCE_LINEAGE_UNVERIFIED")


def test_postpatch_version_lineage_must_be_exact_and_noop_cannot_use_fallback():
    before = fixtures()
    post = _settings_generated_post(before)
    post[2].pop("annotations")
    must_fail(lambda: gate.verify(*before, *post, SHA),
              "POST_VERSION_LINEAGE_UNVERIFIED")
    post = _settings_generated_post(before)
    post[2]["annotations"]["workers/message"] = PRIVATE
    must_fail(lambda: gate.verify(*before, *post, SHA),
              "POST_VERSION_LINEAGE_UNVERIFIED")
    post = _settings_generated_post(before)
    post[1]["result"]["deployments"][0]["annotations"]["workers/message"] = (
        f"B62 production code {'b'*40}")
    must_fail(lambda: gate.verify(*before, *post, SHA),
              "SOURCE_SHA_MISMATCH")
    noop = fixtures("true")
    noop[1]["result"]["deployments"][0]["annotations"]["workers/message"] = (
        "provider settings change")
    noop[2]["annotations"] = {"workers/message": f"B62 production code {SHA}"}
    must_fail(lambda: gate.verify(*fixtures("true"), *noop, SHA, no_op=True),
              "SOURCE_LINEAGE_UNVERIFIED")


def test_postpatch_lineage_fallback_never_weakens_code_binding_or_flag_guards():
    before = fixtures()
    altered = _settings_generated_post(before)
    altered[2]["resources"]["script"]["etag"] = "injected-other-code"
    must_fail(lambda: gate.verify(*before, *altered, SHA),
              "WORKER_CODE_OR_RUNTIME_DRIFT")
    altered = _settings_generated_post(before)
    altered[2]["resources"]["bindings"][-1]["text"] = "false"
    must_fail(lambda: gate.verify(*before, *altered, SHA), "SERVED_FLAG_DRIFT")
    altered = _settings_generated_post(before)
    altered[0]["result"]["bindings"].append(b("UNAPPROVED", "plain_text", text=PRIVATE))
    altered[2]["resources"]["bindings"].append(b("UNAPPROVED", "plain_text", text=PRIVATE))
    must_fail(lambda: gate.verify(*before, *altered, SHA), "POST_SETTINGS_DRIFT")
    altered = _settings_generated_post(before)
    altered[1]["result"]["deployments"][0]["versions"][0]["percentage"] = 50
    must_fail(lambda: gate.verify(*before, *altered, SHA), "ACTIVE_VERSION_NOT_UNIQUE")


def test_postpatch_source_reason_is_finite_without_exposing_secret():
    before = fixtures()
    post = _settings_generated_post(before)
    post[2]["annotations"]["workers/message"] = PRIVATE
    with TemporaryDirectory() as td:
        argv = _cli_evidence_paths(Path(td), before, post)
        output = StringIO()
        with redirect_stdout(output):
            assert gate.main(argv) == 1
    result = output.getvalue()
    assert "P01_SSE_OPTIN_GATE_REASON=POST_VERSION_LINEAGE_UNVERIFIED" in result
    assert PRIVATE not in result
    assert "SECRET_VALUES_EMITTED=0" in result

if __name__ == "__main__":
    for name, func in sorted(globals().copy().items()):
        if name.startswith("test_") and callable(func):
            func()
            print(name + "=PASS")

