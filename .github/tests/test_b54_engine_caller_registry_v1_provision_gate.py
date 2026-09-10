"""Contract tests for the B54 Engine caller-registry V1 provision gate.

Proves statically that the gate:
  1. is dispatch-only for mutation (pull requests run only static tests);
  2. requires the exact confirmation phrase and the production environment;
  3. carries exact-main assertions fail-closed before any live read/mutation;
  4. never accepts secret material (raw registry or raw credential) through
     workflow_dispatch inputs — the baseline, the currentness attestation, and
     the credential all come from Actions secrets only;
  5. on the preservation path (live V1 PRESENT), requires the private baseline
     secret, asserts the B61 entry (storymemory-b61 / exactly ["b61"]),
     preserves every existing caller entry verbatim (unknown callers are
     opaque existing authority), and appends exactly the b54-kagent entry with
     the RAW credential (never pre-hashed);
  6. fails closed when b54-kagent already exists unless the baseline entry is
     exactly compatible (then the plan is a no-op);
  7. validates the COMPLETE merged result with the Engine's own V1 parser and
     proves authentication round-trips for B61, unknown callers, and
     b54-kagent against the exact payload shape;
  8. keeps the greenfield all-ABSENT path only as an isolated tested
     capability (not the Production path), forbidding baseline and attestation;
  9. never re-creates or blindly replaces an existing registry secret;
 10. never touches the B62 live-config workflow or the ``padiem-chat`` worker,
     and never deploys the Engine worker;
 11. FAILS CLOSED unless BASELINE_CURRENTNESS_PROVEN=YES: a structurally valid
     baseline is not proof of currentness, so the bounded NON-SECRET
     attestation from the private authority process (#2400) must be present,
     canonical, bound to the EXACT supplied baseline (SHA-256 of its UTF-8
     bytes), match the baseline caller count, and be fresh — otherwise the plan
     fails and the workflow cannot reach the PUT;
 12. rejects any attempt to smuggle registry plaintext or credential material
     in as the currentness provenance input.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-engine-caller-registry-v1-provision-gate.yml"
HELPER = ROOT / ".github/scripts/b54_engine_caller_registry_v1_provision.py"

SENTINEL = "sentinel-raw-value-must-never-appear"
CREDENTIAL_ENV = "B54_TEST_ENGINE_CALLER_CREDENTIAL"
BASELINE_ENV = "B54_TEST_ENGINE_CALLER_REGISTRY_BASELINE"
CURRENTNESS_ENV = "B54_TEST_ENGINE_CALLER_REGISTRY_CURRENTNESS"
CURRENTNESS_AUTHORITY = "b54-preservation-authority"
LEGACY_TRIO_NAMES = (
    "PADIEM_ENGINE_CALLER_ID",
    "PADIEM_ENGINE_CALLER_SECRET",
    "PADIEM_ENGINE_ALLOWED_APPS",
)


def _load_helper():
    spec = importlib.util.spec_from_file_location("b54_engine_caller_registry_v1_provision", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_engine_identity():
    """Load the Engine V1 parser without importing the heavy app package."""
    engine_root = ROOT / "apps" / "padiem-ai-engine"
    app_pkg = types.ModuleType("app")
    sys.modules["app"] = app_pkg
    service_identity_spec = importlib.util.spec_from_file_location(
        "app.service_identity", engine_root / "app" / "service_identity.py"
    )
    assert service_identity_spec is not None and service_identity_spec.loader is not None
    service_identity = importlib.util.module_from_spec(service_identity_spec)
    # Register before exec: dataclass introspection resolves cls.__module__
    # through sys.modules while the class body is processed.
    sys.modules["app.service_identity"] = service_identity
    service_identity_spec.loader.exec_module(service_identity)
    app_pkg.service_identity = service_identity
    identity_spec = importlib.util.spec_from_file_location(
        "app.identity_enforcement", engine_root / "app" / "identity_enforcement.py"
    )
    assert identity_spec is not None and identity_spec.loader is not None
    identity = importlib.util.module_from_spec(identity_spec)
    sys.modules["app.identity_enforcement"] = identity
    identity_spec.loader.exec_module(identity)
    return identity


def _binding(name: str, binding_type: str, **value_fields: object) -> dict[str, object]:
    row: dict[str, object] = {"name": name, "type": binding_type}
    row.update(value_fields)
    return row


def _settings(bindings: list[dict[str, object]]) -> dict[str, object]:
    return {"success": True, "result": {"bindings": bindings}}


def _run_main(helper, argv: list[str]) -> tuple[int, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = helper.main(argv)
    return code, stdout.getvalue() + stderr.getvalue()


def _write_settings(payload: object) -> Path:
    tmp = tempfile.mkdtemp(prefix="b54-registry-test-")
    path = Path(tmp) / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@contextlib.contextmanager
def _env(**values: str | None):
    """Temporarily set/clear environment variables, always restoring them."""
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _registry_entry(caller_id: str, credential: str, app_ids: list[str]) -> dict:
    return {"caller_id": caller_id, "credential": credential, "allowed_app_ids": app_ids}


def _baseline_payload(b54_credential: str, b61_credential: str) -> dict:
    return {
        "version": 1,
        "callers": [
            _registry_entry("storymemory-b61", b61_credential, ["b61"]),
            _registry_entry("opaque-unknown-caller", "u" * 40, ["b61", "other"]),
        ],
    }


def _currentness(
    helper,
    baseline: str,
    payload: dict,
    *,
    authority: str = CURRENTNESS_AUTHORITY,
    issued_at: datetime | None = None,
    caller_count: int | None = None,
) -> str:
    """Build a canonical attestation for a baseline (the #2400 issuance contract)."""
    return helper.format_currentness_attestation(
        authority=authority,
        baseline=baseline,
        caller_count=len(payload["callers"]) if caller_count is None else caller_count,
        issued_at=issued_at if issued_at is not None else datetime.now(timezone.utc),
    )


def _plan_argv(
    *,
    disposition: str,
    output: Path,
    baseline_env: str | None,
    currentness_env: str | None,
) -> list[str]:
    argv = [
        "plan",
        "--disposition",
        disposition,
        "--credential-env",
        CREDENTIAL_ENV,
        "--output",
        str(output),
    ]
    if baseline_env is not None:
        argv += ["--baseline-env", baseline_env]
    if currentness_env is not None:
        argv += ["--currentness-env", currentness_env]
    return argv


def _run_plan(
    helper,
    *,
    disposition: str,
    output: Path,
    baseline_env: str | None = BASELINE_ENV,
    currentness_env: str | None = CURRENTNESS_ENV,
) -> tuple[int, str]:
    return _run_main(
        helper,
        _plan_argv(
            disposition=disposition,
            output=output,
            baseline_env=baseline_env,
            currentness_env=currentness_env,
        ),
    )


def test_script_constants_exact() -> None:
    helper = _load_helper()
    assert helper.ENGINE_WORKER == "padiem-ai-engine"
    assert helper.REGISTRY_SECRET_NAME == "PADIEM_ENGINE_CALLER_REGISTRY_V1"
    assert helper.CALLER_ID == "b54-kagent"
    assert helper.ALLOWED_APP_IDS == ("b54-padiem-claw",)
    assert helper.B61_CALLER_ID == "storymemory-b61"
    assert helper.B61_ALLOWED_APP_IDS == ("b61",)
    assert helper.REGISTRY_VERSION == 1
    assert helper.MIN_CREDENTIAL_BYTES == 32
    assert helper.MAX_CREDENTIAL_BYTES == 512
    assert helper.MAX_CALLER_REGISTRY_V1_BYTES == 524288
    assert set(helper.LEGACY_TRIO_NAMES) == set(LEGACY_TRIO_NAMES)
    # Currentness contract constants (source-bounded; not dispatcher-tunable).
    assert helper.CURRENTNESS_ATTESTATION_PREFIX == "b54-currentness-v1"
    assert helper.CURRENTNESS_AUTHORITY_ID == CURRENTNESS_AUTHORITY
    assert helper.CURRENTNESS_FIELD_ORDER == (
        "authority",
        "baseline_sha256",
        "caller_count",
        "issued_at",
    )
    assert helper.CURRENTNESS_FINGERPRINT_ALGO == "sha256"
    assert helper.CURRENTNESS_MAX_ATTESTATION_BYTES == 1024
    assert helper.CURRENTNESS_MAX_AGE_SECONDS == 24 * 60 * 60
    assert helper.CURRENTNESS_MAX_FUTURE_SKEW_SECONDS == 5 * 60


def test_authority_dispositions() -> None:
    helper = _load_helper()
    all_absent = {
        "PADIEM_ENGINE_CALLER_REGISTRY_V1": "ABSENT",
        "PADIEM_ENGINE_CALLER_ID": "ABSENT",
        "PADIEM_ENGINE_CALLER_SECRET": "ABSENT",
        "PADIEM_ENGINE_ALLOWED_APPS": "ABSENT",
    }
    assert helper.authority_disposition(all_absent) == "PROVISION_REQUIRED"
    assert (
        helper.authority_disposition(
            {
                "PADIEM_ENGINE_CALLER_REGISTRY_V1": "PRESENT:secret_text",
                "PADIEM_ENGINE_CALLER_ID": "ABSENT",
                "PADIEM_ENGINE_CALLER_SECRET": "ABSENT",
                "PADIEM_ENGINE_ALLOWED_APPS": "ABSENT",
            }
        )
        == "EXTEND_REQUIRED"
    )
    # Live truth shape: V1 plus the full legacy trio present.
    assert (
        helper.authority_disposition(
            {
                "PADIEM_ENGINE_CALLER_REGISTRY_V1": "PRESENT:secret_text",
                "PADIEM_ENGINE_CALLER_ID": "PRESENT:secret_text",
                "PADIEM_ENGINE_CALLER_SECRET": "PRESENT:secret_text",
                "PADIEM_ENGINE_ALLOWED_APPS": "PRESENT:secret_text",
            }
        )
        == "EXTEND_REQUIRED"
    )
    assert (
        helper.authority_disposition(
            {
                "PADIEM_ENGINE_CALLER_REGISTRY_V1": "ABSENT",
                "PADIEM_ENGINE_CALLER_ID": "PRESENT:plain_text",
                "PADIEM_ENGINE_CALLER_SECRET": "PRESENT:secret_text",
                "PADIEM_ENGINE_ALLOWED_APPS": "PRESENT:plain_text",
            }
        )
        == "REFUSE_LEGACY_AUTHORITY_PRESENT"
    )
    assert (
        helper.authority_disposition(
            {
                "PADIEM_ENGINE_CALLER_REGISTRY_V1": "PRESENT:plain_text",
                "PADIEM_ENGINE_CALLER_ID": "ABSENT",
                "PADIEM_ENGINE_CALLER_SECRET": "ABSENT",
                "PADIEM_ENGINE_ALLOWED_APPS": "ABSENT",
            }
        )
        == "REFUSE_WRONG_TYPE"
    )


def test_parse_baseline_requires_b61_contract() -> None:
    helper = _load_helper()
    b61 = "b" * 40
    payload = _baseline_payload(b54_credential="x" * 40, b61_credential=b61)
    parsed = helper.parse_baseline_registry(json.dumps(payload))
    assert parsed["callers"][0]["credential"] == b61

    # Missing B61 entry fails closed.
    no_b61 = {
        "version": 1,
        "callers": [_registry_entry("opaque-unknown-caller", "u" * 40, ["other"])],
    }
    try:
        helper.parse_baseline_registry(json.dumps(no_b61))
    except helper.ProvisionPlanError:
        pass
    else:
        raise AssertionError("baseline missing storymemory-b61 must fail closed")

    # B61 with a different app list fails closed.
    wrong_apps = {
        "version": 1,
        "callers": [_registry_entry("storymemory-b61", b61, ["b61", "extra"])],
    }
    try:
        helper.parse_baseline_registry(json.dumps(wrong_apps))
    except helper.ProvisionPlanError:
        pass
    else:
        raise AssertionError("B61 allowed_app_ids must be exactly [\"b61\"]")

    # Malformed baselines fail closed.
    for bad in ("", "not-json", "[]", '{"version":2,"callers":[]}'):
        try:
            helper.parse_baseline_registry(bad)
        except helper.ProvisionPlanError:
            continue
        raise AssertionError(f"baseline {bad!r} must fail closed")


def test_merge_appends_b54_and_preserves_all_existing_verbatim() -> None:
    helper = _load_helper()
    b61_cred = "b" * 40
    unknown_cred = "u" * 40
    baseline = _baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred)
    new_cred = "n" * 40
    merged, verdict = helper.merge_b54_caller(baseline, new_cred)
    assert verdict == "APPENDED"
    by_id = {entry["caller_id"]: entry for entry in merged["callers"]}
    # Existing entries preserved verbatim (credential and apps untouched).
    assert by_id["storymemory-b61"] == baseline["callers"][0]
    assert by_id["opaque-unknown-caller"] == baseline["callers"][1]
    # B54 entry appended with raw credential and exact app list.
    assert by_id["b54-kagent"] == {
        "caller_id": "b54-kagent",
        "credential": new_cred,
        "allowed_app_ids": ["b54-padiem-claw"],
    }
    assert merged["version"] == 1


def test_merge_existing_compatible_b54_is_no_op() -> None:
    helper = _load_helper()
    b61_cred = "b" * 40
    compatible_cred = "c" * 40
    baseline = {
        "version": 1,
        "callers": [
            _registry_entry("storymemory-b61", b61_cred, ["b61"]),
            _registry_entry("b54-kagent", compatible_cred, ["b54-padiem-claw"]),
        ],
    }
    merged, verdict = helper.merge_b54_caller(baseline, compatible_cred)
    assert verdict == "ALREADY_COMPATIBLE"
    assert merged["callers"] == baseline["callers"]


def test_merge_existing_incompatible_b54_fails_closed() -> None:
    helper = _load_helper()
    b61_cred = "b" * 40
    # Different credential.
    baseline_bad_cred = {
        "version": 1,
        "callers": [
            _registry_entry("storymemory-b61", b61_cred, ["b61"]),
            _registry_entry("b54-kagent", "z" * 40, ["b54-padiem-claw"]),
        ],
    }
    try:
        helper.merge_b54_caller(baseline_bad_cred, "n" * 40)
    except helper.ProvisionPlanError:
        pass
    else:
        raise AssertionError("existing b54-kagent with a different credential must fail closed")
    # Different app contract.
    baseline_bad_apps = {
        "version": 1,
        "callers": [
            _registry_entry("storymemory-b61", b61_cred, ["b61"]),
            _registry_entry("b54-kagent", "n" * 40, ["b54-padiem-claw", "extra"]),
        ],
    }
    try:
        helper.merge_b54_caller(baseline_bad_apps, "n" * 40)
    except helper.ProvisionPlanError:
        return
    raise AssertionError("existing b54-kagent with a different app contract must fail closed")


def test_greenfield_payload_is_isolated_single_caller() -> None:
    helper = _load_helper()
    credential = "g" * 40
    payload = helper.build_registry_payload(credential=credential)
    assert payload["version"] == 1
    assert payload["callers"] == [
        {
            "caller_id": "b54-kagent",
            "credential": credential,
            "allowed_app_ids": ["b54-padiem-claw"],
        }
    ]
    for bad in ("", "x" * 31, "x" * 513):
        try:
            helper.build_registry_payload(credential=bad)
        except helper.ProvisionPlanError:
            continue
        raise AssertionError(f"greenfield credential of invalid length must fail closed: {len(bad)}")
    helper.build_registry_payload(credential="x" * 32)
    helper.build_registry_payload(credential="x" * 512)


def test_merged_payload_parses_and_authenticates_with_engine_parser() -> None:
    helper = _load_helper()
    identity = _load_engine_identity()
    b61_cred = "b" * 40
    unknown_cred = "u" * 40
    new_cred = "n" * 40
    baseline = _baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred)
    merged, _ = helper.merge_b54_caller(baseline, new_cred)
    serialized = json.dumps(merged, separators=(",", ":"), ensure_ascii=False)
    env = type("Env", (), {identity.CALLER_REGISTRY_V1_ENV: serialized})()

    # Every caller authenticates with its own raw credential.
    identity.authenticate_request(
        env=env,
        headers={identity.CALLER_ID_HEADER: "storymemory-b61", identity.CALLER_CREDENTIAL_HEADER: b61_cred},
        requested_app_id="b61",
    )
    identity.authenticate_request(
        env=env,
        headers={
            identity.CALLER_ID_HEADER: "opaque-unknown-caller",
            identity.CALLER_CREDENTIAL_HEADER: unknown_cred,
        },
        requested_app_id="other",
    )
    identity.authenticate_request(
        env=env,
        headers={identity.CALLER_ID_HEADER: "b54-kagent", identity.CALLER_CREDENTIAL_HEADER: new_cred},
        requested_app_id="b54-padiem-claw",
    )
    # A pre-hashed value is NOT the accepted credential: the Engine hashes
    # internally, so a digest in the payload must fail authentication.
    try:
        identity.authenticate_request(
            env=env,
            headers={
                identity.CALLER_ID_HEADER: "b54-kagent",
                identity.CALLER_CREDENTIAL_HEADER: identity.caller_secret_digest(new_cred),
            },
            requested_app_id="b54-padiem-claw",
        )
    except identity.ServiceIdentityError as exc:
        assert exc.code == "service_authentication_failed"
        return
    raise AssertionError("pre-hashed credential must not authenticate")


# ---------------------------------------------------------------------------
# Currentness guard (BLOCKING: a structurally valid baseline is not proof of
# currentness). Requirements 1-4, 7-8, 11.
# ---------------------------------------------------------------------------


def test_currentness_attestation_canonical_form_contract() -> None:
    helper = _load_helper()
    b61_cred = "b" * 40
    baseline = json.dumps(_baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred))
    payload = json.loads(baseline)
    now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

    attestation = _currentness(helper, baseline, payload, issued_at=now)
    assert attestation.startswith("b54-currentness-v1 authority=")
    assert f"baseline_sha256={helper.baseline_fingerprint(baseline)}" in attestation
    assert "caller_count=2" in attestation
    assert "issued_at=2026-09-11T12:00:00Z" in attestation
    meta = helper.parse_currentness_attestation(attestation)
    assert meta["authority"] == CURRENTNESS_AUTHORITY
    assert meta["caller_count"] == 2
    assert meta["issued_at"] == now
    # The canonical form carries no registry plaintext and no credential.
    assert b61_cred not in attestation
    assert "{" not in attestation and '"' not in attestation

    # Bounded issuance inputs.
    for bad_count in (0, 65, True):
        try:
            _currentness(helper, baseline, payload, caller_count=bad_count)
        except helper.ProvisionPlanError:
            continue
        raise AssertionError(f"caller_count {bad_count!r} must fail closed")
    try:
        helper.format_currentness_attestation(
            authority=CURRENTNESS_AUTHORITY,
            baseline=baseline,
            caller_count=2,
            issued_at=datetime(2026, 9, 11, 12, 0, 0),
        )
    except helper.ProvisionPlanError:
        pass
    else:
        raise AssertionError("naive issued_at must fail closed")
    for bad_authority in (
        "",
        "bad authority",
        "x" * 129,
        "bad\nauthority",
        # Bounded but NOT the approved private authority: a credential-shaped
        # string must not be accepted in the authority slot (and is never
        # echoed, because only the canonical constant is emitted).
        "some-other-authority",
        "n" * 40,
    ):
        try:
            helper.format_currentness_attestation(
                authority=bad_authority,
                baseline=baseline,
                caller_count=2,
                issued_at=now,
            )
        except helper.ProvisionPlanError:
            continue
        raise AssertionError(f"authority {bad_authority!r} must fail closed")

    # The approved authority is the only one that parses.
    for bad_authority in ("some-other-authority", "n" * 40):
        forged = attestation.replace(CURRENTNESS_AUTHORITY, bad_authority)
        assert forged != attestation
        try:
            helper.parse_currentness_attestation(forged)
        except helper.ProvisionPlanError:
            continue
        raise AssertionError(f"unapproved authority {bad_authority!r} must fail closed")


def test_currentness_binds_exact_baseline_fingerprint_and_caller_count() -> None:
    helper = _load_helper()
    b61_cred = "b" * 40
    baseline = json.dumps(_baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred))
    payload = json.loads(baseline)
    now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

    # Fingerprint issued for a DIFFERENT (longer) baseline must not match.
    other_baseline = json.dumps(
        {
            "version": 1,
            "callers": payload["callers"]
            + [_registry_entry("another-caller", "a" * 40, ["b61"])],
        }
    )
    mismatched = _currentness(helper, other_baseline, payload, issued_at=now)
    try:
        helper.assert_baseline_currentness(baseline, payload, mismatched, now=now)
    except helper.ProvisionPlanError:
        pass
    else:
        raise AssertionError("attestation for another baseline must fail closed")

    # Caller count that does not match the supplied baseline must fail.
    wrong_count = _currentness(helper, baseline, payload, issued_at=now, caller_count=3)
    try:
        helper.assert_baseline_currentness(baseline, payload, wrong_count, now=now)
    except helper.ProvisionPlanError:
        pass
    else:
        raise AssertionError("caller_count mismatch must fail closed")

    # Exact binding succeeds, including the freshness boundaries.
    accepted = _currentness(helper, baseline, payload, issued_at=now)
    helper.assert_baseline_currentness(baseline, payload, accepted, now=now)
    helper.assert_baseline_currentness(
        baseline,
        payload,
        accepted,
        now=now + timedelta(seconds=helper.CURRENTNESS_MAX_AGE_SECONDS),
    )


def test_extend_without_currentness_proof_fails_closed() -> None:
    """Requirement 1: EXTEND + valid baseline + NO proof -> FAIL (PUT=NO)."""
    helper = _load_helper()
    b61_cred = "b" * 40
    baseline = json.dumps(_baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred))

    # (a) no --currentness-env argument at all
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: "n" * 40, BASELINE_ENV: baseline, CURRENTNESS_ENV: None}):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out, currentness_env=None)
        assert code == 1
        assert "B54_ENGINE_CALLER_REGISTRY_PLAN=FAIL" in output
        assert "BASELINE_CURRENTNESS_PROVEN=NO" in output
        assert not out.exists()

    # (b) flag present but the environment variable is unset
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: "n" * 40, BASELINE_ENV: baseline, CURRENTNESS_ENV: None}):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
        assert code == 1
        assert "BASELINE_CURRENTNESS_PROVEN=NO" in output
        assert not out.exists()

    # (c) flag present but blank
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: "n" * 40, BASELINE_ENV: baseline, CURRENTNESS_ENV: ""}):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
        assert code == 1
        assert "BASELINE_CURRENTNESS_PROVEN=NO" in output
        assert not out.exists()


def test_extend_with_invalid_currentness_proof_fails_closed() -> None:
    """Requirement 2: EXTEND + valid baseline + INVALID proof -> FAIL."""
    helper = _load_helper()
    b61_cred = "b" * 40
    baseline = json.dumps(_baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred))
    payload = json.loads(baseline)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    valid = _currentness(helper, baseline, payload, issued_at=now)
    fingerprint = helper.baseline_fingerprint(baseline)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert f"issued_at={stamp}" in valid

    invalid = {
        "wrong prefix": valid.replace("b54-currentness-v1", "b54-currentness-v2"),
        "extra field appended": valid + " extra=1",
        "field reordered": f"b54-currentness-v1 baseline_sha256={fingerprint} authority={CURRENTNESS_AUTHORITY} caller_count=2 issued_at={stamp}",
        "unbounded authority": valid.replace(CURRENTNESS_AUTHORITY, "bad authority"),
        "non-hex fingerprint": valid.replace(fingerprint, "z" * 64),
        "short fingerprint": valid.replace(fingerprint, fingerprint[:63]),
        "non-integer count": valid.replace("caller_count=2", "caller_count=two"),
        "count out of bounds": valid.replace("caller_count=2", "caller_count=65"),
        "non-UTC timestamp": valid.replace("Z", "+00:00"),
        "malformed timestamp": valid.replace(f"issued_at={stamp}", "issued_at=today"),
        "date-only timestamp": valid.replace(
            f"issued_at={stamp}", f"issued_at={now.strftime('%Y-%m-%d')}"
        ),
        "not the contract": "attested",
        "empty": "",
        "non-ascii": "b54-currentness-v1 authority=é baseline_sha256="
        + fingerprint
        + f" caller_count=2 issued_at={stamp}",
    }
    for label, value in invalid.items():
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "put-body.json"
            with _env(**{CREDENTIAL_ENV: "n" * 40, BASELINE_ENV: baseline, CURRENTNESS_ENV: value}):
                code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
            assert code == 1, label
            assert "BASELINE_CURRENTNESS_PROVEN=NO" in output, label
            assert not out.exists(), label


def test_extend_stale_or_future_currentness_cannot_reach_put() -> None:
    """Requirement 4: a valid-but-stale/unproven baseline cannot reach PUT."""
    helper = _load_helper()
    b61_cred = "b" * 40
    baseline = json.dumps(_baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred))
    payload = json.loads(baseline)
    reference = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

    stale_at = reference - timedelta(seconds=helper.CURRENTNESS_MAX_AGE_SECONDS + 1)
    stale = _currentness(helper, baseline, payload, issued_at=stale_at)
    # The stale attestation is formally canonical and fingerprint-correct...
    helper.parse_currentness_attestation(stale)
    assert helper.baseline_fingerprint(baseline) in stale
    # ...but it cannot prove currentness.
    try:
        helper.assert_baseline_currentness(baseline, payload, stale, now=reference)
    except helper.ProvisionPlanError:
        pass
    else:
        raise AssertionError("stale attestation must fail closed")

    future = _currentness(
        helper,
        baseline,
        payload,
        issued_at=reference + timedelta(seconds=helper.CURRENTNESS_MAX_FUTURE_SKEW_SECONDS + 1),
    )
    try:
        helper.assert_baseline_currentness(baseline, payload, future, now=reference)
    except helper.ProvisionPlanError:
        pass
    else:
        raise AssertionError("future-dated attestation must fail closed")

    # End-to-end: a stale attestation must not produce a PUT body. Built
    # against the real clock so the staleness holds regardless of run date.
    real_stale = _currentness(
        helper,
        baseline,
        payload,
        issued_at=datetime.now(timezone.utc)
        - timedelta(seconds=helper.CURRENTNESS_MAX_AGE_SECONDS + 60),
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: "n" * 40, BASELINE_ENV: baseline, CURRENTNESS_ENV: real_stale}):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
        assert code == 1
        assert "BASELINE_CURRENTNESS_PROVEN=NO" in output
        assert not out.exists()

    # End-to-end: a future-dated attestation also cannot produce a PUT body.
    real_future = _currentness(
        helper,
        baseline,
        payload,
        issued_at=datetime.now(timezone.utc)
        + timedelta(seconds=helper.CURRENTNESS_MAX_FUTURE_SKEW_SECONDS + 60),
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: "n" * 40, BASELINE_ENV: baseline, CURRENTNESS_ENV: real_future}):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
        assert code == 1
        assert "BASELINE_CURRENTNESS_PROVEN=NO" in output
        assert not out.exists()


def test_extend_with_valid_currentness_is_allowed() -> None:
    """Requirement 3: EXTEND + valid baseline + accepted proof -> plan allowed."""
    helper = _load_helper()
    b61_cred = "b" * 40
    baseline = json.dumps(_baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred))
    payload = json.loads(baseline)
    attestation = _currentness(helper, baseline, payload)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: "n" * 40, BASELINE_ENV: baseline, CURRENTNESS_ENV: attestation}):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
        assert code == 0
        assert "B54_ENGINE_CALLER_REGISTRY_PLAN=PASS" in output
        assert "BASELINE_CURRENTNESS_PROVEN=YES" in output
        assert "CURRENTNESS_ATTESTATION_CONTAINS_SECRET_MATERIAL=NO" in output
        assert out.exists()
        body = json.loads(out.read_text(encoding="utf-8"))
    merged = json.loads(body["text"])
    by_id = {entry["caller_id"]: entry for entry in merged["callers"]}
    # Requirement 5: unknown baseline callers remain preserved.
    assert set(by_id) == {"storymemory-b61", "opaque-unknown-caller", "b54-kagent"}
    # Requirement 6: B61 preservation remains exact.
    assert by_id["storymemory-b61"]["allowed_app_ids"] == ["b61"]
    assert by_id["storymemory-b61"]["credential"] == b61_cred
    assert by_id["opaque-unknown-caller"]["credential"] == "u" * 40
    assert by_id["b54-kagent"]["credential"] == "n" * 40
    assert by_id["b54-kagent"]["allowed_app_ids"] == ["b54-padiem-claw"]


def test_currentness_rejects_raw_registry_material() -> None:
    """Requirement 7: the raw registry cannot be the provenance input."""
    helper = _load_helper()
    b61_cred = "b" * 40
    baseline = json.dumps(_baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred))
    forbidden = {
        "raw registry json": baseline,
        "pretty registry json": json.dumps(json.loads(baseline), indent=2),
        "registry json in envelope": (
            f"b54-currentness-v1 authority={CURRENTNESS_AUTHORITY} baseline_sha256="
            f"{helper.baseline_fingerprint(baseline)} caller_count=2 "
            f"issued_at=2026-09-11T12:00:00Z {baseline}"
        ),
        "json braces only": '{"version":1,"callers":[]}',
    }
    for label, value in forbidden.items():
        try:
            helper.parse_currentness_attestation(value)
        except helper.ProvisionPlanError:
            continue
        raise AssertionError(f"raw registry material accepted as provenance: {label}")

    # And the credential-free gate still refuses it end to end.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: "n" * 40, BASELINE_ENV: baseline, CURRENTNESS_ENV: baseline}):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
        assert code == 1
        assert not out.exists()
        assert b61_cred not in output


def test_currentness_rejects_raw_credential_material() -> None:
    """Requirement 8: the raw credential cannot be the provenance input."""
    helper = _load_helper()
    b61_cred = "b" * 40
    new_cred = "n" * 40
    baseline = json.dumps(_baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred))
    forbidden = {
        "raw credential": new_cred,
        "credential in envelope": (
            f"b54-currentness-v1 authority={CURRENTNESS_AUTHORITY} baseline_sha256="
            f"{helper.baseline_fingerprint(baseline)} caller_count=2 "
            f"issued_at=2026-09-11T12:00:00Z {new_cred}"
        ),
        "credential as authority": (
            f"b54-currentness-v1 authority={new_cred} baseline_sha256="
            f"{helper.baseline_fingerprint(baseline)} caller_count=2 "
            f"issued_at=2026-09-11T12:00:00Z"
        ),
    }
    for label, value in forbidden.items():
        try:
            helper.parse_currentness_attestation(value)
        except helper.ProvisionPlanError:
            continue
        raise AssertionError(f"raw credential accepted as provenance: {label}")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: new_cred, BASELINE_ENV: baseline, CURRENTNESS_ENV: new_cred}):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
        assert code == 1
        assert not out.exists()
        assert new_cred not in output


def test_plan_extend_path_evidence_and_never_emits_secrets() -> None:
    helper = _load_helper()
    b61_cred = "b" * 40
    new_cred = "n" * 40
    baseline = json.dumps(_baseline_payload(b54_credential="x" * 40, b61_credential=b61_cred))
    payload = json.loads(baseline)
    attestation = _currentness(helper, baseline, payload)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: new_cred, BASELINE_ENV: baseline, CURRENTNESS_ENV: attestation}):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
        assert code == 0
        body = json.loads(out.read_text(encoding="utf-8"))
    for leaked in (new_cred, b61_cred, baseline, attestation, helper.baseline_fingerprint(baseline)):
        assert leaked not in output, "secret/provenance material must not be emitted"
    for marker in (
        "B61_PRESERVATION_ASSERT=PASS",
        "UNKNOWN_CALLERS_PRESERVED=PASS",
        "BASELINE_CALLERS_PRESERVED_VERBATIM=PASS",
        "B54_KAGENT_APPEND_ONLY=PASS",
        "BASELINE_CURRENTNESS_PROVEN=YES",
        "BASELINE_CURRENTNESS_AUTHORITY=b54-preservation-authority",
        "BASELINE_CURRENTNESS_FINGERPRINT_BOUND=YES",
        "BASELINE_CURRENTNESS_CALLER_COUNT=2",
        "CURRENTNESS_ATTESTATION_CONTAINS_SECRET_MATERIAL=NO",
        "RAW_CREDENTIAL_PREHASHED=NO",
        "RAW_SECRET_OUTPUT=0",
        "RAW_REGISTRY_OUTPUT=0",
        "SECRET_VALUE_OUTPUT=0",
        "B54_ENGINE_CALLER_REGISTRY_NO_OP=0",
    ):
        assert marker in output, marker
    assert body["name"] == "PADIEM_ENGINE_CALLER_REGISTRY_V1"
    assert body["type"] == "secret_text"
    merged = json.loads(body["text"])
    by_id = {entry["caller_id"]: entry for entry in merged["callers"]}
    assert set(by_id) == {"storymemory-b61", "opaque-unknown-caller", "b54-kagent"}
    assert by_id["storymemory-b61"]["credential"] == b61_cred


def test_plan_extend_no_op_when_b54_already_compatible() -> None:
    helper = _load_helper()
    b61_cred = "b" * 40
    compatible_cred = "c" * 40
    baseline = json.dumps(
        {
            "version": 1,
            "callers": [
                _registry_entry("storymemory-b61", b61_cred, ["b61"]),
                _registry_entry("b54-kagent", compatible_cred, ["b54-padiem-claw"]),
            ],
        }
    )
    payload = json.loads(baseline)
    attestation = _currentness(helper, baseline, payload)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(
            **{
                CREDENTIAL_ENV: compatible_cred,
                BASELINE_ENV: baseline,
                CURRENTNESS_ENV: attestation,
            }
        ):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
        assert code == 0
        assert "B54_KAGENT_APPEND_ONLY=ALREADY_COMPATIBLE" in output
        assert "BASELINE_CURRENTNESS_PROVEN=YES" in output
        assert "B54_ENGINE_CALLER_REGISTRY_NO_OP=1" in output
        body = json.loads(out.read_text(encoding="utf-8"))
        assert json.loads(body["text"])["callers"] == payload["callers"]


def test_plan_extend_requires_baseline_secret() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: "n" * 40, BASELINE_ENV: None, CURRENTNESS_ENV: None}):
            code, output = _run_plan(helper, disposition="EXTEND_REQUIRED", output=out)
    assert code == 1
    assert "B54_ENGINE_CALLER_REGISTRY_PLAN=FAIL" in output
    assert not out.exists()


def test_plan_greenfield_isolated_and_baseline_forbidden() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: "g" * 40, BASELINE_ENV: None, CURRENTNESS_ENV: None}):
            code, output = _run_plan(helper, disposition="PROVISION_REQUIRED", output=out)
        assert code == 0
        assert "B54_KAGENT_APPEND_ONLY=GREENFIELD_SINGLE_CALLER" in output
        assert "BASELINE_CURRENTNESS_PROVEN=GREENFIELD_NOT_APPLICABLE" in output
        assert "B54_ENGINE_CALLER_REGISTRY_NO_OP=0" in output
        body = json.loads(out.read_text(encoding="utf-8"))
        assert [e["caller_id"] for e in json.loads(body["text"])["callers"]] == ["b54-kagent"]

        # Baseline on the greenfield path is contradictory: fail closed.
        with _env(
            **{
                CREDENTIAL_ENV: "g" * 40,
                BASELINE_ENV: json.dumps(_baseline_payload("x" * 40, "b" * 40)),
                CURRENTNESS_ENV: None,
            }
        ):
            code, output = _run_plan(helper, disposition="PROVISION_REQUIRED", output=out)
        assert code == 1

    # Requirement 10: the attestation is equally forbidden there — the
    # greenfield path stays an isolated capability, not a bypass.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(
            **{
                CREDENTIAL_ENV: "g" * 40,
                BASELINE_ENV: None,
                CURRENTNESS_ENV: "b54-currentness-v1 authority=x baseline_sha256="
                + "0" * 64
                + " caller_count=1 issued_at=2026-09-11T12:00:00Z",
            }
        ):
            code, output = _run_plan(helper, disposition="PROVISION_REQUIRED", output=out)
        assert code == 1
        assert "B54_ENGINE_CALLER_REGISTRY_PLAN=FAIL" in output
        assert not out.exists()


def test_classify_cli_dispositions() -> None:
    helper = _load_helper()
    empty = _settings([])
    code, output = _run_main(helper, ["classify", "--settings", str(_write_settings(empty))])
    assert code == 0
    assert "B54_ENGINE_CALLER_REGISTRY_DISPOSITION=PROVISION_REQUIRED" in output
    assert "SECRET_VALUES_READ=0" in output
    assert "BINDING_NAME_AND_TYPE_ONLY=YES" in output
    assert SENTINEL not in output

    live = _settings(
        [
            _binding("PADIEM_ENGINE_CALLER_REGISTRY_V1", "secret_text", text=SENTINEL),
            _binding("PADIEM_ENGINE_CALLER_ID", "secret_text", text=SENTINEL),
            _binding("PADIEM_ENGINE_CALLER_SECRET", "secret_text", text=SENTINEL),
            _binding("PADIEM_ENGINE_ALLOWED_APPS", "secret_text", text=SENTINEL),
        ]
    )
    code, output = _run_main(helper, ["classify", "--settings", str(_write_settings(live))])
    assert code == 0
    assert "B54_ENGINE_CALLER_REGISTRY_DISPOSITION=EXTEND_REQUIRED" in output

    legacy = _settings([_binding("PADIEM_ENGINE_CALLER_ID", "plain_text", text=SENTINEL)])
    code, output = _run_main(helper, ["classify", "--settings", str(_write_settings(legacy))])
    assert code == 1
    assert "B54_ENGINE_CALLER_REGISTRY_DISPOSITION=REFUSE_LEGACY_AUTHORITY_PRESENT" in output

    wrong_type = _settings([_binding("PADIEM_ENGINE_CALLER_REGISTRY_V1", "plain_text", text=SENTINEL)])
    code, output = _run_main(helper, ["classify", "--settings", str(_write_settings(wrong_type))])
    assert code == 1
    assert "B54_ENGINE_CALLER_REGISTRY_DISPOSITION=REFUSE_WRONG_TYPE" in output


def test_verify_cli_post_readback() -> None:
    helper = _load_helper()
    present = _settings([_binding("PADIEM_ENGINE_CALLER_REGISTRY_V1", "secret_text")])
    code, output = _run_main(helper, ["verify", "--settings", str(_write_settings(present))])
    assert code == 0
    assert "B54_ENGINE_CALLER_REGISTRY_POST_READBACK=PASS" in output
    assert "SECRET_VALUES_READ=0" in output

    absent = _settings([])
    code, output = _run_main(helper, ["verify", "--settings", str(_write_settings(absent))])
    assert code == 1
    assert "B54_ENGINE_CALLER_REGISTRY_POST_READBACK=PASS" not in output


def test_workflow_dispatch_inputs_never_accept_secret_material() -> None:
    """Requirement 9: no secret material (or provenance) enters dispatch."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "apply_engine_caller_registry_v1" in text
    assert "cloudflare_readonly" in text
    assert "repository_preflight" in text
    # Only mode/target_sha/confirmation are dispatch inputs — no raw registry,
    # no raw credential, no baseline, no currentness attestation.
    for forbidden_input in (
        "registry",
        "baseline",
        "credential",
        "secret",
        "currentness",
        "attestation",
    ):
        assert re.search(
            rf"inputs:\s*\n\s*{forbidden_input}:", text, re.IGNORECASE
        ) is None, f"dispatch input must not accept secret material: {forbidden_input}"
    # Dispatch inputs are exactly the three bounded non-secret strings.
    assert set(re.findall(r"\n      (\w+):\n        description:", text)) == {
        "mode",
        "target_sha",
        "confirmation",
    }
    assert "B62_P01_ENGINE_CREDENTIAL" in text
    assert "B54_ENGINE_CALLER_REGISTRY_V1_BASELINE" in text
    assert "B54_ENGINE_CALLER_REGISTRY_V1_BASELINE_CURRENTNESS" in text
    assert "PROVISION_B54_ENGINE_CALLER_REGISTRY_V1_FROM_EXACT_MAIN" in text


def test_workflow_apply_job_confirmation_environment_and_guards() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "inputs.mode == 'apply_engine_caller_registry_v1'" in text
    assert "environment: production" in text
    assert 'test "${CONFIRMATION}" = "PROVISION_B54_ENGINE_CALLER_REGISTRY_V1_FROM_EXACT_MAIN"' in text
    assert "B54_ENGINE_CALLER_REGISTRY_AUTHORIZATION=PASS" in text
    assert "PROVISION_REQUIRED|EXTEND_REQUIRED" in text
    assert "Refusing mutation: no trustworthy readonly disposition" in text
    assert "PREMUTATION_EXACT_MAIN_SHA=PASS" in text
    assert "SECRET_MATERIAL_IN_WORKFLOW_INPUTS=0" in text
    # All secret/provenance material arrives only through job environment vars.
    assert "ENGINE_CALLER_CREDENTIAL: ${{ secrets.B62_P01_ENGINE_CREDENTIAL }}" in text
    assert "BASELINE_REGISTRY: ${{ secrets.B54_ENGINE_CALLER_REGISTRY_V1_BASELINE }}" in text
    assert (
        "BASELINE_CURRENTNESS: ${{ secrets.B54_ENGINE_CALLER_REGISTRY_V1_BASELINE_CURRENTNESS }}"
        in text
    )
    assert "inputs.currentness" not in text
    assert "inputs.baseline" not in text
    assert "inputs.credential" not in text


def test_workflow_currentness_guard_blocks_put_until_proven() -> None:
    """Requirements 1-4 (workflow side): PUT is unreachable without YES."""
    text = WORKFLOW.read_text(encoding="utf-8")
    # The attestation secret is env-only, and the plan step consumes it.
    assert (
        "BASELINE_CURRENTNESS: ${{ secrets.B54_ENGINE_CALLER_REGISTRY_V1_BASELINE_CURRENTNESS }}"
        in text
    )
    assert "--currentness-env BASELINE_CURRENTNESS" in text
    # Fail closed before the plan when the attestation is absent on EXTEND.
    assert 'if [ "${DISPOSITION}" = "EXTEND_REQUIRED" ]; then' in text
    assert "test -n \"${BASELINE_CURRENTNESS}\"" in text
    assert 'test "${currentness}" = "YES"' in text
    assert "BASELINE_CURRENTNESS_FINGERPRINT_BOUND=YES" in text
    assert "CURRENTNESS_ATTESTATION_CONTAINS_SECRET_MATERIAL=NO" in text
    assert "BASELINE_CURRENTNESS_GUARD=PASS" in text
    # The proven flag is exported, and the PUT step requires it.
    assert 'echo "BASELINE_CURRENTNESS_PROVEN=${currentness}" >> "${GITHUB_ENV}"' in text
    put_if = re.search(
        r"- name: Provision the registry secret only when a change is required\n\s+if: \$\{\{(.+)\}\}",
        text,
    )
    assert put_if is not None
    condition = put_if.group(1)
    assert "env.B54_ENGINE_CALLER_REGISTRY_NO_OP != '1'" in condition
    assert "env.BASELINE_CURRENTNESS_PROVEN == 'YES'" in condition


def test_workflow_exact_main_guards_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in text
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in text
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in text
    assert "EXACT_MAIN_GUARD=PASS" in text
    assert "READONLY_EXACT_MAIN_SHA=PASS" in text
    assert "set -euo pipefail" in text


def test_workflow_provisions_engine_secret_gated_on_plan_no_op() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workers/scripts/${ENGINE_WORKER}/secrets" in text
    assert "ENGINE_WORKER: padiem-ai-engine" in text
    assert "PADIEM_ENGINE_CALLER_REGISTRY_V1" in text
    assert "B54_ENGINE_CALLER_REGISTRY_NO_OP" in text
    assert "env.B54_ENGINE_CALLER_REGISTRY_NO_OP != '1'" in text
    assert "rm -f" in text
    assert "SECRET_VALUE_EMITTED=0" in text
    assert "RAW_SECRET_OUTPUT=0" in text
    assert "RAW_REGISTRY_OUTPUT=0" in text
    assert "SECRET_REUSE_ONLY_NO_RECREATION=PASS" in text
    assert "B54_ENGINE_CALLER_REGISTRY=PROVISIONED" in text
    assert "B54_ENGINE_CALLER_REGISTRY_POST_READBACK=PASS" in text
    assert "SKIPPED_ALREADY_COMPATIBLE" in text


def test_workflow_never_touches_b62_live_config_or_padiem_chat() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "b62-claw-live-config-activation-gate" not in text
    assert "CONFIRM_ACTIVATE_B62_CLAW_LIVE_CONFIG" not in text
    assert "CONFIRM_ROLLBACK_B62_CLAW_LIVE_CONFIG" not in text
    # Never mutates padiem-chat secrets and never reuses B62 env patterns.
    assert "padiem-chat/secrets" not in text
    assert '"name": "P01_ENGINE_CREDENTIAL"' not in text
    assert "B62_WORKER" not in text
    # Pull-request paths must not drag in the B62 workflow.
    pr_paths = re.search(r"pull_request:\s*\n\s*paths:\n((?:\s+- .*\n)+)", text)
    assert pr_paths is not None
    for line in pr_paths.group(1).splitlines():
        assert "b62" not in line


def test_workflow_never_deploys_engine_worker() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("pywrangler deploy", "wrangler deploy", "d1 execute", "deploy-production-engine"):
        assert forbidden not in text, f"provision gate must not contain: {forbidden}"


def test_readonly_job_is_get_only_name_type_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workers/scripts/${ENGINE_WORKER}/settings" in text
    assert "GET_ONLY=PASS" in text
    assert "BINDING_NAME_AND_TYPE_ONLY=YES" in text
    assert "SECRET_VALUES_READ=0" in text
    assert "CLOUDFLARE_MUTATION=0" in text
    assert "PRODUCTION_MUTATION=0" in text
    # The only mutation endpoint in the file targets the Engine secret.
    assert text.count("workers/scripts/${ENGINE_WORKER}/secrets") == 1


if __name__ == "__main__":
    test_script_constants_exact()
    test_authority_dispositions()
    test_parse_baseline_requires_b61_contract()
    test_merge_appends_b54_and_preserves_all_existing_verbatim()
    test_merge_existing_compatible_b54_is_no_op()
    test_merge_existing_incompatible_b54_fails_closed()
    test_greenfield_payload_is_isolated_single_caller()
    test_merged_payload_parses_and_authenticates_with_engine_parser()
    test_currentness_attestation_canonical_form_contract()
    test_currentness_binds_exact_baseline_fingerprint_and_caller_count()
    test_extend_without_currentness_proof_fails_closed()
    test_extend_with_invalid_currentness_proof_fails_closed()
    test_extend_stale_or_future_currentness_cannot_reach_put()
    test_extend_with_valid_currentness_is_allowed()
    test_currentness_rejects_raw_registry_material()
    test_currentness_rejects_raw_credential_material()
    test_plan_extend_path_evidence_and_never_emits_secrets()
    test_plan_extend_no_op_when_b54_already_compatible()
    test_plan_extend_requires_baseline_secret()
    test_plan_greenfield_isolated_and_baseline_forbidden()
    test_classify_cli_dispositions()
    test_verify_cli_post_readback()
    test_workflow_dispatch_inputs_never_accept_secret_material()
    test_workflow_apply_job_confirmation_environment_and_guards()
    test_workflow_currentness_guard_blocks_put_until_proven()
    test_workflow_exact_main_guards_fail_closed()
    test_workflow_provisions_engine_secret_gated_on_plan_no_op()
    test_workflow_never_touches_b62_live_config_or_padiem_chat()
    test_workflow_never_deploys_engine_worker()
    test_readonly_job_is_get_only_name_type_only()
    print("B54_ENGINE_CALLER_REGISTRY_V1_PROVISION_GATE_TESTS=PASS")
