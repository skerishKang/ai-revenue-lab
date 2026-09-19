"""B62 Google auth activation gate regressions (#2536, SOURCE-ONLY)."""
from __future__ import annotations

import importlib.util
import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github" / "scripts" / "b62_google_auth_activation.py"

EXPECTED_URL = "https://padiem-chat.charliekant.workers.dev"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_google_auth_activation", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _binding(name, kind, **extra):
    return {"name": name, "type": kind, **extra}


def _settings(bindings):
    return {"success": True, "result": {"bindings": bindings}}


BASE = [
    _binding("ASSETS", "assets"),
    _binding("B14_SERVICE", "service", service="ai-revenue-korean-ai-platform"),
    _binding("PADIEM_CHAT_DB", "d1", id="11111111-1111-1111-1111-111111111111"),
    _binding("IDENTITY_AUTHORITY_SERVICE", "service",
             service="padiem-control-plane-identity"),
    _binding("PADIEM_WORKSPACE_FILES", "r2_bucket", bucket_name="padiem-workspace-files"),
    _binding("PADIEM_CHAT_RUNTIME_MODE", "plain_text", text="b14"),
    _binding("PADIEM_CHAT_LIVE_ENABLED", "plain_text", text="true"),
    _binding("PADIEM_CHAT_QUOTA_SALT", "secret_text"),
]


def _full_auth(extra=()):
    helper = _load_helper()
    bindings = list(BASE) + [
        _binding("PADIEM_CHAT_AUTH_MODE", "plain_text", text="google"),
        _binding("PADIEM_CHAT_PUBLIC_BASE_URL", "plain_text", text=EXPECTED_URL),
        _binding("PADIEM_CHAT_GOOGLE_CLIENT_ID", "plain_text", text="test-client-id"),
        _binding("PADIEM_CHAT_GOOGLE_CLIENT_SECRET", "secret_text"),
        _binding("PADIEM_CHAT_SESSION_SECRET", "secret_text"),
    ] + list(extra)
    states = helper.classify_auth_config(
        _settings(bindings), expected_public_base_url=EXPECTED_URL
    )
    return helper, bindings, states


def test_missing_requires_activation_and_exact_passes():
    helper = _load_helper()
    states = helper.classify_auth_config(
        _settings(list(BASE)), expected_public_base_url=EXPECTED_URL
    )
    assert helper.disposition(states) == "ACTIVATION_REQUIRED"
    assert all(states[n] == "missing" for n in helper.AUTH_TARGET_TYPES)
    assert states[helper.SESSION_MAX_AGE_NAME] == "not_configured"
    _, _, full = _full_auth()
    assert helper.disposition(full) == "ALREADY_EXACT"


def test_wrong_type_bad_mode_bad_url_fail_closed():
    helper = _load_helper()
    _, bindings, _ = _full_auth()
    bad = [dict(b) for b in bindings]
    for row in bad:
        if row["name"] == "PADIEM_CHAT_AUTH_MODE":
            row["type"] = "secret_text"
    states = helper.classify_auth_config(_settings(bad), expected_public_base_url=EXPECTED_URL)
    assert helper.disposition(states) == "REFUSE_WRONG_TYPE"

    _, bindings, _ = _full_auth()
    bad = [dict(b) for b in bindings]
    for row in bad:
        if row["name"] == "PADIEM_CHAT_AUTH_MODE":
            row.update({"type": "plain_text", "text": "off"})
    states = helper.classify_auth_config(_settings(bad), expected_public_base_url=EXPECTED_URL)
    assert states["PADIEM_CHAT_AUTH_MODE"] == "invalid"
    assert helper.disposition(states) == "REFUSE_INVALID"

    for bad_url in ("http://x.example.test",
                    "https://padiem-chat.charliekant.workers.dev/app",
                    "https://padiem-chat.charliekant.workers.dev/?x=1",
                    "not-a-url", ""):
        _, bindings, _ = _full_auth()
        bad = [dict(b) for b in bindings]
        for row in bad:
            if row["name"] == "PADIEM_CHAT_PUBLIC_BASE_URL":
                row.update({"type": "plain_text", "text": bad_url})
        states = helper.classify_auth_config(_settings(bad), expected_public_base_url=EXPECTED_URL)
        assert states["PADIEM_CHAT_PUBLIC_BASE_URL"] == "invalid", bad_url

    _, bindings, _ = _full_auth()
    bad = [dict(b) for b in bindings]
    for row in bad:
        if row["name"] == "PADIEM_CHAT_PUBLIC_BASE_URL":
            row.update({"type": "plain_text", "text": "https://other.example.test"})
    states = helper.classify_auth_config(_settings(bad), expected_public_base_url=EXPECTED_URL)
    assert states["PADIEM_CHAT_PUBLIC_BASE_URL"] == "drift"
    assert helper.disposition(states) == "REFUSE_INVALID"


def test_secret_wrong_type_and_empty_client_id_fail_closed():
    helper = _load_helper()
    _, bindings, _ = _full_auth()
    bad = [dict(b) for b in bindings]
    for row in bad:
        if row["name"] == "PADIEM_CHAT_GOOGLE_CLIENT_SECRET":
            row.update({"type": "plain_text", "text": "exposed"})
    states = helper.classify_auth_config(_settings(bad), expected_public_base_url=EXPECTED_URL)
    assert helper.disposition(states) == "REFUSE_WRONG_TYPE"

    _, bindings, _ = _full_auth()
    bad = [dict(b) for b in bindings]
    for row in bad:
        if row["name"] == "PADIEM_CHAT_GOOGLE_CLIENT_ID":
            row.update({"type": "plain_text", "text": "   "})
    states = helper.classify_auth_config(_settings(bad), expected_public_base_url=EXPECTED_URL)
    assert states["PADIEM_CHAT_GOOGLE_CLIENT_ID"] == "invalid"


def test_optional_ttl_never_blocks():
    helper = _load_helper()
    _, _, states = _full_auth()
    assert states[helper.SESSION_MAX_AGE_NAME] == "not_configured"
    assert helper.disposition(states) == "ALREADY_EXACT"
    _, _, states = _full_auth(
        [_binding("PADIEM_CHAT_SESSION_MAX_AGE_SECONDS", "plain_text", text="3600")])
    assert states[helper.SESSION_MAX_AGE_NAME] == "exact"
    _, _, states = _full_auth(
        [_binding("PADIEM_CHAT_SESSION_MAX_AGE_SECONDS", "plain_text", text="10")])
    assert states[helper.SESSION_MAX_AGE_NAME] == "invalid"
    assert helper.disposition(states) == "ALREADY_EXACT"


def test_plan_preserves_unrelated_names_only():
    helper, bindings, _ = _full_auth()
    plan = helper.build_activation_plan(
        _settings(bindings), expected_public_base_url=EXPECTED_URL, target_sha="f" * 40)
    assert plan["no_op"] is True and plan["changes"] == []
    inherited = {b["name"] for b in plan["payload"]["bindings"] if b["type"] == "inherit"}
    assert {"ASSETS", "PADIEM_CHAT_DB"} <= inherited
    text = json.dumps(plan["payload"])
    assert "test-client-id" not in text
    assert "secret_text" not in text
    plan2 = helper.build_activation_plan(
        _settings(list(BASE)), expected_public_base_url=EXPECTED_URL, target_sha="f" * 40)
    assert plan2["no_op"] is False
    assert "AUTH_SET_PADIEM_CHAT_AUTH_MODE" in plan2["changes"]
    assert "AUTH_SECRET_PLACEHOLDER_PADIEM_CHAT_SESSION_SECRET" in plan2["changes"]
    assert "AUTH_PLACEHOLDER_PADIEM_CHAT_GOOGLE_CLIENT_ID" in plan2["changes"]


def test_plan_refuses_and_bad_sha():
    helper, bindings, _ = _full_auth()
    bad = [dict(b) for b in bindings]
    for row in bad:
        if row["name"] == "PADIEM_CHAT_AUTH_MODE":
            row.update({"type": "plain_text", "text": "off"})
    with pytest.raises(helper.AuthGateError):
        helper.build_activation_plan(
            _settings(bad), expected_public_base_url=EXPECTED_URL, target_sha="f" * 40)
    with pytest.raises(helper.AuthGateError):
        helper.build_activation_plan(
            _settings(bindings), expected_public_base_url=EXPECTED_URL, target_sha="short")


def test_cli_closed_vocabulary():
    helper = _load_helper()

    with tempfile.TemporaryDirectory() as tmp:
        settings = Path(tmp) / "settings.json"
        settings.write_text(json.dumps(_settings(list(BASE))), encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = helper.main(["classify", "--settings", str(settings),
                              "--expected-public-base-url", EXPECTED_URL])
        assert rc == 0
        out = buf.getvalue()
        assert "B62_GOOGLE_AUTH_DISPOSITION=ACTIVATION_REQUIRED" in out
        assert "SECRET_VALUES_READ=0" in out
        assert "PRODUCTION_MUTATION=0" in out
        assert '"text"' not in out
        assert "cookie" not in out.lower()


def test_reuses_helpers_and_matches_config():
    helper = _load_helper()
    source = HELPER.read_text(encoding="utf-8")
    assert "parse_live_bindings" in source
    assert "canonical_binding" in source
    worker = (ROOT / "apps" / "padiem-chat" / "app" / "worker_config.py").read_text(
        encoding="utf-8")
    for name in helper.AUTH_ALLOWLIST:
        assert name in worker, name
    routes = (ROOT / "apps" / "padiem-chat" / "app" / "claw_routes.py").read_text(
        encoding="utf-8")
    assert "_resolve_canonical_tenant" in routes
    assert "workspace_scope_unavailable" in routes


def test_workflow_is_source_only_and_exact_main_guarded():
    workflow = (
        ROOT / ".github" / "workflows" / "b62-google-auth-activation-gate.yml"
    ).read_text(encoding="utf-8")
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in workflow
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "READONLY_EXACT_MAIN_SHA=PASS" in workflow
    assert "b62_google_auth_activation.py classify" in workflow
    assert "b62_google_auth_activation.py prereq" in workflow
    assert "AUTH_VALUE_OUTPUT=0" in workflow
    assert "SECRET_VALUES_READ=0" in workflow
    assert "SECRET_VALUES_EMITTED=0" in workflow
    assert "PRODUCTION_MUTATION=0" in workflow
    assert "activate_auth_config" not in workflow
    for token in ("curl -sS -X PATCH", "wrangler deploy", "-X PUT",
                  "-X POST", "-X DELETE", "--data"):
        assert token not in workflow, token
    assert "cookie" not in workflow.lower()
    assert "password" not in workflow.lower()
    helper_src = HELPER.read_text(encoding="utf-8")
    assert "GOOGLE_CLIENT_SECRET" in helper_src
    assert "SESSION_SECRET" in helper_src


def test_activation_plan_mode_is_mutation_free_and_confirmed():
    workflow = (
        ROOT / ".github" / "workflows" / "b62-google-auth-activation-gate.yml"
    ).read_text(encoding="utf-8")
    assert "activation_plan_readonly" in workflow
    assert "PLAN_B62_GOOGLE_AUTH_ACTIVATION_ONLY" in workflow
    assert "ACTIVATION_DISPATCH=NOT_PERFORMED" in workflow
    assert "environment: production" in workflow
    assert "b62_google_auth_activation.py plan" in workflow
    assert "ACTIVATION_PLAN_SECRET_VALUES_PRESENT=0" in workflow
    plan_job = workflow.split("activation-plan-readonly:", 1)[1]
    for verb in ("-X PATCH", "-X PUT", "-X POST", "-X DELETE", "--data",
                 "-F \"settings=", "wrangler", "secrets."):
        if verb == "secrets.":
            # only read-only API credentials may be referenced in the job
            assert "secrets.CLOUDFLARE_API_TOKEN" in plan_job
            assert "secrets.CLOUDFLARE_ACCOUNT_ID" in plan_job
            continue
        assert verb not in plan_job, verb


def test_disposition_fails_closed_on_partial_or_unknown_states():
    helper = _load_helper()
    with pytest.raises(helper.AuthGateError):
        helper.disposition({helper.AUTH_MODE_NAME: "exact"})
    with pytest.raises(helper.AuthGateError):
        helper.disposition({"UNREVIEWED_BINDING": "exact"})


def test_prereq_readback_shapes():
    helper = _load_helper()
    prereq = helper.read_prerequisites(_settings(list(BASE)))
    assert prereq["PADIEM_CHAT_DB"] == "exact"
    assert prereq["IDENTITY_AUTHORITY_SERVICE"] == "exact"
    assert prereq["PADIEM_WORKSPACE_FILES"] == "exact"
    prereq = helper.read_prerequisites(_settings([_binding("ASSETS", "assets")]))
    assert prereq["PADIEM_CHAT_DB"] == "missing"
    assert prereq["IDENTITY_AUTHORITY_SERVICE"] == "missing"
