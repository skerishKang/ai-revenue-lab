"""Source contract tests for the A6 read-only attestation (#1971 A6-S2B).

Network-free and dispatch-free by construction: these tests only read the
workflow text and its parsed YAML. They pin the two properties that make the
attestation safe to exist in the repository — a pull request or a main push can
never perform a Production read, and the live read that an owner may dispatch
stays mutation-free, schema-name-only and fail-honest about a missing migration.

They deliberately assert on parsed trigger/job structure rather than on loose
substring presence, so a reworded comment cannot silently open the gate.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-engine-a6-readonly-attestation.yml"
GUARD = ROOT / ".github/scripts/b54_engine_served_version_guard.py"
WRANGLER = ROOT / "apps/padiem-ai-engine/wrangler.toml"

CONFIRMATION = "ATTEST_B54_ENGINE_A6_READONLY"
LIVE_JOB = "served-a6-readonly"
SCHEMA_JOB_STEP = "Observe A6 durable schema objects by name only"
SCHEMA_QUERY = "SELECT name FROM sqlite_master WHERE type IN ('table','index')"

IMAGE_TABLE = "padiem_engine_attachment_images"
DOCUMENT_TABLE = "padiem_engine_document_bytes"
DOCUMENT_INDEXES = (
    "idx_padiem_engine_document_bytes_expires_at",
    "idx_padiem_engine_document_bytes_scope",
)
COMPLETE_SCHEMA = [IMAGE_TABLE, DOCUMENT_TABLE, *DOCUMENT_INDEXES]


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _doc() -> dict:
    data = yaml.safe_load(_text())
    return data


def _triggers() -> dict:
    data = _doc()
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return trigger


def _live_job() -> dict:
    return _doc()["jobs"][LIVE_JOB]


def _live_schema_script() -> str:
    """Return the schema reader the live job embeds, verbatim.

    Executing that script instead of re-implementing its logic is what turns the
    fail-honest branches below into evidence rather than prose.
    """
    step = next(s for s in _live_job()["steps"] if s["name"] == SCHEMA_JOB_STEP)
    lines = step["run"].splitlines()
    start = next(i for i, line in enumerate(lines) if line.endswith("<<'PY'")) + 1
    end = next(i for i in range(start, len(lines)) if lines[i] == "PY")
    return "\n".join(lines[start:end])


def _run_live_schema_read(names, *, rows=None, envelope=True) -> tuple[str, int]:
    """Run the live job's reader against a synthetic, network-free D1 payload."""
    if rows is None:
        rows = [{"name": name} for name in names]
    payload = [{"success": True, "meta": {}, "results": rows}] if envelope else rows
    with tempfile.TemporaryDirectory() as tmp:
        captured = Path(tmp) / "engine-a6-schema.json"
        captured.write_text(json.dumps(payload), encoding="utf-8")
        env = dict(os.environ, A6_SCHEMA_JSON=str(captured))
        proc = subprocess.run(
            [sys.executable, "-c", _live_schema_script()],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp,
        )
    return proc.stdout + proc.stderr, proc.returncode


def test_live_schema_reader_is_local_only() -> None:
    """The reader parses a file; it holds no credential or network surface.

    This is the precondition for the whole executable group below: the exact
    Production-facing branch can be run in a network-free contract test.
    """
    script = _live_schema_script()
    assert set(re.findall(r"^(?:import|from)\s+(\w+)", script, re.MULTILINE)) == {
        "json",
        "os",
        "pathlib",
    }
    for shape in ("subprocess", "requests", "fetch", "curl", "wrangler", "token"):
        assert shape not in script.lower(), shape


def test_source_contract_reports_0006_as_unproven_at_source() -> None:
    """A source-only job must emit the honest marker, not merely list it.

    A required-marker list can always satisfy itself by containing its own
    string, so the assertion is scoped to the emitted lines of the job that
    runs without a Production read.
    """
    source_runs = "\n".join(
        step.get("run", "") for step in _doc()["jobs"]["source-contract"]["steps"]
    )
    assert 'print("MIGRATION_0006_PRODUCTION_APPLIED=UNKNOWN_UNPROVEN_AT_SOURCE")' in source_runs
    # Nothing in the workflow may claim the production apply as settled.
    for body in (source_runs, "\n".join(s.get("run", "") for s in _live_job()["steps"])):
        assert "MIGRATION_0006_PRODUCTION_APPLIED=YES" not in body


def test_live_schema_read_passes_only_when_all_objects_exist() -> None:
    out, code = _run_live_schema_read(COMPLETE_SCHEMA)
    assert code == 0, out
    assert "A6_IMAGE_TABLE_PRESENT=YES" in out
    assert "A6_DOCUMENT_TABLE_PRESENT=YES" in out
    assert "A6_DOCUMENT_INDEXES_PRESENT=YES" in out
    assert "IMAGE_SCHEMA_STATE=PRESENT" in out
    assert "DOCUMENT_SCHEMA_STATE=PRESENT" in out
    assert "A6_D1_SCHEMA_STATE=PRESENT" in out
    assert "A6_STORAGE_SCHEMA_VALIDATED=YES" in out
    # Even a full pass is readiness evidence, never an activation claim.
    assert "MIGRATION_0006_PRODUCTION_APPLIED=YES" not in out
    assert "ABSENT" not in out


def test_live_schema_read_fails_closed_when_document_schema_absent() -> None:
    out, code = _run_live_schema_read([IMAGE_TABLE])
    assert code != 0
    assert "A6_DOCUMENT_TABLE_PRESENT=NO" in out
    assert "DOCUMENT_SCHEMA_STATE=ABSENT" in out
    assert "A6_D1_SCHEMA_STATE=ABSENT" in out
    assert "MIGRATION_0006_PRODUCTION_APPLIED=NO" in out
    # absence must not be rescued into a success verdict
    assert "A6_D1_SCHEMA_STATE=PRESENT" not in out
    assert "A6_STORAGE_SCHEMA_VALIDATED=YES" not in out


def test_live_schema_read_fails_closed_on_partial_document_schema() -> None:
    """Table without its retention/scope indexes is not a provisioned store."""
    out, code = _run_live_schema_read([IMAGE_TABLE, DOCUMENT_TABLE, DOCUMENT_INDEXES[0]])
    assert code != 0
    assert "A6_DOCUMENT_TABLE_PRESENT=YES" in out
    assert "A6_DOCUMENT_INDEXES_PRESENT=NO" in out
    assert "DOCUMENT_SCHEMA_STATE=ABSENT" in out
    assert "A6_D1_SCHEMA_STATE=ABSENT" in out


def test_live_schema_read_fails_closed_when_image_schema_absent() -> None:
    out, code = _run_live_schema_read([DOCUMENT_TABLE, *DOCUMENT_INDEXES])
    assert code != 0
    assert "A6_IMAGE_TABLE_PRESENT=NO" in out
    assert "IMAGE_SCHEMA_STATE=ABSENT" in out
    assert "A6_IMAGE_STORE_SCHEMA_MISSING=YES" in out
    assert "A6_D1_SCHEMA_STATE=ABSENT" in out
    assert "A6_STORAGE_SCHEMA_VALIDATED=YES" not in out


def test_live_schema_read_is_name_only_against_row_shaped_payload() -> None:
    """Row values stay out of the log even if the store ever returns them.

    The query asks for names, but the reader is fed byte-store-shaped columns so
    the assertion tests the reader rather than the query text.
    """
    sentinel = "RAW-BYTE-VALUE-MUST-NOT-APPEAR"
    rows = [
        {
            "name": name,
            "content": sentinel,
            "text": sentinel,
            "blob": sentinel,
            "body": sentinel,
            "sql": f"SELECT * FROM {name}",
        }
        for name in COMPLETE_SCHEMA
    ]
    out, code = _run_live_schema_read([], rows=rows)
    assert code == 0, out
    assert sentinel not in out
    assert "SELECT *" not in out
    assert "SCHEMA_OBJECT_NAMES_ONLY=YES" in out
    assert "ROW_VALUE_OUTPUT=0" in out
    assert "DOCUMENT_CONTENT_OUTPUT=0" in out


def test_live_schema_read_handles_both_wrangler_payload_shapes() -> None:
    _, wrapped_code = _run_live_schema_read(COMPLETE_SCHEMA)
    assert wrapped_code == 0
    bare_out, bare_code = _run_live_schema_read(COMPLETE_SCHEMA, envelope=False)
    assert bare_code == 0, bare_out
    assert "A6_D1_SCHEMA_STATE=PRESENT" in bare_out
    empty_out, empty_code = _run_live_schema_read([], envelope=False)
    assert empty_code != 0
    assert "A6_D1_SCHEMA_STATE=ABSENT" in empty_out


def _pytest_hosts(test_file: str) -> set[str]:
    """Workflows whose pytest command actually names this test file.

    Repo contract-test workflows list files explicitly, so a module nothing
    points at is never executed in CI — the filename check is exact, and the
    substring prefilter only skips files that cannot be hosts.
    """
    hosts = set()
    for path in (ROOT / ".github/workflows").glob("*.y*ml"):
        text = path.read_text(encoding="utf-8")
        if test_file not in text or "pytest" not in text:
            continue
        spec = yaml.safe_load(text) or {}
        for job in (spec.get("jobs") or {}).values():
            for step in (job or {}).get("steps", []):
                run = step.get("run", "") if isinstance(step, dict) else ""
                if "pytest" in run and test_file in run:
                    hosts.add(path.name)
    return hosts


def test_slice_test_modules_have_a_real_ci_host() -> None:
    a6 = _pytest_hosts("test_b54_engine_a6_readonly_attestation.py")
    assert a6 == {"b54-engine-a6-readonly-attestation.yml"}, a6
    assert WORKFLOW.relative_to(ROOT).as_posix() in _triggers()["pull_request"]["paths"]
    assert (ROOT / ".github/tests" / "test_b54_engine_a6_readonly_attestation.py").relative_to(
        ROOT
    ).as_posix() in _triggers()["pull_request"]["paths"]
    # The extended guard module keeps its pre-existing host.
    assert "b54-engine-deploy-gate-contract-tests.yml" in _pytest_hosts(
        "test_b54_engine_served_version_guard.py"
    )


def test_workflow_parses_with_expected_job_set() -> None:
    doc = _doc()
    assert set(doc["jobs"]) == {"source-contract", LIVE_JOB}
    assert doc["permissions"] == {"contents": "read"}


def test_pull_request_never_runs_the_live_read() -> None:
    condition = _live_job()["if"]
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "pull_request" not in condition


def test_there_is_no_push_trigger_at_all() -> None:
    """Stronger than a guarded push: no push event can start this workflow.

    The Drive attestation this mirrors does run on main push. A6 must not, so
    the absence is asserted on the parsed trigger map, not on prose.
    """
    triggers = _triggers()
    assert "push" not in triggers
    assert set(triggers) == {"pull_request", "workflow_dispatch"}


def test_live_read_requires_the_exact_confirmation_phrase() -> None:
    condition = _live_job()["if"]
    assert f"github.event.inputs.confirmation == '{CONFIRMATION}'" in condition
    inputs = _triggers()["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"target_sha", "confirmation"}
    assert all(spec["required"] is True for spec in inputs.values())
    assert CONFIRMATION in inputs["confirmation"]["description"]


def test_live_job_runs_in_production_after_the_source_contract() -> None:
    job = _live_job()
    assert job["environment"] == "production"
    assert job["needs"] == "source-contract"


def test_live_job_guards_exact_current_main_before_reading() -> None:
    job = _live_job()
    steps = {step["name"]: step.get("run", "") for step in job["steps"]}
    guard = next(
        body for name, body in steps.items() if "exact current main" in name.lower()
    )
    assert 'test "$(git rev-parse HEAD)" = "${{ github.event.inputs.target_sha }}"' in guard
    assert "git fetch --no-tags --depth=1 origin main" in guard
    assert 'test "$(git rev-parse origin/main)" = "${{ github.event.inputs.target_sha }}"' in guard
    assert "A6_READONLY_EXACT_MAIN_SHA=PASS" in guard
    # The reconfirmation must be the first live step, before any GET.
    assert list(steps)[1] == next(
        name for name in steps if "exact current main" in name.lower()
    )


def test_attestation_reuses_the_canonical_served_version_resolver() -> None:
    text = _text()
    assert "b54_engine_served_version_guard.py resolve-active" in text
    assert "b54_engine_served_version_guard.py verify" in text
    assert "--require-a6-runtime-bindings" in text
    assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in _text()
    # No parallel resolver implementation, and the guard script is not forked.
    assert "def resolve_served_version_id" not in text
    assert GUARD.exists()


def test_live_read_uses_only_the_two_documented_get_endpoints() -> None:
    text = _text()
    assert "${base}/deployments" in text
    assert "${base}/versions/${active_version}" in text
    # A non-GET is expressed through curl's method switches or a body, never
    # through the bare words: "PUT"/"POST" also occur inside markers such as
    # RAW_DATABASE_ID_OUTPUT, so a substring scan here would be meaningless.
    for forbidden in ("-X ", "--request", "--data", " --upload-file", "-d ", "-F "):
        assert forbidden not in text, forbidden
    assert text.count("curl -fsS") == 2
    # The mutable settings plane must never substitute for served-version proof.
    assert "/settings" not in text


def test_d1_observation_is_schema_name_only() -> None:
    """Scoped to the SQL the live job sends, not to this test file's own text.

    The workflow must name the forbidden vocabulary in order to forbid it, and
    the scan pattern is itself a `--command "..."`-shaped literal, so a
    whole-file substring scan would match its own guard and prove nothing.
    """
    pattern = '--command "([^"]*)"'
    commands = [
        found
        for step in _live_job()["steps"]
        for found in re.findall(pattern, step.get("run", ""))
    ]
    assert commands == [SCHEMA_QUERY]
    joined = " ".join(commands).lower()
    for forbidden in (
        "select *",
        "content",
        "text",
        "blob",
        "hex(",
        "length(",
        "limit",
        "offset",
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "pragma",
    ):
        assert forbidden not in joined, forbidden


def test_d1_database_is_addressed_by_name_not_identifier() -> None:
    """No Cloudflare database UUID may be embedded or printed by this workflow."""
    text = _text()
    assert 'ENGINE_D1_DATABASE: padiem-engine' in text
    assert 'd1 execute "${ENGINE_D1_DATABASE}"' in text
    assert "6b77ad02-bc27-488f-bb97-6325f6750cba" not in text
    assert "D1_DATABASE_ID" not in text
    assert "RAW_DATABASE_ID_OUTPUT=0" in text


def test_missing_migration_is_reported_not_faked_as_success() -> None:
    text = _text()
    assert "DOCUMENT_SCHEMA_STATE=" in text
    assert "A6_D1_SCHEMA_STATE=ABSENT" in text
    assert "A6_D1_SCHEMA_STATE=PRESENT" in text
    assert "MIGRATION_0006_PRODUCTION_APPLIED=NO" in text
    # ABSENT must be raised, not merely printed.
    absent_branch = text[text.index("A6_D1_SCHEMA_STATE=ABSENT") :]
    assert "raise SystemExit" in absent_branch[: absent_branch.index("A6_D1_SCHEMA_STATE=PRESENT")]
    assert "IMAGE_SCHEMA_STATE=" in text


def test_source_contract_declares_the_inertness_markers() -> None:
    text = _text()
    for marker in (
        "ROW_VALUE_OUTPUT=0",
        "DOCUMENT_CONTENT_OUTPUT=0",
        "REAL_USER_DATA=0",
        "SECRET_VALUE_OUTPUT=0",
        "RAW_VERSION_DETAIL_OUTPUT=0",
        "D1_MUTATION=0",
        "MIGRATION_APPLY=0",
        "ENGINE_DEPLOY=0",
        "BINDING_MUTATION=0",
        "MANIFEST_FLIP=0",
        "READINESS_NOT_ACTIVATION=YES",
        "PRODUCTION_MUTATION=0",
        "SECOND_SERVED_VERSION_RESOLVER=NO",
        "A6_PRODUCTION_READ_AUTO_ON_MAIN_PUSH=NO",
        "A6_PRODUCTION_READ_DISPATCH_ONLY=YES",
    ):
        assert marker in text, marker


def test_source_contract_does_not_touch_production() -> None:
    doc = _doc()
    source = doc["jobs"]["source-contract"]
    assert "environment" not in source
    assert "secrets" not in _text()[: _text().index("served-a6-readonly:")]
    assert "CLOUDFLARE_API_TOKEN" not in _text()[: _text().index(LIVE_JOB)]


def test_wrangler_canonical_a6_bindings_are_pinned_by_the_contract() -> None:
    config = WRANGLER.read_text(encoding="utf-8")
    text = _text()
    for binding in ("ENGINE_IMAGE_STORE", "ENGINE_DOCUMENT_STORE"):
        block = config[config.index(f'binding = "{binding}"') :]
        head = block[: block.find("[[")]
        assert 'database_name = "padiem-engine"' in head
        assert f'"{binding}"' in text
    assert "canonical Engine A6 D1 binding missing or drifted" in text


def test_live_job_contains_no_mutation_shape() -> None:
    """Checked against the live job's own script, not this file's vocabulary.

    Naming a forbidden command is how it stays forbidden; scanning the whole
    workflow would match the list that forbids it.
    """
    live_runs = "\n".join(
        step.get("run", "") for step in _live_job()["steps"]
    )
    for shape in (
        "--file=",
        "migrations apply",
        "wrangler deploy",
        "pywrangler deploy",
        "wrangler versions",
        "--rollback-version-id",
        "secret put",
        "d1 create",
        "d1 delete",
        "--remote --command \"UPDATE",
        "[[d1_databases]]",
    ):
        assert shape not in live_runs, shape
    # The only remote execution allowed is the read-only deployments/version
    # GETs plus one schema-name D1 observation.
    assert live_runs.count("npx --yes wrangler@4 d1 execute") == 1
    assert live_runs.count("curl -fsS") == 2


def test_bounded_served_binding_markers_only() -> None:
    text = _text()
    assert "ENGINE_IMAGE_STORE_SERVED_BINDING=PRESENT:d1" in text
    assert "ENGINE_DOCUMENT_STORE_SERVED_BINDING=PRESENT:d1" in text
    assert "A6_STORAGE_BINDINGS_VALIDATED=YES" in text
    assert "BINDING_NAME_TYPE_ONLY=YES" in text


def test_rollback_anchor_comes_from_the_fresh_served_version() -> None:
    text = _text()
    assert "ROLLBACK_ANCHOR_VERSION_ID=${active_version}" in text
    assert "ROLLBACK_ANCHOR_SOURCE=FRESH_SERVED_VERSION" in text


def test_drive_attestation_and_guard_contract_remain_intact() -> None:
    """A6 must not widen or weaken the reviewed Drive evidence."""
    drive = (ROOT / ".github/workflows/b54-engine-google-oauth-binding-readonly.yml").read_text(
        encoding="utf-8"
    )
    assert "--require-drive-runtime-bindings" in drive
    assert "DRIVE_RUNTIME_BINDINGS_VALIDATED=YES" in drive
    guard = GUARD.read_text(encoding="utf-8")
    assert "require_drive_runtime_bindings: bool = False" in guard
    assert "require_a6_runtime_bindings: bool = False" in guard
    # The Drive flag keeps its own independent default and its own verifier.
    assert "_verify_drive_runtime_bindings" in guard
    assert "_verify_a6_runtime_bindings" in guard
