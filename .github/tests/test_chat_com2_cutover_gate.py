"""Offline contracts for the manual Chat domain cutover gate.

All network/process boundaries are blocked unless a test supplies a fake.
These tests do not dispatch Actions, deploy, or access Cloudflare.
"""
from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "chat_com2_cutover_gate", ROOT / ".github/scripts/chat_com2_cutover_gate.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
WORKFLOW_PATH = ROOT / ".github/workflows/chat-com2-cutover-gate.yml"
SHA = "a" * 40
ZONE = "b" * 32
PRIVATE = "synthetic-private-token-do-not-log"
GENERATION = "20261031T042000Z"


def signed_evidence(*, sha=SHA, generation=GENERATION, expired=False):
    # RFC 8032 section 7.1 TEST 1 public test vector; not a generated key.
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    ))
    import chat_rehearsal_evidence as evidence
    now = int(datetime.now(timezone.utc).timestamp())
    finish = now - (90000 if expired else 60)
    payload = {
        "schema": evidence.SCHEMA, "issuer": "COM2", "target": evidence.STAGING_TARGET,
        "main_sha": sha, "generation_id": generation,
        "generation_sha256": "e" * 64, "report_sha256": "f" * 64,
        "started_at": finish - 60, "finished_at": finish, "issued_at": finish,
        "expires_at": finish + evidence.MAX_EVIDENCE_AGE_SECONDS,
        "result": "PASS", "stages": list(evidence.REHEARSAL_STAGES), "skipped_stages": [],
    }
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return evidence.sign_summary(payload, private_pem), public_pem.decode()


def environment(mode="preflight"):
    return {
        "MODE": mode, "TARGET_SHA": SHA, "GITHUB_SHA": SHA,
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
        "CONFIRMATION": f"{mode.upper()}_CHAT_COM2_{SHA}",
        "GITHUB_REPOSITORY": "skerishKang/ai-revenue-lab",
        "CLOUDFLARE_ACCOUNT_ID": "c" * 32, "CLOUDFLARE_API_TOKEN": PRIVATE,
        "GH_TOKEN": PRIVATE, "READONLY_RUN_ID": "456", "TARGET_GENERATION_ID": GENERATION,
        "REHEARSAL_EVIDENCE_URL": "https://evidence.invalid/rehearsal.json",
    }


@pytest.fixture(autouse=True)
def no_external_effects(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("test attempted an unstubbed network or process call")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(gate, "request", denied)


def record_methods(monkeypatch, instance):
    events = []
    for name in (
        "exact_main", "account", "preflight", "readonly", "prior_readonly",
        "deploy", "move_domain", "probe", "freeze_probes", "legacy_freeze_config", "rehearsal",
    ):
        def record(*args, _name=name, **kwargs):
            events.append((_name, args, kwargs))
        monkeypatch.setattr(instance, name, record)
    return events


def report():
    stamp = datetime.now(timezone.utc).isoformat()
    return {
        "target": "https://chat-com2-staging.padiem.net", "dry_run": False,
        "failed_stage": None,
        "stages": [
            {"stage": stage, "passed": True, "skipped": False,
             "started_utc": stamp, "ended_utc": stamp, "detail": "executed"}
            for stage in gate.REHEARSAL_STAGES
        ],
    }


def run_record(workflow=gate.WORKFLOW, **changes):
    result = {
        "head_sha": SHA, "head_branch": "main", "event": "workflow_dispatch",
        "status": "completed", "conclusion": "success",
        "path": ".github/workflows/" + workflow,
        "display_title": f"chat-com2/readonly/{SHA}/{GENERATION}",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result.update(changes)
    return result


def domain_row(service=gate.LEGACY, **changes):
    result = {
        "hostname": gate.HOST, "service": service, "enabled": True,
        "zone_name": "padiem.net", "zone_id": ZONE, "previews_enabled": False,
    }
    result.update(changes)
    return result


@pytest.mark.parametrize("mode", gate.MODES)
def test_each_mode_requires_its_own_confirmation(mode):
    env = environment(mode)
    gate.validate_dispatch(env)
    for other in gate.MODES:
        if other != mode:
            env["CONFIRMATION"] = f"{other.upper()}_CHAT_COM2_{SHA}"
            with pytest.raises(gate.Refused, match="confirmation_mismatch"):
                gate.validate_dispatch(env)


@pytest.mark.parametrize("field,value,reason", [
    ("GITHUB_REF", "refs/heads/feature", "main_required"),
    ("GITHUB_REF", "refs/tags/main", "main_required"),
    ("GITHUB_EVENT_NAME", "pull_request", "dispatch_required"),
    ("GITHUB_SHA", "d" * 40, "dispatch_sha_mismatch"),
    ("TARGET_SHA", "a" * 39, "sha_invalid"),
    ("TARGET_SHA", "A" * 40, "sha_invalid"),
    ("MODE", "deploy", "mode_invalid"),
    ("TARGET_GENERATION_ID", "", "evidence_generation_invalid"),
    ("TARGET_GENERATION_ID", "../other", "evidence_generation_invalid"),
])
def test_invalid_dispatch_stops_before_any_action(monkeypatch, field, value, reason):
    env = environment()
    env[field] = value
    instance = gate.Gate(env)
    calls = record_methods(monkeypatch, instance)
    with pytest.raises(gate.Refused, match=reason):
        instance.execute()
    assert calls == []


@pytest.mark.parametrize("checkout,remote,reason", [
    ("d" * 40, SHA, "checkout_sha_mismatch"),
    (SHA, "d" * 40, "main_sha_mismatch"),
])
def test_main_sha_guard_checks_checkout_and_fresh_remote(monkeypatch, checkout, remote, reason):
    def command(argv, **kwargs):
        return checkout if argv[1] == "rev-parse" else f"{remote}\trefs/heads/main"
    monkeypatch.setattr(gate, "run_command", command)
    with pytest.raises(gate.Refused, match=reason):
        gate.Gate(environment()).exact_main()


@pytest.mark.parametrize("mode,expected", [
    ("preflight", ["exact_main", "account", "preflight"]),
    ("readonly", ["exact_main", "account", "preflight", "readonly"]),
    ("switch", ["exact_main", "account", "preflight", "readonly", "prior_readonly",
                "exact_main", "deploy", "readonly", "rehearsal", "move_domain", "probe", "probe", "probe", "freeze_probes"]),
    ("rollback", ["exact_main", "account", "legacy_freeze_config", "move_domain", "freeze_probes"]),
])
def test_mode_order_and_mutation_boundary(monkeypatch, mode, expected):
    instance = gate.Gate(environment(mode))
    events = record_methods(monkeypatch, instance)
    instance.execute()
    assert [event[0] for event in events] == expected
    if mode in {"preflight", "readonly"}:
        assert not any(name in {"deploy", "move_domain"} for name, _, _ in events)
    elif mode == "switch":
        assert events[9] == ("move_domain", (gate.FRONT,), {})
        # The public auth probe must have no client proof: the front signs it.
        assert ("probe", (gate.PUBLIC, "/api/auth/status", 200), {}) in events
        assert ("probe", (gate.ORIGIN, "/api/auth/status", 403), {}) in events
    else:
        assert events[3] == ("move_domain", (gate.LEGACY,), {})
        assert not any(name in {"preflight", "readonly", "prior_readonly", "deploy"} for name, _, _ in events)


@pytest.mark.parametrize("failure", ["preflight", "readonly", "prior_readonly", "deploy", "rehearsal"])
def test_failed_switch_prerequisite_never_moves_domain(monkeypatch, failure):
    instance = gate.Gate(environment("switch"))
    events = record_methods(monkeypatch, instance)
    def refuse(*args, **kwargs):
        raise gate.Refused("synthetic_failure")
    monkeypatch.setattr(instance, failure, refuse)
    with pytest.raises(gate.Refused, match="synthetic_failure"):
        instance.execute()
    assert not any(name == "move_domain" for name, _, _ in events)


def test_switch_post_move_failure_does_not_auto_rollback(monkeypatch):
    instance = gate.Gate(environment("switch"))
    events = record_methods(monkeypatch, instance)
    monkeypatch.setattr(instance, "probe", lambda *a, **kw: gate.require(False, "post_probe_failed"))
    with pytest.raises(gate.Refused, match="post_probe_failed"):
        instance.execute()
    assert [args for name, args, _ in events if name == "move_domain"] == [(gate.FRONT,)]


def test_deploy_preserves_vars_and_enforces_canonical_static_origin(monkeypatch):
    instance = gate.Gate(environment("switch"))
    calls = []
    monkeypatch.setattr(instance, "domain", lambda: domain_row())
    monkeypatch.setattr(gate, "run_command", lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(instance, "front_config", lambda **kw: calls.append(("verify", kw)))
    instance.deploy()
    argv, kwargs = calls[0]
    assert argv[:4] == ["npx", "--no-install", "wrangler", "deploy"]
    assert "--keep-vars" in argv
    assert argv[argv.index("--config") + 1] == "apps/padiem-chat-front/wrangler.toml"
    assert {argv[i + 1] for i, arg in enumerate(argv) if arg == "--var"} == {
        "COM2_CANONICAL:writes", "FALLBACK_MODE:static", "FRONT_ORIGIN:" + gate.ORIGIN,
    }
    assert "GH_TOKEN" not in kwargs["env"]
    assert calls[1] == ("verify", {"deployed": True})


@pytest.mark.parametrize("target", [gate.FRONT, gate.LEGACY])
def test_domain_change_is_one_put_then_readback(monkeypatch, target):
    instance = gate.Gate(environment("switch" if target == gate.FRONT else "rollback"))
    source = gate.LEGACY if target == gate.FRONT else gate.FRONT
    events = []
    rows = iter([domain_row(source), domain_row(target)])
    monkeypatch.setattr(instance, "exact_main", lambda: events.append("main"))
    monkeypatch.setattr(instance, "domain", lambda: next(rows))
    monkeypatch.setattr(instance, "cf", lambda path, **kw: events.append((path, kw)))
    instance.move_domain(target)
    assert events == ["main", ("/workers/domains", {"method": "PUT", "payload": {
        "hostname": gate.HOST, "service": target, "zone_id": ZONE, "enabled": True,
        "previews_enabled": False,
    }})]


def test_domain_put_failure_is_not_retried_or_deleted(monkeypatch):
    instance = gate.Gate(environment("switch"))
    calls = []
    monkeypatch.setattr(instance, "exact_main", lambda: None)
    monkeypatch.setattr(instance, "domain", lambda: domain_row())
    def failed(path, **kwargs):
        calls.append((path, kwargs["method"]))
        raise gate.Refused("cloudflare_http_failed")
    monkeypatch.setattr(instance, "cf", failed)
    with pytest.raises(gate.Refused, match="cloudflare_http_failed"):
        instance.move_domain(gate.FRONT)
    assert calls == [("/workers/domains", "PUT")]


def test_domain_wrong_readback_refuses_without_second_mutation(monkeypatch):
    instance = gate.Gate(environment("switch"))
    calls = []
    monkeypatch.setattr(instance, "exact_main", lambda: None)
    monkeypatch.setattr(instance, "domain", lambda: domain_row())
    monkeypatch.setattr(instance, "cf", lambda path, **kw: calls.append(kw))
    with pytest.raises(gate.Refused, match="domain_move_unverified"):
        instance.move_domain(gate.FRONT)
    assert len(calls) == 1


@pytest.mark.parametrize("rows,reason", [
    ([], "domain_not_unique"),
    ([domain_row(), domain_row()], "domain_not_unique"),
    ([domain_row("unrelated-worker")], "domain_scope_mismatch"),
    ([domain_row(enabled=False)], "domain_scope_mismatch"),
    ([domain_row(zone_name="unrelated.net")], "domain_scope_mismatch"),
    ([domain_row(zone_id="bad")], "domain_scope_mismatch"),
])
def test_domain_scope_is_fail_closed(monkeypatch, rows, reason):
    instance = gate.Gate(environment())
    monkeypatch.setattr(instance, "cf", lambda path: rows)
    with pytest.raises(gate.Refused, match=reason):
        instance.domain()


@pytest.mark.parametrize("field,value", [
    ("head_sha", "d" * 40), ("head_branch", "feature"), ("event", "pull_request"),
    ("status", "in_progress"), ("conclusion", "failure"),
    ("path", ".github/workflows/unrelated.yml"),
])
def test_prior_run_requires_successful_exact_main_dispatch(monkeypatch, field, value):
    instance = gate.Gate(environment("switch"))
    monkeypatch.setattr(instance, "github", lambda path: run_record(**{field: value}))
    with pytest.raises(gate.Refused, match="source_run_not_successful_exact_main"):
        instance.prior_readonly()


def test_prior_readonly_title_cannot_be_switch_or_preflight(monkeypatch):
    instance = gate.Gate(environment("switch"))
    monkeypatch.setattr(instance, "github", lambda path: run_record(display_title=f"chat-com2/preflight/{SHA}"))
    with pytest.raises(gate.Refused, match="readonly_run_required"):
        instance.prior_readonly()
    monkeypatch.setattr(instance, "github", lambda path: run_record())
    instance.prior_readonly()


@pytest.mark.parametrize("mutation,reason", [
    (lambda r: r.update(dry_run=True), "rehearsal_not_pass"),
    (lambda r: r.update(target="http://localhost:8801"), "rehearsal_target"),
    (lambda r: r.update(failed_stage="reflect"), "rehearsal_not_pass"),
    (lambda r: r["stages"].reverse(), "rehearsal_order"),
    (lambda r: r["stages"][4].update(passed=False), "rehearsal_stage_not_executed"),
    (lambda r: r["stages"][4].update(started_utc=""), "rehearsal_stage_not_executed"),
    (lambda r: r["stages"][4].update(skipped=True), "rehearsal_skipped"),
    (lambda r: r["stages"][6].update(skipped=True), "rehearsal_skipped"),
])
def test_rehearsal_refuses_unexecuted_or_wrong_evidence(mutation, reason):
    data = report()
    mutation(data)
    with pytest.raises(gate.Refused, match=reason):
        gate.validate_rehearsal(data)


def test_rehearsal_accepts_only_documented_reflect_parity_substitution():
    data = report()
    gate.validate_rehearsal(data)
    data["stages"][6].update(skipped=True, detail="post_apply_comparison_skipped: reflect_pre_apply_match is the evidence")
    data["stages"][5]["detail"] = "exit=0 expect=STAGING_DB_FROM_GENERATION=READY+CHAT_COPY_PARITY=MATCH+STAGING_DB_PENDING_APPLIED"
    gate.validate_rehearsal(data)
    data["stages"][5]["detail"] = "exit=0 expect=STAGING_DB_FROM_GENERATION=READY"
    with pytest.raises(gate.Refused, match="rehearsal_skipped"):
        gate.validate_rehearsal(data)


@pytest.mark.parametrize("hours", [25, -1])
def test_new_upload_does_not_make_old_or_future_rehearsal_current(hours):
    data = report()
    stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    data["stages"][0].update(started_utc=stamp, ended_utc=stamp)
    with pytest.raises(gate.Refused, match="rehearsal_report_stale"):
        gate.validate_rehearsal(data, maximum_age_hours=24)


def test_rehearsal_rejects_invalid_report_timestamp():
    data = report()
    data["stages"][0]["started_utc"] = "not-a-timestamp"
    with pytest.raises(gate.Refused, match="rehearsal_timestamp_invalid"):
        gate.validate_rehearsal(data, maximum_age_hours=24)


def test_signed_rehearsal_download_has_no_github_credential(monkeypatch, capsys):
    envelope, public_pem = signed_evidence()
    env = environment()
    env["REHEARSAL_PUBLIC_KEY_PEM"] = public_pem
    calls = []
    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        return 200, {}, json.dumps(envelope).encode()
    monkeypatch.setattr(gate, "request", fake_request)
    gate.Gate(env).rehearsal()
    assert calls == [(env["REHEARSAL_EVIDENCE_URL"], {"headers": {"Cache-Control": "no-cache"}})]
    assert "REHEARSAL_EVIDENCE=PASS" in capsys.readouterr().out


@pytest.mark.parametrize("options,reason", [
    ({"sha": "d" * 40}, "evidence_sha_mismatch"),
    ({"generation": "another-generation"}, "evidence_generation_mismatch"),
    ({"expired": True}, "evidence_expired"),
])
def test_gate_rehearsal_rejects_wrong_sha_generation_or_expiry(monkeypatch, options, reason):
    envelope, public_pem = signed_evidence(**options)
    env = environment()
    env["REHEARSAL_PUBLIC_KEY_PEM"] = public_pem
    monkeypatch.setattr(gate, "request", lambda *a, **kw: (200, {}, json.dumps(envelope).encode()))
    with pytest.raises(gate.Refused, match=reason):
        gate.Gate(env).rehearsal()


def test_gate_refuses_redirected_evidence_without_following(monkeypatch):
    _, public_pem = signed_evidence()
    env = environment()
    env["REHEARSAL_PUBLIC_KEY_PEM"] = public_pem
    calls = []
    monkeypatch.setattr(gate, "request", lambda *a, **kw: calls.append(a) or (302, {"Location": PRIVATE}, b""))
    with pytest.raises(gate.Refused, match="evidence_download_failed"):
        gate.Gate(env).rehearsal()
    assert len(calls) == 1


def test_prior_readonly_cannot_authorize_another_generation(monkeypatch):
    instance = gate.Gate(environment("switch"))
    monkeypatch.setattr(instance, "github", lambda path: run_record(display_title=f"chat-com2/readonly/{SHA}/other"))
    with pytest.raises(gate.Refused, match="readonly_run_required"):
        instance.prior_readonly()


@pytest.mark.parametrize("status,headers,body,reason", [
    (200, {}, b"{}", "probe_status_mismatch"),
    (503, {"X-Padiem-Front": "read_fallback_static"}, b"{}", "front_fallback_detected"),
    (503, {"cache-control": "no-store"}, b"maintenance", "response_json_invalid"),
    (503, {"cache-control": "no-store"}, b'{"error":{"code":"busy"}}', "freeze_unverified"),
    (503, {}, b'{"error":{"code":"maintenance"}}', "freeze_unverified"),
])
def test_freeze_requires_exact_maintenance_and_no_fallback(monkeypatch, status, headers, body, reason):
    monkeypatch.setattr(gate, "request", lambda *args, **kwargs: (status, headers, body))
    with pytest.raises(gate.Refused, match=reason):
        gate.Gate(environment()).probe(gate.ORIGIN, gate.FROZEN_PATHS[0], 503, maintenance=True)


def test_freeze_probe_checks_safe_mutation_before_write_effect_gets(monkeypatch):
    instance = gate.Gate(environment("readonly"))
    calls = []
    monkeypatch.setattr(instance, "probe", lambda *a, **kw: calls.append((a, kw)))
    instance.freeze_probes(gate.ORIGIN)
    assert calls[1] == ((gate.ORIGIN, "/health", 503), {"method": "POST", "maintenance": True})
    assert calls[2] == ((gate.ORIGIN, "/api/auth/status", 403), {})
    assert [args[1] for args, _ in calls[3:]] == list(gate.FROZEN_PATHS)


@pytest.mark.parametrize("flag", ["", "0", "false", "no", "off"])
def test_missing_or_disabled_legacy_freeze_is_refused(monkeypatch, flag):
    instance = gate.Gate(environment("readonly"))
    monkeypatch.setattr(instance, "bindings", lambda worker: {
        "PADIEM_CHAT_WRITE_FREEZE": flag,
        "PADIEM_CHAT_WRITE_FREEZE_PATHS": ",".join(gate.FROZEN_PATHS),
    })
    with pytest.raises(gate.Refused, match="legacy_freeze_unverified"):
        instance.legacy_freeze_config()


def test_missing_frozen_get_is_refused(monkeypatch):
    instance = gate.Gate(environment("readonly"))
    monkeypatch.setattr(instance, "bindings", lambda worker: {
        "PADIEM_CHAT_WRITE_FREEZE": "true",
        "PADIEM_CHAT_WRITE_FREEZE_PATHS": ",".join(gate.FROZEN_PATHS[:-1]),
    })
    with pytest.raises(gate.Refused, match="legacy_freeze_unverified"):
        instance.legacy_freeze_config()


def test_front_secret_metadata_logs_name_only(monkeypatch, capsys):
    instance = gate.Gate(environment())
    monkeypatch.setattr(instance, "bindings", lambda worker: {
        "FRONT_ORIGIN": gate.ORIGIN, "FALLBACK_MODE": "static", "COM2_CANONICAL": "off",
        "UNRELATED_PRIVATE_VAR": PRIVATE,
    })
    monkeypatch.setattr(instance, "cf", lambda path: [{"name": gate.SECRET_NAME, "type": "secret_text", "text": PRIVATE}])
    instance.front_config()
    output = capsys.readouterr().out
    assert gate.SECRET_NAME in output
    assert PRIVATE not in output


@pytest.mark.parametrize("route_config", [
    "routes = []", 'route = "chat.padiem.net/*"',
])
def test_explicit_route_management_is_refused_before_deploy(monkeypatch, tmp_path, route_config):
    front = tmp_path / "apps/padiem-chat-front"
    front.mkdir(parents=True)
    (front / "wrangler.toml").write_text(
        'name = "padiem-chat-front"\nworkers_dev = false\npreview_urls = false\n'
        + route_config + '\n[vars]\nFRONT_ORIGIN = "' + gate.ORIGIN + '"\n'
    )
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    with pytest.raises(gate.Refused, match="front_route_config_drift"):
        gate.Gate(environment()).front_config()


def test_command_failure_never_echoes_subprocess_output(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout=PRIVATE, stderr=PRIVATE))
    with pytest.raises(gate.Refused, match="command_failed") as error:
        gate.run_command(["synthetic"])
    assert PRIVATE not in str(error.value)
    assert PRIVATE not in capsys.readouterr().out


def test_api_error_body_never_leaks(monkeypatch, capsys):
    monkeypatch.setattr(gate, "request", lambda *a, **kw: (403, {}, PRIVATE.encode()))
    with pytest.raises(gate.Refused, match="cloudflare_http_failed") as error:
        gate.Gate(environment()).cf("/workers/domains")
    assert PRIVATE not in str(error.value)
    assert PRIVATE not in capsys.readouterr().out


def test_main_sanitizes_unexpected_exception_and_prints_only_rollback_guidance(monkeypatch, capsys):
    monkeypatch.setenv("MODE", "switch")
    def failed(self):
        raise RuntimeError(PRIVATE)
    monkeypatch.setattr(gate.Gate, "execute", failed)
    assert gate.main() == 2
    output = capsys.readouterr().out
    assert PRIVATE not in output
    assert "unexpected_failure" in output
    assert "ROLLBACK_GUIDANCE=" in output


def test_workflow_has_one_production_lock_without_mode_or_ref_suffix():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    group = workflow["concurrency"]["group"]
    assert "b62-production-code-deploy-gate-production" in group
    assert "inputs.mode" not in group and "github.ref" not in group
    assert workflow["concurrency"]["cancel-in-progress"] is False
    job = workflow["jobs"]["gate"]
    assert job["environment"] == "production"
    assert job["if"] == "github.event_name == 'workflow_dispatch'"
    steps = job["steps"]
    validation = steps[0]["run"]
    assert "refs/heads/main" in validation
    assert '"$TARGET_SHA" == "$GITHUB_SHA"' in validation
    assert "${MODE^^}_CHAT_COM2_${TARGET_SHA}" in validation
    assert "actions/checkout@" in steps[1]["uses"]
    assert steps[1]["with"]["persist-credentials"] is False
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}


def test_workflow_never_echoes_secrets_or_uses_automatic_rollback():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    steps = workflow["jobs"]["gate"]["steps"]
    scripts = "\n".join(step.get("run", "") for step in steps)
    assert "${{ secrets." not in scripts
    assert "set -x" not in scripts
    assert "echo $CLOUDFLARE" not in scripts
    assert "workflow run" not in scripts and "gh api" not in scripts
    failure = steps[-1]
    assert failure["if"] == "failure() && inputs.mode == 'switch'"
    assert all(line.strip().startswith("echo ") for line in failure["run"].splitlines() if line.strip())
    execution_env = next(step["env"] for step in steps if step.get("name") == "Execute one approved mode")
    assert gate.SECRET_NAME not in execution_env
