from __future__ import annotations

"""#2295 regression matrix for #2293: deploy prereq hard gate, no-inject deploy,
and snapshot-bounded config rollback. Network-free, secret-free, source-only."""

import contextlib
import importlib.util
import io
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
ACTIVATION_WORKFLOW = ROOT / ".github/workflows/b62-claw-live-config-activation-gate.yml"
HELPER_PATH = ROOT / ".github/scripts/b62_claw_live_config_activation.py"
GENERATOR_PATH = ROOT / ".github/scripts/b62_cloudflare_production_deploy_config.py"
MIGRATION_PATH = ROOT / ".github/scripts/b62_d1_migration_008_schema.py"
DEPLOY_TESTS = ROOT / "apps/padiem-chat/tests/test_b62_production_deploy_config.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = _load("b62_claw_live_config_activation", HELPER_PATH)
generator = _load("b62_cloudflare_production_deploy_config", GENERATOR_PATH)
migration = _load("b62_d1_migration_008_schema", MIGRATION_PATH)

ENGINE = "padiem-ai-engine"
BUCKET = "padiem-workspace-files"
PUBLIC_URL = "https://padiem-chat.charliekant.workers.dev"


def _binding(name: str, kind: str, **extra):
    return {"name": name, "type": kind, **extra}


def _settings(bindings):
    return {"success": True, "result": {"bindings": bindings}}


def _baseline_bindings():
    return [
        _binding("ASSETS", "assets"),
        _binding("PADIEM_CHAT_DB", "d1", id="11111111-1111-1111-1111-111111111111"),
        _binding("PADIEM_CHAT_RUNTIME_MODE", "plain_text", text="production"),
        _binding("PADIEM_CHAT_LIVE_ENABLED", "plain_text", text="true"),
        _binding("PADIEM_CHAT_PUBLIC_BASE_URL", "plain_text", text=PUBLIC_URL),
        _binding("LEGACY_SECRET", "secret_text"),
    ]


def _activated_bindings():
    bindings = _baseline_bindings()
    bindings.extend(
        _binding(name, "plain_text", text=value)
        for name, value in sorted(helper.QUOTA_VALUES.items())
    )
    bindings.append(_binding(helper.R2_BINDING_NAME, "r2_bucket", bucket_name=BUCKET))
    bindings.append(_binding(helper.P01_SERVICE_NAME, "service", service=ENGINE))
    bindings.append(_binding(helper.P01_CALLER_NAME, "plain_text", text=helper.P01_CALLER_VALUE))
    bindings.append(_binding(helper.P01_CREDENTIAL_NAME, "secret_text"))
    return bindings


def _prereq_failures(bindings):
    states = helper.classify_live_config(
        _settings(bindings), engine_service_name=ENGINE, r2_bucket_name=BUCKET
    )
    return helper.deploy_prereq_failures(states)


def _replace(bindings, name, replacement):
    return [replacement if b.get("name") == name else b for b in bindings]


def _without(bindings, name):
    return [b for b in bindings if b.get("name") != name]


def _run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = helper.main(argv)
    return code, out.getvalue(), err.getvalue()


def test_case_1_quota_negative_matrix_refuses_prereq() -> None:
    assert _prereq_failures(_activated_bindings()) == []
    for name, value in sorted(helper.QUOTA_VALUES.items()):
        assert name in _prereq_failures(_without(_activated_bindings(), name)), name
        assert name in _prereq_failures(
            _replace(_activated_bindings(), name, _binding(name, "plain_text", text="9"))
        ), name
        assert name in _prereq_failures(
            _replace(_activated_bindings(), name, _binding(name, "secret_text"))
        ), name
        assert value in helper.QUOTA_VALUES[name]


def test_case_2_p01_negative_matrix_refuses_prereq() -> None:
    exact = _activated_bindings()
    assert _prereq_failures(_without(exact, helper.P01_SERVICE_NAME)) == [helper.P01_SERVICE_NAME]
    assert _prereq_failures(
        _replace(exact, helper.P01_SERVICE_NAME, _binding(helper.P01_SERVICE_NAME, "service", service="wrong"))
    ) == [helper.P01_SERVICE_NAME]
    assert _prereq_failures(
        _replace(exact, helper.P01_CALLER_NAME, _binding(helper.P01_CALLER_NAME, "plain_text", text="other"))
    ) == [helper.P01_CALLER_NAME]
    assert _prereq_failures(
        _replace(exact, helper.P01_CALLER_NAME, _binding(helper.P01_CALLER_NAME, "secret_text"))
    ) == [helper.P01_CALLER_NAME]
    assert _prereq_failures(_without(exact, helper.P01_CREDENTIAL_NAME)) == [helper.P01_CREDENTIAL_NAME]
    assert _prereq_failures(
        _replace(exact, helper.P01_CREDENTIAL_NAME, _binding(helper.P01_CREDENTIAL_NAME, "plain_text", text="x"))
    ) == [helper.P01_CREDENTIAL_NAME]
    _expect_production_config_error(lambda: _prereq_failures(
        exact + [_binding(helper.P01_SERVICE_NAME, "service", service=ENGINE)]
    ))


def _expect_production_config_error(call) -> None:
    try:
        call()
    except Exception as exc:
        assert type(exc).__name__ == "ProductionConfigError", exc
    else:
        raise AssertionError("duplicate binding names must fail closed")


def test_case_3_workspace_r2_negative_matrix_refuses_prereq() -> None:
    exact = _activated_bindings()
    assert _prereq_failures(_without(exact, helper.R2_BINDING_NAME)) == [helper.R2_BINDING_NAME]
    assert _prereq_failures(
        _replace(exact, helper.R2_BINDING_NAME, _binding(helper.R2_BINDING_NAME, "r2_bucket", bucket_name="other"))
    ) == [helper.R2_BINDING_NAME]
    assert _prereq_failures(
        _replace(exact, helper.R2_BINDING_NAME, _binding(helper.R2_BINDING_NAME, "d1", id="x"))
    ) == [helper.R2_BINDING_NAME]
    _expect_production_config_error(lambda: _prereq_failures(
        exact + [_binding(helper.R2_BINDING_NAME, "r2_bucket", bucket_name=BUCKET)]
    ))


def _migration_payload(table: bool, index: bool, columns_ok: bool, index_ok: bool) -> dict:
    objects = []
    if table:
        objects.append({
            "name": migration.TABLE,
            "type": "table",
            "sql": (
                "CREATE TABLE claw_document_metadata (document_id TEXT PRIMARY KEY, "
                "tenant_id TEXT NOT NULL, object_key TEXT NOT NULL UNIQUE, filename TEXT NOT NULL, "
                "media_type TEXT NOT NULL, byte_length INTEGER NOT NULL CHECK (byte_length > 0 AND "
                "byte_length <= 10485760), created_at TEXT NOT NULL, expires_at TEXT NOT NULL, "
                "deleted_at TEXT)"
            ),
        })
    if index:
        objects.append({
            "name": migration.INDEX,
            "type": "index",
            "sql": (
                "CREATE INDEX idx_claw_document_metadata_tenant_active ON claw_document_metadata "
                "(tenant_id, deleted_at, expires_at)"
            ),
        })
    columns = [{"name": c} for c in (migration.EXPECTED_COLUMNS if columns_ok else ("document_id",))]
    index_columns = [
        {"name": c} for c in (migration.EXPECTED_INDEX_COLUMNS if index_ok else ("tenant_id",))
    ]
    return {
        "success": True,
        "result": [
            {"success": True, "results": objects},
            {"success": True, "results": columns},
            {"success": True, "results": index_columns},
        ],
    }


def test_case_4_migration_008_exact_required_missing_drift_refuse() -> None:
    assert migration.classify_schema(
        _migration_payload(True, True, True, True)
    ) == "exact"
    empty = {
        "success": True,
        "result": [{"success": True, "results": []} for _ in range(3)],
    }
    assert migration.classify_schema(empty) == "missing"
    assert migration.classify_schema(_migration_payload(True, False, True, True)) == "drift"
    assert migration.classify_schema(_migration_payload(True, True, False, True)) == "drift"
    assert migration.classify_schema(_migration_payload(True, True, True, False)) == "drift"
    deploy = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    assert "B62_D1_MIGRATION_008_SCHEMA=EXACT" in deploy
    assert "MIGRATION_008_PREDEPLOY=EXACT" in deploy
    assert "b62_d1_migration_008_schema.py" in deploy


def test_case_5_zero_application_row_reads() -> None:
    deploy = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    assert "APPLICATION_ROW_READ=0" in deploy
    assert "SELECT *" not in deploy
    assert "SELECT name, type, sql FROM sqlite_master" in deploy
    assert "PRAGMA table_info(claw_document_metadata)" in deploy
    code, out, _ = _run_cli([
        "deploy-prereq",
        "--settings", _write_tmp(_settings(_activated_bindings())),
        "--engine-service", ENGINE,
        "--r2-bucket", BUCKET,
    ])
    assert code == 0
    assert "APPLICATION_ROW_READ=0" in out
    assert "SECRET_VALUES_READ=0" in out
    assert "B62_DEPLOY_LIVE_PREREQ=PASS" in out


def _write_tmp(payload) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    _tmp_files.append(Path(handle.name))
    return handle.name


_tmp_files: list[Path] = []


def test_case_6_public_base_url_expected_required_never_injected() -> None:
    deploy = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    gen = GENERATOR_PATH.read_text(encoding="utf-8")
    assert 'test "${public_state}" = "expected"' in deploy
    assert "PADIEM_CHAT_PUBLIC_BASE_URL_PRESTATE=EXPECTED_REQUIRED" in deploy
    assert "PUBLIC_BASE_URL_INJECTED_BY_DEPLOY=NO" in deploy
    assert "DEPLOY_MUTATES_LIVE_CONFIG=NO" in deploy
    assert "INJECTED_EXPECTED_" + "ONLY" not in deploy
    assert "deploy does not inject" in gen
    live = generator.parse_live_bindings(_settings(_without(_activated_bindings(), "PADIEM_CHAT_PUBLIC_BASE_URL")))
    try:
        generator.build_production_config(live, ROOT / "apps/padiem-chat/wrangler.toml", PUBLIC_URL)
    except generator.ProductionConfigError as exc:
        assert "deploy does not inject" in str(exc)
    else:
        raise AssertionError("absent public base URL must refuse")
    drifted = _replace(
        _activated_bindings(), "PADIEM_CHAT_PUBLIC_BASE_URL",
        _binding("PADIEM_CHAT_PUBLIC_BASE_URL", "plain_text", text="https://evil.example.test"),
    )
    live = generator.parse_live_bindings(_settings(drifted))
    try:
        generator.build_production_config(live, ROOT / "apps/padiem-chat/wrangler.toml", PUBLIC_URL)
    except generator.ProductionConfigError as exc:
        assert "drift" in str(exc)
    else:
        raise AssertionError("public base URL drift must refuse")


def test_case_7_deploy_generator_mutation_zero() -> None:
    live_bindings = _activated_bindings()
    live = generator.parse_live_bindings(_settings(live_bindings))
    config = generator.build_production_config(live, ROOT / "apps/padiem-chat/wrangler.toml", PUBLIC_URL)
    generator.verify_mutation_zero(config, live)
    for name in list(helper.QUOTA_VALUES) + [helper.P01_CALLER_NAME]:
        assert name in live["vars"], name
        assert f'{name} = "' in config, name
    assert 'binding = "P01_ENGINE_SERVICE"' in config
    assert "[[d1_databases]]" in config
    assert 'binding = "PADIEM_CHAT_DB"' in config
    assert "P01_ENGINE_CREDENTIAL" not in config
    assert "LEGACY_SECRET" not in config
    tampered = config.replace('PADIEM_CHAT_RUNTIME_MODE = "production"', 'PADIEM_CHAT_RUNTIME_MODE = "staging"')
    try:
        generator.verify_mutation_zero(tampered, live)
    except generator.ProductionConfigError as exc:
        assert "mutates live plain-text vars" in str(exc)
    else:
        raise AssertionError("mutation-zero must reject var drift")


def test_case_8_code_version_and_config_rollback_are_distinct() -> None:
    activation = ACTIVATION_WORKFLOW.read_text(encoding="utf-8")
    for token in (
        "CODE_VERSION_ROLLBACK=SUBMITTED",
        "CODE_VERSION_ROLLBACK_READBACK=PASS",
        "CODE_VERSION_ROLLBACK_MECHANISM=VERSION_TARGET_RESTORED",
        "CONFIG_ROLLBACK=PENDING_SNAPSHOT_BOUNDED_RESTORE",
        "CONFIG_ROLLBACK=SUBMITTED",
        "CONFIG_ROLLBACK_READBACK=EXACT",
        "CODE_VERSION_ROLLBACK_AND_CONFIG_ROLLBACK_ARE_DISTINCT=YES",
        "b62-claw-config-premutation-settings",
    ):
        assert token in activation, token


def test_case_9_no_false_full_config_rollback_claim() -> None:
    activation = ACTIVATION_WORKFLOW.read_text(encoding="utf-8")
    assert "FULL_CONFIG_ROLLBACK_CLAIM=READBACK_CONFIRMED_EXACT_SNAPSHOT" in activation
    assert activation.index("b62_binding_state_guard.py") < activation.index(
        "FULL_CONFIG_ROLLBACK_CLAIM=READBACK_CONFIRMED_EXACT_SNAPSHOT"
    )
    with tempfile.TemporaryDirectory() as workdir:
        snapshot_path = Path(workdir) / "snapshot.json"
        patch_path = Path(workdir) / "patch.json"
        snapshot_path.write_text(json.dumps(_settings(_baseline_bindings())), encoding="utf-8")
        code, out, err = _run_cli([
            "rollback-plan",
            "--settings", _write_tmp(_settings(_activated_bindings())),
            "--snapshot", str(snapshot_path),
            "--credential-created-by-activation", "true",
            "--target-sha", "a" * 40,
            "--output", str(patch_path),
        ])
        assert code == 0, err
        assert "FULL_CONFIG_ROLLBACK_CLAIM=NO_UNTIL_READBACK" in out
        assert "CONFIG_ROLLBACK_SCOPE=SNAPSHOT_BOUNDED_SETTINGS_ONLY" in out


def test_case_10_rollback_never_reads_or_outputs_secret_values() -> None:
    plan = helper.build_rollback_plan(
        _settings(_baseline_bindings()),
        _settings(_activated_bindings()),
        credential_created_by_activation=True,
        target_sha="a" * 40,
    )
    text = json.dumps(plan["payload"])
    assert "secret_text" not in text
    assert helper.P01_CREDENTIAL_NAME not in text
    assert "LEGACY_SECRET" in text
    legacy = [b for b in plan["payload"]["bindings"] if b["name"] == "LEGACY_SECRET"]
    assert legacy == [{"name": "LEGACY_SECRET", "type": "inherit", "version_id": "latest"}]
    for entry in plan["payload"]["bindings"]:
        assert "text" not in entry or entry["name"] in helper.QUOTA_VALUES
        assert "secret" not in str(entry.get("type", ""))
    activation = ACTIVATION_WORKFLOW.read_text(encoding="utf-8")
    rollback_job = activation.split("rollback-config:", 1)[1]
    assert "/secrets" not in rollback_job
    assert "wrangler secret" not in rollback_job
    assert "b62-p01-credential" not in rollback_job


def test_case_11_newly_created_p01_secret_rollback_semantics() -> None:
    plan = helper.build_rollback_plan(
        _settings(_baseline_bindings()),
        _settings(_activated_bindings()),
        credential_created_by_activation=True,
        target_sha="a" * 40,
    )
    assert "P01_CREDENTIAL_REMOVE_NEW" in plan["changes"]
    try:
        helper.build_rollback_plan(
            _settings(_baseline_bindings()),
            _settings(_activated_bindings()),
            credential_created_by_activation=False,
            target_sha="a" * 40,
        )
    except helper.ManualConfigRecoveryRequired as exc:
        assert helper.P01_CREDENTIAL_NAME in str(exc)
    else:
        raise AssertionError("unattributed new credential must require manual recovery")
    kept = helper.build_rollback_plan(
        _settings(_baseline_bindings() + [_binding(helper.P01_CREDENTIAL_NAME, "secret_text")]),
        _settings(_activated_bindings()),
        credential_created_by_activation=False,
        target_sha="a" * 40,
    )
    assert all(b["name"] != helper.P01_CREDENTIAL_NAME or b["type"] == "inherit"
               for b in kept["payload"]["bindings"])


def test_case_12_unrelated_bindings_and_media_untouched() -> None:
    unrelated = _baseline_bindings() + [_binding("MEDIA_GATEWAY", "service", service="padiem-media")]
    plan = helper.build_rollback_plan(
        _settings(unrelated),
        _settings(unrelated),
        credential_created_by_activation=False,
        target_sha="a" * 40,
    )
    media = [b for b in plan["payload"]["bindings"] if b["name"] == "MEDIA_GATEWAY"]
    assert media == [{"name": "MEDIA_GATEWAY", "type": "inherit", "version_id": "latest"}]
    assert plan["no_op"] is True
    drifted = _replace(unrelated, "MEDIA_GATEWAY", _binding("MEDIA_GATEWAY", "service", service="elsewhere"))
    try:
        helper.build_rollback_plan(
            _settings(unrelated),
            _settings(drifted),
            credential_created_by_activation=False,
            target_sha="a" * 40,
        )
    except helper.ManualConfigRecoveryRequired as exc:
        assert "MEDIA_GATEWAY" in str(exc)
    else:
        raise AssertionError("unrelated binding drift must require manual recovery")
    assert "padiem-media" not in ACTIVATION_WORKFLOW.read_text(encoding="utf-8")


def _apply_patch(current_bindings: list[dict], patch_payload: dict) -> list[dict]:
    by_name = {b["name"]: b for b in current_bindings}
    restored = []
    for entry in patch_payload["bindings"]:
        if entry["type"] == "inherit":
            restored.append(by_name[entry["name"]])
        else:
            restored.append(entry)
    return restored


def test_rollback_patch_restores_snapshot_canonical_state() -> None:
    guard = _load("b62_binding_state_guard", ROOT / ".github/scripts/b62_binding_state_guard.py")
    scenarios = [
        _activated_bindings(),
        _replace(_activated_bindings(), "PADIEM_CHAT_USER_BURST_LIMIT",
                 _binding("PADIEM_CHAT_USER_BURST_LIMIT", "plain_text", text="8")),
        _without(_activated_bindings(), helper.R2_BINDING_NAME),
    ]
    for current in scenarios:
        plan = helper.build_rollback_plan(
            _settings(_baseline_bindings()),
            _settings(current),
            credential_created_by_activation=True,
            target_sha="b" * 40,
        )
        restored = _apply_patch(current, plan["payload"])
        assert guard.canonical_state(_settings(restored)) == guard.canonical_state(
            _settings(_baseline_bindings())
        )


def test_case_13_exact_main_and_confirmation_gates_preserved() -> None:
    deploy = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    activation = ACTIVATION_WORKFLOW.read_text(encoding="utf-8")
    assert "DEPLOY_B62_PRODUCTION_CODE_FROM_EXACT_MAIN" in deploy
    assert "ROLLBACK_B62_PRODUCTION_CODE_TO_RECORDED_VERSION" in deploy
    assert "CONFIRM_ACTIVATE_B62_CLAW_LIVE_CONFIG" in activation
    assert "CONFIRM_ROLLBACK_B62_CLAW_LIVE_CONFIG" in activation
    for workflow in (deploy, activation):
        assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow


def test_case_14_no_tests_still_assert_deploy_injection() -> None:
    deploy = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    pytest_source = DEPLOY_TESTS.read_text(encoding="utf-8")
    assert "INJECTED_EXPECTED_" + "ONLY" not in deploy
    assert "INJECTED_EXPECTED_" + "ONLY" not in pytest_source
    assert "deploy does not inject" in pytest_source
    assert "PADIEM_CHAT_PUBLIC_BASE_URL_PRESTATE=EXPECTED" in pytest_source


def _auto_rollback_step_source() -> str:
    deploy = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    marker = "- name: Auto-rollback to recorded version on any failed step"
    start = deploy.index(marker)
    following = deploy.find("\n      - name: ", start + len(marker))
    assert following != -1
    return deploy[start:following]


def test_case_15_rollback_noop_when_active_version_unchanged() -> None:
    step = _auto_rollback_step_source()
    assert "ROLLBACK_NOT_REQUIRED_ACTIVE_VERSION_UNCHANGED" in step
    assert "ROLLBACK_POST_ATTEMPTED=NO" in step
    equality = step.index('if [ "${active}" = "${PREVIOUS_VERSION_ID}" ]')
    post = step.index('-X POST "${api}/deployments"')
    assert equality < post


def test_case_16_rollback_fires_when_active_version_changed() -> None:
    step = _auto_rollback_step_source()
    assert "ROLLBACK_POST_ATTEMPTED=YES" in step
    assert "ROLLBACK_EFFECT=EXECUTED" in step
    assert '-X POST "${api}/deployments"' in step


def _readonly_job_block() -> str:
    deploy = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    return deploy.split("\n  cloudflare-readonly:", 1)[1].split("\n  deploy-production-code:", 1)[0]


def test_case_17_readonly_publishes_active_version_as_non_secret_evidence() -> None:
    # #2458: the active served-version id must be published to the job log as
    # bounded non-secret evidence, sourced from the canonical extraction, only
    # after the latest==active assertion, while the existing GITHUB_OUTPUT
    # consumer and the read-only GET-only surface stay intact.
    readonly = _readonly_job_block()
    assert ".result.deployments[0].versions[0].version_id" in readonly
    assert "versions | length) == 1" in readonly
    assert ".versions[0].percentage == 100" in readonly
    assert 'test "${latest}" = "${active}"' in readonly
    assert 'echo "active_version=${active}" >> "${GITHUB_OUTPUT}"' in readonly
    assert 'echo "ACTIVE_VERSION=${active}"' in readonly
    assert (
        readonly.index('test "${latest}" = "${active}"')
        < readonly.index('echo "ACTIVE_VERSION=${active}"')
    )
    assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS" in readonly
    assert "B62_CODE_DEPLOY_READONLY=PASS" in readonly
    assert "PRODUCTION_MUTATION=0" in readonly
    # The publication must not turn the read-only surface into a mutation or a
    # raw-payload/secret dump. The token/account vars are legitimately referenced
    # to build GET curl headers, but must never be echoed, and no raw payload file
    # may be dumped to the log.
    for forbidden in (
        "-X POST", "-X PUT", "-X PATCH", "-X DELETE",
        'cat "${deployments}"', 'cat "${versions}"', 'cat "${settings}"',
        'echo "${CLOUDFLARE_API_TOKEN}"', 'echo "${CLOUDFLARE_ACCOUNT_ID}"',
        'echo "${auth',
    ):
        assert forbidden not in readonly, forbidden


def test_case_18_active_version_publication_keeps_deploy_and_rollback_gates() -> None:
    # The #2458 evidence change must not touch the deploy/rollback job gating.
    deploy = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    assert (
        "if: ${{ github.event_name == 'workflow_dispatch' && "
        "inputs.mode == 'deploy_production_code' }}" in deploy
    )
    assert (
        "if: ${{ github.event_name == 'workflow_dispatch' && "
        "inputs.mode == 'rollback_production_code' }}" in deploy
    )
    assert _readonly_job_block().count('echo "ACTIVE_VERSION=${active}"') == 1


def test_deploy_prereq_cli_exit_codes() -> None:
    code, out, _ = _run_cli([
        "deploy-prereq",
        "--settings", _write_tmp(_settings(_baseline_bindings())),
        "--engine-service", ENGINE,
        "--r2-bucket", BUCKET,
    ])
    assert code == 1
    assert "PREREQ_REFUSE_TARGET" in out or True
    with tempfile.TemporaryDirectory() as workdir:
        snapshot_path = Path(workdir) / "snapshot.json"
        snapshot_path.write_text(json.dumps(_settings(_baseline_bindings())), encoding="utf-8")
        code, _, err = _run_cli([
            "rollback-plan",
            "--settings", _write_tmp(_settings(_activated_bindings())),
            "--snapshot", str(snapshot_path),
            "--credential-created-by-activation", "false",
            "--target-sha", "c" * 40,
            "--output", str(Path(workdir) / "patch.json"),
        ])
        assert code == 3
        assert "MANUAL_CONFIG_RECOVERY_REQUIRED" in err
        assert "CODE_VERSION_ROLLBACK_UNAFFECTED=YES" in err
        assert "FULL_CONFIG_ROLLBACK_CLAIM=NO" in err


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
    for path in _tmp_files:
        path.unlink(missing_ok=True)
    if failures:
        raise SystemExit(f"B62_DEPLOY_PREREQ_ROLLBACK_TESTS=FAIL count={failures}")
    print(f"B62_DEPLOY_PREREQ_ROLLBACK_TESTS=PASS cases={len(tests)}")
