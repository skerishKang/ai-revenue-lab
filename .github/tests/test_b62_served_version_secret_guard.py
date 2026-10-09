from __future__ import annotations

"""#2411 network-free regressions for the served-version secret set guard.

Every fixture is a synthetic Cloudflare API payload. No network, no live
Cloudflare calls, and no real secret material: secret_text entries carry only
name/type metadata, mirroring what the version detail endpoint exposes.
"""

import contextlib
import importlib.util
import io
import json
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_served_version_secret_guard.py"
spec = importlib.util.spec_from_file_location("b62_served_version_secret_guard", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PRE_VERSION = "11111111-1111-1111-1111-111111111111"
POST_VERSION = "22222222-2222-2222-2222-222222222222"


def deployments(*entries):
    return {"success": True, "result": {"deployments": [{"versions": list(entries)}]}}


def served(version_id, percentage=100):
    return {"version_id": version_id, "percentage": percentage}


def version_detail(version_id, bindings_map):
    return {
        "success": True,
        "result": {
            "id": version_id,
            "resources": {"bindings": bindings_map},
        },
    }


def secret(name):
    return {"type": "secret_text"}


def plain(text):
    return {"type": "plain_text", "text": text}


def base_bindings_map():
    return {
        "ASSETS": {"type": "assets"},
        "PADIEM_CHAT_DB": {"type": "d1", "id": "db-id"},
        "PADIEM_CHAT_RUNTIME_MODE": plain("production"),
        "PADIEM_CHAT_QUOTA_SALT": secret("PADIEM_CHAT_QUOTA_SALT"),
        "P01_ENGINE_CREDENTIAL": secret("P01_ENGINE_CREDENTIAL"),
        "LEGACY_UNRELATED_SECRET": secret("LEGACY_UNRELATED_SECRET"),
    }


def expected_capture(version_id=PRE_VERSION, bindings=None):
    return mod.build_capture(version_id, bindings if bindings is not None else _entries(base_bindings_map()))


def _entries(bindings_map):
    return mod._binding_entries(bindings_map)


# --- pre/post served version resolution -------------------------------------


def test_resolve_served_version_id_single_full_traffic_version():
    payload = deployments(served(PRE_VERSION))
    assert mod.resolve_served_version_id(payload) == PRE_VERSION


def test_resolve_served_version_id_missing_version_fails_closed():
    with pytest.raises(mod.ServedVersionGuardError):
        mod.resolve_served_version_id(deployments({"percentage": 100}))
    with pytest.raises(mod.ServedVersionGuardError):
        mod.resolve_served_version_id(deployments(served("   ")))


def test_ambiguous_active_deployments_fail_closed():
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.resolve_served_version_id({"success": True, "result": {"deployments": []}})
    assert "ambiguous active deployment" in str(exc.value)


def test_first_deployment_is_the_active_one_when_history_is_returned():
    # Cloudflare documents the deployments endpoint as returning history whose
    # first entry is the latest deployment actively serving traffic.
    payload = {
        "success": True,
        "result": {
            "deployments": [
                {"versions": [served(PRE_VERSION)]},
                {"versions": [served(POST_VERSION)]},
            ]
        },
    }
    assert mod.resolve_served_version_id(payload) == PRE_VERSION


def test_non_object_first_deployment_fails_closed():
    payload = {"success": True, "result": {"deployments": ["not-an-object"]}}
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.resolve_served_version_id(payload)
    assert "ambiguous active deployment" in str(exc.value)


def test_partial_traffic_version_split_fails_closed():
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.resolve_served_version_id(deployments(served(PRE_VERSION, 50), served(POST_VERSION, 50)))
    assert "ambiguous active deployment" in str(exc.value)


def test_version_detail_must_match_served_version_id():
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.served_version_bindings(version_detail(POST_VERSION, base_bindings_map()), expected_version_id=PRE_VERSION)
    assert "does not match the served version id" in str(exc.value)


def test_version_detail_missing_resources_or_bindings_fails_closed():
    with pytest.raises(mod.ServedVersionGuardError):
        mod.served_version_bindings({"success": True, "result": {"id": PRE_VERSION}}, expected_version_id=PRE_VERSION)
    with pytest.raises(mod.ServedVersionGuardError):
        mod.served_version_bindings(
            {"success": True, "result": {"id": PRE_VERSION, "resources": {}}},
            expected_version_id=PRE_VERSION,
        )


# --- complete-set equality and explicit guards -------------------------------


def test_full_secret_set_equality_passes_for_identical_name_type_sets():
    bindings = _entries(base_bindings_map())
    mod.verify_secret_set(mod.secret_name_type_set(bindings), bindings)


def test_secret_set_equality_is_order_insensitive():
    bindings = _entries(base_bindings_map())
    expected = tuple(sorted(reversed(bindings and mod.secret_name_type_set(bindings))))
    mod.verify_secret_set(expected, bindings)


def test_quota_salt_explicit_guard():
    bindings = _entries(base_bindings_map())
    assert ("PADIEM_CHAT_QUOTA_SALT", "secret_text") in mod.secret_name_type_set(bindings)
    lost = [b for b in bindings if b["name"] != "PADIEM_CHAT_QUOTA_SALT"]
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.require_required_secrets(lost, stage="post-deploy")
    assert "PADIEM_CHAT_QUOTA_SALT" in str(exc.value)


def test_p01_explicit_guard():
    bindings = _entries(base_bindings_map())
    assert ("P01_ENGINE_CREDENTIAL", "secret_text") in mod.secret_name_type_set(bindings)
    lost = [b for b in bindings if b["name"] != "P01_ENGINE_CREDENTIAL"]
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.require_required_secrets(lost, stage="post-deploy")
    assert "P01_ENGINE_CREDENTIAL" in str(exc.value)


def test_p01_downgraded_to_plain_text_fails_closed():
    drifted = dict(base_bindings_map())
    drifted["P01_ENGINE_CREDENTIAL"] = plain("not-a-secret")
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.require_required_secrets(_entries(drifted), stage="post-deploy")
    assert "type drift" in str(exc.value)


def test_lost_unrelated_pre_existing_secret_fails_closed():
    bindings = _entries(base_bindings_map())
    expected = mod.secret_name_type_set(bindings)
    post = [b for b in bindings if b["name"] != "LEGACY_UNRELATED_SECRET"]
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.verify_secret_set(expected, post)
    assert "missing pre-existing secret: LEGACY_UNRELATED_SECRET" in str(exc.value)


def test_unrelated_secret_type_drift_fails_closed():
    bindings = _entries(base_bindings_map())
    expected = mod.secret_name_type_set(bindings)
    drifted = dict(base_bindings_map())
    drifted["LEGACY_UNRELATED_SECRET"] = plain("x")
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.verify_secret_set(expected, _entries(drifted))
    assert "type drift: LEGACY_UNRELATED_SECRET" in str(exc.value)


def test_unexpected_new_secret_in_served_version_fails_closed():
    bindings = _entries(base_bindings_map())
    expected = mod.secret_name_type_set(bindings)
    grown = dict(base_bindings_map())
    grown["SURPRISE_SECRET"] = secret("SURPRISE_SECRET")
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.verify_secret_set(expected, _entries(grown))
    assert "unexpected new secret: SURPRISE_SECRET" in str(exc.value)


def test_duplicate_binding_names_fail_closed():
    bindings = [
        {"name": "PADIEM_CHAT_QUOTA_SALT", "type": "secret_text"},
        {"name": "PADIEM_CHAT_QUOTA_SALT", "type": "secret_text"},
        {"name": "P01_ENGINE_CREDENTIAL", "type": "secret_text"},
    ]
    payload = {"success": True, "result": {"id": PRE_VERSION, "resources": {"bindings": bindings}}}
    with pytest.raises(mod.ServedVersionGuardError) as exc:
        mod.served_version_bindings(payload, expected_version_id=PRE_VERSION)
    assert "duplicate binding names" in str(exc.value)


def test_capture_rejects_entries_with_extra_fields():
    tampered = {
        "schema": mod.CAPTURE_SCHEMA,
        "version_id": PRE_VERSION,
        "secrets": [{"name": "X", "type": "secret_text", "text": "leaked"}],
    }
    with pytest.raises(mod.ServedVersionGuardError):
        mod.load_capture(tampered)


def test_capture_rejects_foreign_schema():
    with pytest.raises(mod.ServedVersionGuardError):
        mod.load_capture({"schema": "other/v1", "secrets": []})
    with pytest.raises(mod.ServedVersionGuardError):
        mod.load_capture({"success": True, "result": {"bindings": []}})


# --- CLI round trip and secret-content non-disclosure ------------------------


def _run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


def test_capture_and_verify_cli_round_trip_is_name_type_only():
    with tempfile.TemporaryDirectory() as workdir:
        work = Path(workdir)
        deployments_path = work / "deployments.json"
        detail_path = work / "detail.json"
        capture_path = work / "capture.json"
        deployments_path.write_text(json.dumps(deployments(served(PRE_VERSION))), encoding="utf-8")
        detail_path.write_text(json.dumps(version_detail(PRE_VERSION, base_bindings_map())), encoding="utf-8")
        code, out, err = _run_cli([
            "capture",
            "--deployments", str(deployments_path),
            "--version-detail", str(detail_path),
            "--output", str(capture_path),
        ])
        assert code == 0, err
        assert "PREDEPLOY_SERVED_VERSION_IDENTIFIED" not in out
        assert f"PREDEPLOY_SERVED_VERSION_ID={PRE_VERSION}" in out
        assert "PADIEM_CHAT_QUOTA_SALT=PRESENT:secret_text" in out
        assert "P01_ENGINE_CREDENTIAL=PRESENT:secret_text" in out
        capture = json.loads(capture_path.read_text(encoding="utf-8"))
        assert capture["schema"] == mod.CAPTURE_SCHEMA
        assert all(set(entry) == {"name", "type"} for entry in capture["secrets"])
        assert all("text" not in entry for entry in capture["secrets"])

        post_deployments = work / "deployments-after.json"
        post_detail = work / "detail-after.json"
        post_deployments.write_text(json.dumps(deployments(served(POST_VERSION))), encoding="utf-8")
        post_detail.write_text(json.dumps(version_detail(POST_VERSION, base_bindings_map())), encoding="utf-8")
        code, out, err = _run_cli([
            "verify",
            "--expected", str(capture_path),
            "--deployments", str(post_deployments),
            "--version-detail", str(post_detail),
        ])
        assert code == 0, err
        assert f"POSTDEPLOY_SERVED_VERSION_ID={POST_VERSION}" in out
        assert "SERVED_VERSION_SECRET_SET_EQUALITY=PASS" in out
        assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in out
        assert "SECRET_VALUES_READ=0" in out


def test_verify_cli_fails_closed_on_secret_loss():
    with tempfile.TemporaryDirectory() as workdir:
        work = Path(workdir)
        capture_path = work / "capture.json"
        capture_path.write_text(json.dumps(expected_capture()), encoding="utf-8")
        deployments_path = work / "deployments.json"
        deployments_path.write_text(json.dumps(deployments(served(POST_VERSION))), encoding="utf-8")
        shrunken = dict(base_bindings_map())
        shrunken.pop("LEGACY_UNRELATED_SECRET")
        detail_path = work / "detail.json"
        detail_path.write_text(json.dumps(version_detail(POST_VERSION, shrunken)), encoding="utf-8")
        code, out, err = _run_cli([
            "verify",
            "--expected", str(capture_path),
            "--deployments", str(deployments_path),
            "--version-detail", str(detail_path),
        ])
        assert code == 1
        assert "B62_SERVED_VERSION_SECRET_SET=FAIL" in err
        assert "missing pre-existing secret: LEGACY_UNRELATED_SECRET" in err
        assert "SECRET_VALUES_READ=0" in err


def test_cli_output_never_contains_secret_values_or_binding_text():
    with tempfile.TemporaryDirectory() as workdir:
        work = Path(workdir)
        deployments_path = work / "deployments.json"
        detail_path = work / "detail.json"
        capture_path = work / "capture.json"
        deployments_path.write_text(json.dumps(deployments(served(PRE_VERSION))), encoding="utf-8")
        secret_map = dict(base_bindings_map())
        secret_map["PADIEM_CHAT_PUBLIC_BASE_URL"] = plain("https://padiem-chat.charliekant.workers.dev")
        detail_path.write_text(json.dumps(version_detail(PRE_VERSION, secret_map)), encoding="utf-8")
        code, out, err = _run_cli([
            "capture",
            "--deployments", str(deployments_path),
            "--version-detail", str(detail_path),
            "--output", str(capture_path),
        ])
        assert code == 0, err
        combined = out + err + capture_path.read_text(encoding="utf-8")
        assert "https://padiem-chat.charliekant.workers.dev" not in combined
        assert "production" not in combined


def test_capture_cli_refuses_existing_output():
    with tempfile.TemporaryDirectory() as workdir:
        work = Path(workdir)
        deployments_path = work / "deployments.json"
        detail_path = work / "detail.json"
        capture_path = work / "capture.json"
        capture_path.write_text("{}", encoding="utf-8")
        deployments_path.write_text(json.dumps(deployments(served(PRE_VERSION))), encoding="utf-8")
        detail_path.write_text(json.dumps(version_detail(PRE_VERSION, base_bindings_map())), encoding="utf-8")
        code, _, err = _run_cli([
            "capture",
            "--deployments", str(deployments_path),
            "--version-detail", str(detail_path),
            "--output", str(capture_path),
        ])
        assert code == 1
        assert "already exists" in err


if __name__ == "__main__":
    import traceback

    tests = sorted(
        (name, fn) for name, fn in globals().items()
        if name.startswith("test_") and callable(fn)
    )
    failures = 0
    for name, fn in tests:
        try:
            fn()
        except Exception:
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    if failures:
        raise SystemExit(f"B62_SERVED_VERSION_SECRET_GUARD_TESTS=FAIL count={failures}")
    print(f"B62_SERVED_VERSION_SECRET_GUARD_TESTS=PASS cases={len(tests)}")


# #3748 / #3897: exact argv parity of the canonical B62 production GET-only
# served-lineage audit. All subprocesses use local synthetic IDs. This suite
# is already run by the PR-only B62 Production Deploy source-contract job.


B62_DEPLOY_GATE = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
LINEAGE_CLI = ROOT / ".github/scripts/cloudflare_served_version_lineage.py"


def _assert_3748_b62_production_argv_source(src: str) -> None:
    assert src.count('--active-version="${active}"') == 1
    assert src.count('--latest-version="${latest}"') == 1
    assert '--active-version "${active}"' not in src
    assert '--latest-version "${latest}"' not in src
    assert "cloudflare_served_version_lineage.py" in src
    assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION" in src
    assert "P01_ENGINE_WORKER: padiem-ai-engine" in src


def _run_3748_b62_production_lineage(*argv: str):
    import subprocess
    import sys
    return subprocess.run(
        [sys.executable, str(LINEAGE_CLI), *argv],
        capture_output=True, text=True, check=False, timeout=15,
    )


def test_3748_b62_production_argv_only_two_lineage_tokens_and_pr_boundary():
    source = B62_DEPLOY_GATE.read_text(encoding="utf-8")
    _assert_3748_b62_production_argv_source(source)
    assert '  pull_request:' in source
    assert '  workflow_dispatch:' in source
    assert '" .github/tests/test_b62_served_version_secret_guard.py "' not in source
    assert "python -m pytest .github/tests/test_b62_served_version_secret_guard.py -q" in source
    assert '"deploy_production_code"' in source
    assert "environment: production" in source
    assert "PRODUCTION_MUTATION=0" in source


def test_3748_b62_production_argv_real_lineage_both_leading_hyphen_pass():
    from cloudflare_served_version import is_safe_version_id
    assert is_safe_version_id("-canonical-live-version")
    run = _run_3748_b62_production_lineage(
        "--active-version=-canonical-live-version",
        "--latest-version=-canonical-live-version",
    )
    assert run.returncode == 0, run.stderr
    assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS" in run.stdout
    assert "SERVED_VERSION_LINEAGE_OUTCOME=PASS" in run.stdout
    assert "SERVED_VERSION_LINEAGE_HTTP_CALLS=0" in run.stdout
    assert "SERVED_VERSION_LINEAGE_MUTATION=0" in run.stdout
    assert "SERVED_VERSION_LINEAGE_SECRET_READ=0" in run.stdout


def test_3748_b62_production_argv_both_old_split_forms_rejected_by_real_argparse():
    for args in (
        ("--active-version", "-canonical-live-version",
         "--latest-version=-canonical-live-version"),
        ("--active-version=-canonical-live-version",
         "--latest-version", "-canonical-live-version"),
    ):
        run = _run_3748_b62_production_lineage(*args)
        assert run.returncode == 2, run.stderr
        assert "expected one argument" in run.stderr
        assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS" not in run.stdout


def test_3748_b62_production_argv_real_lineage_mismatch_and_unsafe_refused():
    mismatch = _run_3748_b62_production_lineage(
        "--active-version=-canonical-live-version",
        "--latest-version=-different-version",
    )
    assert mismatch.returncode == 1, mismatch.stderr
    assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION=FAIL" in mismatch.stdout
    assert "SERVED_VERSION_LINEAGE_REASON=different" in mismatch.stdout
    unsafe = "unsafe latest with spaces"
    rejected = _run_3748_b62_production_lineage(
        "--active-version=-canonical-live-version",
        "--latest-version=" + unsafe,
    )
    assert rejected.returncode == 2, rejected.stderr
    assert "SERVED_VERSION_LINEAGE_OUTCOME=FAIL_CLOSED" in rejected.stdout
    assert unsafe not in rejected.stdout + rejected.stderr
    assert "SERVED_VERSION_LINEAGE_SECRET_READ=0" in rejected.stdout


def test_3748_b62_production_argv_two_independent_mutations_red_and_bytes_preserved():
    original = B62_DEPLOY_GATE.read_bytes()
    source = original.decode("utf-8")
    _assert_3748_b62_production_argv_source(source)
    pairs = (
        ('--active-version="${active}"', '--active-version "${active}"'),
        ('--latest-version="${latest}"', '--latest-version "${latest}"'),
    )
    caught = 0
    for good, bad in pairs:
        mutant = source.replace(good, bad, 1)
        assert mutant != source
        try:
            _assert_3748_b62_production_argv_source(mutant)
        except AssertionError:
            caught += 1
        else:
            raise AssertionError("old CLI split argv mutation was accepted")
    assert caught == 2
    assert B62_DEPLOY_GATE.read_bytes() == original
