"""Live deployment gate has zero mutating operations and never emits secrets."""
from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch

import pytest
from browser_control_3782_live_binding_gate import (
    _active_version_id,
    evaluate_live_versions,
    inspect_live,
)
from test_browser_control_3782_source_binding_gate import _complete


def _versions():
    chat, engine = _complete()
    def build(config, *, with_b54_auth=False):
        bindings = [
            {"name": x["binding"], "type": "d1", "database_id": x["database_id"]}
            for x in config["d1_databases"]
        ]
        bindings += [
            {"name": x["binding"], "type": "service", "service": x["service"]}
            for x in config["services"]
        ]
        if with_b54_auth:
            bindings += [
                {"name": "P01_ENGINE_CALLER_ID", "type": "plain_text", "text": "DO_NOT_PRINT"},
                {"name": "P01_ENGINE_CREDENTIAL", "type": "secret_text", "text": "SECRET_DO_NOT_PRINT"},
            ]
        return {"resources": {"bindings": bindings}}
    return build(chat, with_b54_auth=True), build(engine)


def test_complete_live_binding_graph_is_never_a_production_approval():
    chat, engine = _versions()
    a = evaluate_live_versions(chat, engine)
    assert a == {
        "scope": "authenticated_cloudflare_worker_deployments_readonly",
        "outcome": "LIVE_BINDING_GRAPH_VALID_NOT_AUTHORIZED",
        "blockers": [],
        "real_deployed_worker_versions_read": True,
        "remote_owner_d1_provision_verified": False,
        "owner_schema_applied_verified": False,
        "human_p01_verified": False,
        "production_activation_authorized": False,
    }


def test_live_missing_independent_owner_only_does_not_reinvent_b54_bindings():
    chat, engine = _versions()
    chat["resources"]["bindings"] = [
        v for v in chat["resources"]["bindings"]
        if v["name"] != "BROWSER_CONTROL_OWNER_P01_D1"
    ]
    engine["resources"]["bindings"] = [
        v for v in engine["resources"]["bindings"]
        if v["name"] != "BROWSER_CONTROL_OWNER_P01_D1"
    ]
    x = evaluate_live_versions(chat, engine)
    assert x["blockers"] == [
        "B54_INDEPENDENT_OWNER_D1_MISSING_OR_NO_ID",
        "ENGINE_INDEPENDENT_OWNER_D1_MISSING_OR_NO_ID",
    ]


@pytest.mark.parametrize("change,expected", [
    ("shared_chat", "OWNER_D1_ALIASES_PRIMARY_OR_ORIGINAL_ENGINE"),
    ("different_owner", "OWNER_D1_CROSS_SERVICE_DATABASE_ID_MISMATCH"),
    ("bad_service", "B54_EXISTING_P01_ENGINE_SERVICE_TARGET_MISMATCH"),
    ("missing_secret", "B54_P01_CALLER_CREDENTIAL_SECRET_MISSING"),
    ("secret_wrong_type", "B54_P01_CALLER_CREDENTIAL_SECRET_MISSING"),
    ("duplicate", "LIVE_CLOUDFLARE_METADATA_INVALID"),
])
def test_mismatches_refuse_without_values(change, expected):
    chat, engine = deepcopy(_versions())
    cb, eb = chat["resources"]["bindings"], engine["resources"]["bindings"]
    if change == "shared_chat":
        cb[1]["database_id"] = cb[0]["database_id"]
        eb[1]["database_id"] = cb[0]["database_id"]
    elif change == "different_owner":
        eb[1]["database_id"] = "99999999-9999-4999-8999-999999999999"
    elif change == "bad_service":
        next(x for x in cb if x["name"] == "P01_ENGINE_SERVICE")["service"] = "foreign"
    elif change == "missing_secret":
        cb[:] = [x for x in cb if x["name"] != "P01_ENGINE_CREDENTIAL"]
    elif change == "secret_wrong_type":
        next(x for x in cb if x["name"] == "P01_ENGINE_CREDENTIAL")["type"] = "plain_text"
    elif change == "duplicate":
        cb.append(dict(cb[0]))
    if change == "duplicate":
        with pytest.raises(ValueError, match="LIVE_CLOUDFLARE_METADATA_INVALID"):
            evaluate_live_versions(chat, engine)
        return
    x = evaluate_live_versions(chat, engine)
    assert expected in x["blockers"]
    assert "DO_NOT_PRINT" not in json.dumps(x)
    assert "SECRET_DO_NOT_PRINT" not in json.dumps(x)


def test_only_active_latest_100_percent_deployment_is_read():
    deployments = [
        {"created_on": "2026-10-07T00:00:00Z", "versions": [
            {"version_id": "a" * 36, "percentage": 100},
        ]},
        {"created_on": "2026-10-09T00:00:00Z", "versions": [
            {"version_id": "b" * 36, "percentage": 100},
        ]},
    ]
    assert _active_version_id(deployments) == "b" * 36
    deployments[-1]["versions"][0]["percentage"] = 50
    with pytest.raises(ValueError, match="ACTIVE_DEPLOYMENT_NOT_VERIFIED"):
        _active_version_id(deployments)


def test_no_explicit_account_means_no_wrangle_or_network():
    with (
        patch.dict("os.environ", {"CLOUDFLARE_ACCOUNT_ID": ""}),
        patch("browser_control_3782_live_binding_gate.subprocess.run") as process,
    ):
            response = inspect_live()
            assert response["blockers"] == ["CLOUDFLARE_ACCOUNT_UNSELECTED"]
            assert process.call_count == 0


def test_live_cli_only_queries_deployments_and_version_view():
    chat, engine = _versions()
    calls = []
    def fake_read(*args):
        calls.append(args)
        if args[:2] == ("deployments", "list"):
            marker = "a" * 36 if args[-1] == "padiem-chat" else "b" * 36
            return [{"created_on": "2026-10-09T00:00:00Z", "versions": [
                {"version_id": marker, "percentage": 100},
            ]}]
        if args[:2] == ("versions", "view"):
            content = chat if args[-1] == "padiem-chat" else engine
            return {"id": args[2], **content}
        raise AssertionError("not read-only metadata command")
    with patch("browser_control_3782_live_binding_gate._wrangler_read_only", side_effect=fake_read):
        response = inspect_live()
    assert response["outcome"] == "LIVE_BINDING_GRAPH_VALID_NOT_AUTHORIZED"
    assert [x[:2] for x in calls] == [
        ("deployments", "list"), ("versions", "view"),
        ("deployments", "list"), ("versions", "view"),
    ]
    assert response["production_activation_authorized"] is False


def test_wrangle_launch_is_metadata_read_only_and_does_not_expose_plaintext():
    import subprocess

    from browser_control_3782_live_binding_gate import _wrangler_read_only

    calls = []
    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args, 0, stdout='[{"name":"P01_ENGINE_CREDENTIAL","type":"secret_text"}]',
            stderr="",
        )
    with (
        patch.dict("os.environ", {"CLOUDFLARE_ACCOUNT_ID": "explicit-test-account"}),
        patch("browser_control_3782_live_binding_gate.shutil.which",
              return_value="C:/Program Files/wrangler.cmd"),
        patch("browser_control_3782_live_binding_gate.subprocess.run",
              side_effect=fake_run),
    ):
        output = _wrangler_read_only("deployments", "list", "--name", "padiem-chat")
    assert output[0]["name"] == "P01_ENGINE_CREDENTIAL"
    assert len(calls) == 1
    args, options = calls[0]
    assert args == [
        "C:/Program Files/wrangler.cmd",
        "deployments", "list", "--name", "padiem-chat", "--json",
    ]
    assert options["capture_output"] is True
    assert options["check"] is False
    assert "shell" not in options
