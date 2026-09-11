"""Contract tests for the B54 Engine caller-registry OVERLAY rotation gate.

Proves statically and locally (no network) that the gate:
  1. is dispatch-only for mutation (pull requests run only static tests);
  2. requires the exact confirmation phrase and the production environment;
  3. carries exact-main assertions fail-closed before any live read/mutation;
  4. never accepts secret material through workflow_dispatch inputs — the new
     Claw credential arrives only as the ``B62_P01_ENGINE_CREDENTIAL`` job env
     secret, and the private baseline / currentness attestation are NEVER
     referenced or consumed by this gate (they belong to the provisioning gate);
  5. mutates ONLY ``PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY``: the PUT body
     name is structurally fixed to the overlay and the workflow additionally
     asserts it before the PUT, so a base V1 rewrite is impossible;
  6. refuses mutation unless the SERVED version shows base V1 and overlay both
     ``PRESENT:secret_text`` with the legacy trio absent (overlay creation, base
     absence, wrong types, and legacy-trio presence all refuse for review);
  7. builds the canonical single-caller overlay payload with the RAW credential
     (never pre-hashed), enforcing the Engine 32..512 UTF-8 byte gate before any
     output is written, and round-trips it through the Engine's own
     ``parse_caller_registry_v1_overlay`` / ``authenticate_request`` contract —
     including the additive-overlay fail-closed rules (overlay requires the V1
     base; overlay must not duplicate a base caller id);
  8. proves pre/post readback on the served version detail
     (``result.resources.bindings``), never the settings plane: a settings-plane
     payload and a version-id mismatch both fail closed;
  9. emits only bounded, non-secret evidence when the Engine secret PUT fails
     (HTTP status, boolean success, integer codes; never ``.errors[].message``
     or the response body) and deletes the response temp file;
 10. never prints a credential, overlay, registry, secret value, secret length
     (a single-caller overlay's serialized length is credential-adjacent), or
     secret hash on any code path;
 11. never deploys the Engine worker, never touches the B62 live-config
     workflow or the ``padiem-chat`` worker.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-engine-caller-registry-overlay-rotation-gate.yml"
HELPER = ROOT / ".github/scripts/b54_engine_caller_registry_overlay_rotation.py"

SENTINEL = "sentinel-raw-value-must-never-appear"
CREDENTIAL_ENV = "B54_TEST_OVERLAY_ROTATION_CREDENTIAL"
CONFIRM_PHRASE = "ROTATE_B54_KAGENT_ENGINE_OVERLAY_FROM_EXACT_MAIN"
BASE_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
OVERLAY_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY"
LEGACY_TRIO_NAMES = (
    "PADIEM_ENGINE_CALLER_ID",
    "PADIEM_ENGINE_CALLER_SECRET",
    "PADIEM_ENGINE_ALLOWED_APPS",
)
VERSION_ID = "aaaaaaaa-1111-2222-3333-444444444444"


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "b54_engine_caller_registry_overlay_rotation", HELPER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_engine_identity():
    """Load the Engine overlay parser without importing the heavy app package."""
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


def _version_detail(bindings: list[dict[str, object]], version_id: str = VERSION_ID) -> dict:
    """Canonical served version-detail shape (NOT the settings plane)."""
    return {
        "success": True,
        "result": {"id": version_id, "resources": {"bindings": bindings}},
    }


def _settings_plane(bindings: list[dict[str, object]]) -> dict:
    """Mutable settings-plane shape: must never pass as served-version proof."""
    return {"success": True, "result": {"bindings": bindings}}


def _run_main(helper, argv: list[str]) -> tuple[int, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = helper.main(argv)
    return code, stdout.getvalue() + stderr.getvalue()


def _run_main_split(helper, argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = helper.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def _write_json_file(payload: object, prefix: str = "b54-overlay-test-") -> Path:
    tmp = tempfile.mkdtemp(prefix=prefix)
    path = Path(tmp) / "payload.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_response_file(body: str) -> Path:
    tmp = tempfile.mkdtemp(prefix="b54-overlay-put-failure-")
    path = Path(tmp) / "cloudflare-response.json"
    path.write_text(body, encoding="utf-8")
    return path


@contextlib.contextmanager
def _env(**values: str | None):
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


def _rotation_states(
    base: str = "PRESENT:secret_text",
    overlay: str = "PRESENT:secret_text",
    legacy: tuple[str, str, str] = ("ABSENT", "ABSENT", "ABSENT"),
) -> dict[str, str]:
    states = {BASE_NAME: base, OVERLAY_NAME: overlay}
    states.update(dict(zip(LEGACY_TRIO_NAMES, legacy)))
    return states


# ---------------------------------------------------------------------------
# Constants and pure logic
# ---------------------------------------------------------------------------


def _assert_no_provisioning_material_consumption(text: str) -> None:
    """Baseline/currentness may only appear as negative prose or the refusal marker."""
    assert "B54_ENGINE_CALLER_REGISTRY_V1_BASELINE" not in text
    assert "verify_currentness" not in text
    assert "currentness_attestation" not in text
    assert "currentness-proof" not in text and "currentness_proof" not in text
    lowered = text.lower()
    lines = text.splitlines()
    for match in re.finditer(r"currentness|baseline", lowered):
        window = lowered[max(0, match.start() - 160): match.end() + 160]
        ok = "never" in window or "not " in window or "consumed=0" in window
        assert ok, lines[lowered[: match.start()].count("\n")]


def test_script_constants_exact() -> None:
    helper = _load_helper()
    assert helper.ENGINE_WORKER == "padiem-ai-engine"
    assert helper.REGISTRY_SECRET_NAME == BASE_NAME
    assert helper.OVERLAY_SECRET_NAME == OVERLAY_NAME
    assert helper.REQUIRED_BINDING_TYPE == "secret_text"
    assert set(helper.LEGACY_TRIO_NAMES) == set(LEGACY_TRIO_NAMES)
    assert helper.CALLER_ID == "b54-kagent"
    assert helper.ALLOWED_APP_IDS == ("b54-padiem-claw",)
    assert helper.OVERLAY_VERSION == 1
    assert helper.MIN_CREDENTIAL_BYTES == 32
    assert helper.MAX_CREDENTIAL_BYTES == 512
    assert helper.MAX_CALLER_APP_IDS == 32
    assert helper.MAX_CALLER_REGISTRY_V1_BYTES == 524288
    # The rotation never consumes provisioning-gate material.
    _assert_no_provisioning_material_consumption(HELPER.read_text(encoding="utf-8"))
    assert "BASELINE_OR_CURRENTNESS_CONSUMED=0" in HELPER.read_text(encoding="utf-8")


def test_rotation_dispositions() -> None:
    helper = _load_helper()
    assert helper.rotation_disposition(_rotation_states()) == "ROTATION_REQUIRED"
    assert (
        helper.rotation_disposition(_rotation_states(base="ABSENT"))
        == "REFUSE_BASE_V1_ABSENT"
    )
    assert (
        helper.rotation_disposition(_rotation_states(base="PRESENT:plain_text"))
        == "REFUSE_BASE_V1_WRONG_TYPE"
    )
    assert (
        helper.rotation_disposition(_rotation_states(overlay="ABSENT"))
        == "REFUSE_OVERLAY_ABSENT"
    )
    assert (
        helper.rotation_disposition(_rotation_states(overlay="PRESENT:plain_text"))
        == "REFUSE_OVERLAY_WRONG_TYPE"
    )
    # Any legacy trio member present alongside V1 authority refuses mutation.
    for slot in range(3):
        legacy = ["ABSENT", "ABSENT", "ABSENT"]
        legacy[slot] = "PRESENT:secret_text"
        assert (
            helper.rotation_disposition(_rotation_states(legacy=tuple(legacy)))
            == "REFUSE_LEGACY_TRIO_PRESENT"
        )
    # Base absence outranks every later check (overlay path fails closed).
    assert (
        helper.rotation_disposition(
            _rotation_states(base="ABSENT", legacy=("PRESENT:secret_text",) * 3)
        )
        == "REFUSE_BASE_V1_ABSENT"
    )


def test_build_overlay_payload_is_canonical_single_caller() -> None:
    helper = _load_helper()
    credential = "n" * 40
    payload = helper.build_overlay_payload(credential=credential)
    assert payload == {
        "version": 1,
        "caller": {
            "caller_id": "b54-kagent",
            "credential": credential,
            "allowed_app_ids": ["b54-padiem-claw"],
        },
    }
    # Credential byte boundaries are enforced before any payload is returned.
    for bad in ("", "x" * 31, "x" * 513):
        try:
            helper.build_overlay_payload(credential=bad)
        except helper.OverlayRotationError:
            continue
        raise AssertionError(f"credential of invalid length must fail closed: {len(bad)}")
    helper.build_overlay_payload(credential="x" * 32)
    helper.build_overlay_payload(credential="x" * 512)


def test_overlay_shape_rejects_noncanonical_payloads() -> None:
    helper = _load_helper()
    good = helper.build_overlay_payload(credential="n" * 40)
    assert helper._check_overlay_shape(good) == good
    mutations = {
        "extra top-level key": {**good, "callers": []},
        "missing caller": {"version": 1},
        "bool version": {"version": True, "caller": good["caller"]},
        "version 2": {"version": 2, "caller": good["caller"]},
        "entry extra key": {
            "version": 1,
            "caller": {**good["caller"], "role": "admin"},
        },
        "entry missing apps": {
            "version": 1,
            "caller": {"caller_id": "b54-kagent", "credential": "n" * 40},
        },
        "empty app list": {
            "version": 1,
            "caller": {
                "caller_id": "b54-kagent",
                "credential": "n" * 40,
                "allowed_app_ids": [],
            },
        },
        "duplicate apps": {
            "version": 1,
            "caller": {
                "caller_id": "b54-kagent",
                "credential": "n" * 40,
                "allowed_app_ids": ["a", "a"],
            },
        },
        "unsafe caller id": {
            "version": 1,
            "caller": {
                "caller_id": "-bad id",
                "credential": "n" * 40,
                "allowed_app_ids": ["b54-padiem-claw"],
            },
        },
        "non-string credential": {
            "version": 1,
            "caller": {
                "caller_id": "b54-kagent",
                "credential": 12345,
                "allowed_app_ids": ["b54-padiem-claw"],
            },
        },
        "not a dict": ["version", "caller"],
    }
    for label, payload in mutations.items():
        try:
            helper._check_overlay_shape(payload)
        except helper.OverlayRotationError:
            continue
        raise AssertionError(f"non-canonical overlay accepted: {label}")


def test_put_body_targets_overlay_only() -> None:
    helper = _load_helper()
    payload = helper.build_overlay_payload(credential="n" * 40)
    body = helper.build_overlay_put_body(payload)
    assert body["name"] == OVERLAY_NAME
    assert body["name"] != BASE_NAME
    assert body["type"] == "secret_text"
    assert json.loads(body["text"]) == payload


# ---------------------------------------------------------------------------
# Engine round-trip: the produced overlay authenticates with the Engine's own
# parser under the additive-overlay contract.
# ---------------------------------------------------------------------------


def test_overlay_round_trips_through_engine_parser_and_authentication() -> None:
    helper = _load_helper()
    identity = _load_engine_identity()
    b61_cred = "b" * 40
    new_cred = "n" * 40
    base_registry = {
        "version": 1,
        "callers": [
            {
                "caller_id": "storymemory-b61",
                "credential": b61_cred,
                "allowed_app_ids": ["b61"],
            }
        ],
    }
    overlay = helper.build_overlay_payload(credential=new_cred)
    body = helper.build_overlay_put_body(overlay)
    env = type(
        "Env",
        (),
        {
            identity.CALLER_REGISTRY_V1_ENV: json.dumps(
                base_registry, separators=(",", ":",)
            ),
            identity.CALLER_REGISTRY_V1_OVERLAY_ENV: body["text"],
        },
    )()

    # The Engine's own overlay parser accepts the exact serialized PUT text.
    parsed = identity.parse_caller_registry_v1_overlay(body["text"])
    assert parsed.caller_id == "b54-kagent"
    assert parsed.allowed_app_ids == ("b54-padiem-claw",)
    assert parsed.credential_sha256 == identity.caller_secret_digest(new_cred)

    # b54-kagent authenticates with the RAW new credential (never pre-hashed).
    identity.authenticate_request(
        env=env,
        headers={
            identity.CALLER_ID_HEADER: "b54-kagent",
            identity.CALLER_CREDENTIAL_HEADER: new_cred,
        },
        requested_app_id="b54-padiem-claw",
    )
    # The pre-rotation credential no longer authenticates.
    try:
        identity.authenticate_request(
            env=env,
            headers={
                identity.CALLER_ID_HEADER: "b54-kagent",
                identity.CALLER_CREDENTIAL_HEADER: "o" * 40,
            },
            requested_app_id="b54-padiem-claw",
        )
    except identity.ServiceIdentityError as exc:
        assert exc.code == "service_authentication_failed"
    else:
        raise AssertionError("stale credential must not authenticate")
    # A pre-hashed value is NOT the accepted credential.
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
    else:
        raise AssertionError("pre-hashed credential must not authenticate")
    # The overlay is additive: the untouched base caller still authenticates,
    # and a wrong app for the overlay caller fails closed.
    identity.authenticate_request(
        env=env,
        headers={
            identity.CALLER_ID_HEADER: "storymemory-b61",
            identity.CALLER_CREDENTIAL_HEADER: b61_cred,
        },
        requested_app_id="b61",
    )
    try:
        identity.authenticate_request(
            env=env,
            headers={
                identity.CALLER_ID_HEADER: "b54-kagent",
                identity.CALLER_CREDENTIAL_HEADER: new_cred,
            },
            requested_app_id="b61",
        )
    except identity.ServiceIdentityError:
        pass
    else:
        raise AssertionError("overlay caller must not widen apps")


def test_engine_overlay_fail_closed_rules_hold_for_gate_payload() -> None:
    helper = _load_helper()
    identity = _load_engine_identity()
    overlay_text = helper.build_overlay_put_body(
        helper.build_overlay_payload(credential="n" * 40)
    )["text"]

    # Overlay configured while the V1 base is absent fails closed.
    solo = type("Env", (), {identity.CALLER_REGISTRY_V1_OVERLAY_ENV: overlay_text})()
    try:
        identity.authenticate_request(
            env=solo,
            headers={
                identity.CALLER_ID_HEADER: "b54-kagent",
                identity.CALLER_CREDENTIAL_HEADER: "n" * 40,
            },
            requested_app_id="b54-padiem-claw",
        )
    except identity.ServiceIdentityError as exc:
        assert exc.code == "invalid_caller_registry"
    else:
        raise AssertionError("overlay without the V1 base must fail closed")

    # Overlay duplicating a base caller id fails closed before authentication.
    base_with_dup = {
        "version": 1,
        "callers": [
            {
                "caller_id": "b54-kagent",
                "credential": "d" * 40,
                "allowed_app_ids": ["b54-padiem-claw"],
            }
        ],
    }
    dup_env = type(
        "Env",
        (),
        {
            identity.CALLER_REGISTRY_V1_ENV: json.dumps(base_with_dup),
            identity.CALLER_REGISTRY_V1_OVERLAY_ENV: overlay_text,
        },
    )()
    try:
        identity.authenticate_request(
            env=dup_env,
            headers={
                identity.CALLER_ID_HEADER: "b54-kagent",
                identity.CALLER_CREDENTIAL_HEADER: "n" * 40,
            },
            requested_app_id="b54-padiem-claw",
        )
    except identity.ServiceIdentityError as exc:
        assert exc.code == "duplicate_service_caller"
    else:
        raise AssertionError("overlay duplicating a base caller must fail closed")


# ---------------------------------------------------------------------------
# classify CLI (served-version detail, NAME/TYPE only)
# ---------------------------------------------------------------------------


def test_classify_cli_rotation_required() -> None:
    helper = _load_helper()
    detail = _version_detail(
        [
            _binding(BASE_NAME, "secret_text", text=SENTINEL),
            _binding(OVERLAY_NAME, "secret_text", text=SENTINEL),
            _binding("PADIEM_AI_STUFF", "plain_text", text="irrelevant"),
        ]
    )
    code, output = _run_main(
        helper,
        [
            "classify",
            "--version-detail",
            str(_write_json_file(detail)),
            "--active-version",
            VERSION_ID,
        ],
    )
    assert code == 0
    assert "B54_ENGINE_OVERLAY_ROTATION_DISPOSITION=ROTATION_REQUIRED" in output
    assert f"AUTHORITY_STATE {BASE_NAME}=PRESENT:secret_text" in output
    assert f"AUTHORITY_STATE {OVERLAY_NAME}=PRESENT:secret_text" in output
    for name in LEGACY_TRIO_NAMES:
        assert f"AUTHORITY_STATE {name}=ABSENT" in output
    assert "SERVED_VERSION_READBACK=YES" in output
    assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in output
    assert "BINDING_NAME_AND_TYPE_ONLY=YES" in output
    assert "SECRET_VALUES_READ=0" in output
    assert "CLOUDFLARE_MUTATION=0" in output
    assert SENTINEL not in output


def test_classify_cli_refusals() -> None:
    helper = _load_helper()

    def classify(
        bindings: list[dict],
        version_id: str = VERSION_ID,
        active_version: str | None = None,
    ) -> tuple[int, str]:
        detail = _version_detail(bindings, version_id=version_id)
        return _run_main(
            helper,
            [
                "classify",
                "--version-detail",
                str(_write_json_file(detail)),
                "--active-version",
                active_version if active_version is not None else version_id,
            ],
        )

    code, output = classify([_binding(OVERLAY_NAME, "secret_text")])
    assert code == 1
    assert "B54_ENGINE_OVERLAY_ROTATION_DISPOSITION=REFUSE_BASE_V1_ABSENT" in output

    code, output = classify(
        [_binding(BASE_NAME, "secret_text"), _binding(OVERLAY_NAME, "plain_text")]
    )
    assert code == 1
    assert "B54_ENGINE_OVERLAY_ROTATION_DISPOSITION=REFUSE_OVERLAY_WRONG_TYPE" in output

    code, output = classify(
        [
            _binding(BASE_NAME, "secret_text"),
            _binding(OVERLAY_NAME, "secret_text"),
            _binding("PADIEM_ENGINE_CALLER_ID", "secret_text"),
        ]
    )
    assert code == 1
    assert "B54_ENGINE_OVERLAY_ROTATION_DISPOSITION=REFUSE_LEGACY_TRIO_PRESENT" in output

    # A settings-plane payload is never accepted as served-version proof.
    settings = _settings_plane(
        [_binding(BASE_NAME, "secret_text"), _binding(OVERLAY_NAME, "secret_text")]
    )
    code, output = _run_main(
        helper,
        [
            "classify",
            "--version-detail",
            str(_write_json_file(settings)),
            "--active-version",
            VERSION_ID,
        ],
    )
    assert code == 1
    assert "B54_ENGINE_OVERLAY_ROTATION_CLASSIFY=FAIL" in output
    assert "DISPOSITION=ROTATION_REQUIRED" not in output

    # Version-detail identity that does not match the active version fails closed.
    code, output = classify(
        [_binding(BASE_NAME, "secret_text"), _binding(OVERLAY_NAME, "secret_text")],
        version_id="ffffffff-9999-9999-9999-999999999999",
        active_version=VERSION_ID,
    )
    assert code == 1
    assert "B54_ENGINE_OVERLAY_ROTATION_CLASSIFY=FAIL" in output


# ---------------------------------------------------------------------------
# plan CLI
# ---------------------------------------------------------------------------


def _run_plan(helper, output: Path) -> tuple[int, str]:
    return _run_main_split_out(
        helper, ["plan", "--credential-env", CREDENTIAL_ENV, "--output", str(output)]
    )


def _run_main_split_out(helper, argv: list[str]) -> tuple[int, str]:
    code, stdout, stderr = _run_main_split(helper, argv)
    return code, stdout + stderr


def test_plan_cli_writes_overlay_body_and_never_emits_the_credential() -> None:
    helper = _load_helper()
    credential = "s3cret-material-" + "z" * 30
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        with _env(**{CREDENTIAL_ENV: credential}):
            code, output = _run_plan(helper, out)
        assert code == 0
        assert "B54_ENGINE_OVERLAY_ROTATION_PLAN=PASS" in output
        assert f"B54_ENGINE_OVERLAY_TARGET_NAME={OVERLAY_NAME}" in output
        assert "OVERLAY_CALLER_ID=b54-kagent" in output
        assert "OVERLAY_ALLOWED_APP_IDS=b54-padiem-claw" in output
        assert "CREDENTIAL_BYTES_IN_BOUNDS=PASS" in output
        assert "RAW_CREDENTIAL_PREHASHED=NO" in output
        assert "ENGINE_BASE_V1_MUTATION=0" in output
        assert "LEGACY_TRIO_MUTATION=0" in output
        assert "UNRELATED_SECRET_MUTATION=0" in output
        assert "BASELINE_OR_CURRENTNESS_CONSUMED=0" in output
        # The credential value, its length, and any digest never appear.
        assert credential not in output
        assert str(len(credential)) not in output
        assert "SECRET_VALUE_OUTPUT=0" in output
        assert "SECRET_LENGTH_OUTPUT=0" in output
        assert "SECRET_HASH_OUTPUT=0" in output
        body = json.loads(out.read_text(encoding="utf-8"))
    assert body["name"] == OVERLAY_NAME
    assert body["type"] == "secret_text"
    payload = json.loads(body["text"])
    assert payload["caller"]["credential"] == credential
    assert payload["caller"]["caller_id"] == "b54-kagent"
    assert payload["caller"]["allowed_app_ids"] == ["b54-padiem-claw"]


def test_plan_cli_fails_closed_on_bad_credential_and_existing_output() -> None:
    helper = _load_helper()
    for label, value in {
        "unset": None,
        "blank": "",
        "too short": "x" * 31,
        "too long": "x" * 513,
    }.items():
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "put-body.json"
            with _env(**{CREDENTIAL_ENV: value}):
                code, output = _run_plan(helper, out)
            assert code == 1, label
            assert "B54_ENGINE_OVERLAY_ROTATION_PLAN=FAIL" in output, label
            assert "RAW_SECRET_OUTPUT=0" in output, label
            assert not out.exists(), label

    # An existing output path is refused before the credential is even read.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "put-body.json"
        out.write_text("pre-existing", encoding="utf-8")
        with _env(**{CREDENTIAL_ENV: "n" * 40}):
            code, output = _run_plan(helper, out)
        assert code == 1
        assert out.read_text(encoding="utf-8") == "pre-existing"


# ---------------------------------------------------------------------------
# verify CLI (post-mutation served-version readback)
# ---------------------------------------------------------------------------


def test_verify_cli_post_readback() -> None:
    helper = _load_helper()
    detail = _version_detail(
        [
            _binding(BASE_NAME, "secret_text", text=SENTINEL),
            _binding(OVERLAY_NAME, "secret_text", text=SENTINEL),
        ]
    )
    code, output = _run_main(
        helper,
        [
            "verify",
            "--version-detail",
            str(_write_json_file(detail)),
            "--active-version",
            VERSION_ID,
        ],
    )
    assert code == 0
    assert f"ENGINE_SERVED_VERSION_ID={VERSION_ID}" in output
    assert "ENGINE_V1_SERVED_BINDING=PRESENT:secret_text" in output
    assert "ENGINE_OVERLAY_SERVED_BINDING=PRESENT:secret_text" in output
    assert "LEGACY_TRIO_SERVED_BINDING=ABSENT" in output
    assert "B54_ENGINE_OVERLAY_ROTATION_POST_READBACK=PASS" in output
    assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in output
    assert "RUNTIME_SUCCESS=UNPROVEN_PENDING_PHASE_A" in output
    assert SENTINEL not in output

    # Overlay missing from the served version fails the post-readback.
    missing = _version_detail([_binding(BASE_NAME, "secret_text")])
    code, output = _run_main(
        helper,
        [
            "verify",
            "--version-detail",
            str(_write_json_file(missing)),
            "--active-version",
            VERSION_ID,
        ],
    )
    assert code == 1
    assert "B54_ENGINE_OVERLAY_ROTATION_VERIFY=FAIL" in output

    # Legacy trio reappearing on the served version fails the post-readback.
    legacy = _version_detail(
        [
            _binding(BASE_NAME, "secret_text"),
            _binding(OVERLAY_NAME, "secret_text"),
            _binding("PADIEM_ENGINE_CALLER_SECRET", "secret_text"),
        ]
    )
    code, output = _run_main(
        helper,
        [
            "verify",
            "--version-detail",
            str(_write_json_file(legacy)),
            "--active-version",
            VERSION_ID,
        ],
    )
    assert code == 1
    assert "B54_ENGINE_OVERLAY_ROTATION_VERIFY=FAIL" in output


# ---------------------------------------------------------------------------
# Bounded PUT-failure evidence
# ---------------------------------------------------------------------------


def test_failure_evidence_never_emits_cloudflare_message_text() -> None:
    helper = _load_helper()
    sentinel = "sentinel-error-message-must-never-appear"
    bodies = {
        "message in errors": json.dumps(
            {"success": False, "errors": [{"code": 10000, "message": sentinel}]}
        ),
        "sentinel in many fields": json.dumps(
            {
                "success": False,
                "errors": [{"code": 10000, "message": sentinel, "meta": {"detail": sentinel}}],
                "messages": [sentinel],
                "result": sentinel,
            }
        ),
        "credential-shaped code": json.dumps(
            {"success": False, "errors": [{"code": sentinel, "message": sentinel}]}
        ),
        "non-json body": sentinel,
    }
    for label, body in bodies.items():
        path = _write_response_file(body)
        code, stdout, stderr = _run_main_split(
            helper, ["failure-evidence", "--response", str(path), "--http-status", "403"]
        )
        assert code == 0, label
        assert sentinel not in stdout, label
        assert sentinel not in stderr, label
        assert "CLOUDFLARE_HTTP_STATUS=403" in stdout, label
        assert "CLOUDFLARE_ERROR_MESSAGE_OUTPUT=0" in stdout, label
        assert "CLOUDFLARE_RESPONSE_BODY_OUTPUT=0" in stdout, label
        assert "RAW_SECRET_OUTPUT=0" in stdout, label
        assert "RAW_OVERLAY_OUTPUT=0" in stdout, label
        assert "SECRET_VALUE_OUTPUT=0" in stdout, label
        assert not path.exists(), label

    # Non-integer codes are dropped; only bounded integer codes are emitted.
    path = _write_response_file(
        json.dumps(
            {
                "success": False,
                "errors": [{"code": True}, {"code": "1001"}, {"code": 1003}],
            }
        )
    )
    _, stdout, _ = _run_main_split(
        helper, ["failure-evidence", "--response", str(path), "--http-status", "400"]
    )
    assert "CLOUDFLARE_ERROR_CODES=1003" in stdout
    assert "CLOUDFLARE_ERROR_CODE_COUNT=1" in stdout

    # A non-numeric HTTP status is reported as bounded ``unknown``.
    path = _write_response_file(json.dumps({"success": False, "errors": []}))
    _, stdout, _ = _run_main_split(
        helper, ["failure-evidence", "--response", str(path), "--http-status", ""]
    )
    assert "CLOUDFLARE_HTTP_STATUS=unknown" in stdout

    # A missing response still yields bounded evidence and safe cleanup.
    missing = Path(tempfile.mkdtemp(prefix="b54-overlay-put-failure-")) / "absent.json"
    code, stdout, _ = _run_main_split(
        helper, ["failure-evidence", "--response", str(missing), "--http-status", "500"]
    )
    assert code == 0
    assert "CLOUDFLARE_ERROR_BODY_PARSABLE=NO" in stdout
    assert "RESPONSE_TEMP_CLEANUP=PASS" in stdout


def test_helper_never_selects_message_fields() -> None:
    script = HELPER.read_text(encoding="utf-8")
    for forbidden_selection in ('"message"', "'message'", '"messages"', "'messages'"):
        assert forbidden_selection not in script, forbidden_selection


# ---------------------------------------------------------------------------
# Static workflow contract
# ---------------------------------------------------------------------------


def test_workflow_dispatch_inputs_never_accept_secret_material() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "repository_preflight" in text
    assert "cloudflare_readonly" in text
    assert "apply_overlay_credential_rotation" in text
    # Dispatch inputs are exactly the three bounded non-secret strings.
    assert set(re.findall(r"\n      (\w+):\n        description:", text)) == {
        "mode",
        "target_sha",
        "confirmation",
    }
    for forbidden_input in ("credential", "secret", "registry", "overlay", "baseline"):
        assert re.search(
            rf"inputs:\s*\n\s*{forbidden_input}:", text, re.IGNORECASE
        ) is None, forbidden_input
    assert "inputs.credential" not in text
    assert "inputs.overlay" not in text


def test_workflow_apply_job_confirmation_and_guards() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert CONFIRM_PHRASE in text
    assert 'test "${CONFIRMATION}" = ' in text
    assert "environment: production" in text
    assert "inputs.mode == 'apply_overlay_credential_rotation'" in text
    assert "B54_ENGINE_OVERLAY_ROTATION_AUTHORIZATION=PASS" in text
    assert "Refusing mutation: no trustworthy readonly served-version disposition" in text
    assert "PREMUTATION_EXACT_MAIN_SHA=PASS" in text
    assert "SECRET_MATERIAL_IN_WORKFLOW_INPUTS=0" in text
    # The credential arrives only as the Actions secret in the job env.
    assert "ENGINE_CALLER_CREDENTIAL: ${{ secrets.B62_P01_ENGINE_CREDENTIAL }}" in text
    # The provisioning gate's private material is NEVER referenced here.
    _assert_no_provisioning_material_consumption(text)
    # Disposition from the readonly job gates the apply job.
    assert "disposition: ${{ steps.classify.outputs.disposition }}" in text
    assert 'DISPOSITION: ${{ needs.cloudflare-readonly.outputs.disposition }}' in text


def test_workflow_exact_main_guards_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in text
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in text
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in text
    assert "EXACT_MAIN_GUARD=PASS" in text
    assert "READONLY_EXACT_MAIN_SHA=PASS" in text
    assert "set -euo pipefail" in text


def test_workflow_uses_served_version_never_settings_plane() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workers/scripts/${ENGINE_WORKER}/deployments" in text
    assert "/versions/${active_version}" in text
    assert "b54_engine_served_version_guard.py resolve-active" in text
    assert "--version-detail" in text
    assert "--active-version" in text
    # The mutable settings plane is never consulted for authority proof.
    assert "/settings" not in text
    assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in text
    assert "SERVED_VERSION_READBACK=YES" in text
    # PRE-MUTATION: deployments shape is pinned and the served version id is
    # captured before the single overlay PUT.
    assert "jq -e '.success == true'" in text
    assert "(.result.deployments | type == \"array\" and length > 0)" in text
    assert "(.result.deployments[0].versions | type == \"array\" and length == 1)" in text
    assert ".result.deployments[0].versions[0].percentage == 100" in text
    assert "PREMUTATION_SERVED_VERSION_ID" in text
    assert 'echo "PREMUTATION_SERVED_VERSION_ID=${active_version}" >> "${GITHUB_ENV}"' in text
    # POST-MUTATION: poll deployments to a single 100-percent version, capture
    # the post id, and emit whether the secret PUT rotated the served version.
    assert "POSTMUTATION_SERVED_VERSION_ID" in text
    assert "SERVED_VERSION_CHANGED_BY_SECRET_PUT=YES" in text
    assert "SERVED_VERSION_CHANGED_BY_SECRET_PUT=NO" in text
    # Neither a settings GET, a PUT response, nor a version-upload/latest read
    # is accepted as authority proof.
    assert "VERSION_UPLOAD_LATEST_READ_ACCEPTED=NO" in text
    assert "DEPLOYMENTS_SHAPE_GUARD=PASS" in text
    # The guard/verify runs against the exact post-mutation served version.
    assert 'active_version="${POSTMUTATION_SERVED_VERSION_ID}"' in text
    # Pre-mutation capture must precede the PUT, and the post-mutation
    # readback must follow it.
    pre_pos = text.index("PREMUTATION_SERVED_VERSION_ID=${active_version}")
    put_pos = text.index("-X PUT")
    post_pos = text.index("POSTMUTATION_SERVED_VERSION_ID")
    assert pre_pos < put_pos < post_pos


def test_workflow_put_targets_overlay_only_and_never_base_v1() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workers/scripts/${ENGINE_WORKER}/secrets" in text
    # Exactly one mutation endpoint: the overlay secret PUT.
    assert text.count("workers/scripts/${ENGINE_WORKER}/secrets") == 1
    assert '-X PUT' in text
    # The plan step structurally pins the PUT body to the overlay name.
    assert 'jq -e \'.name == "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY"' in text
    assert 'jq -e \'.name != "PADIEM_ENGINE_CALLER_REGISTRY_V1"\'' in text
    assert "B54_ENGINE_OVERLAY_TARGET_GUARD=PASS" in text
    assert "--credential-env ENGINE_CALLER_CREDENTIAL" in text
    assert "B54_ENGINE_OVERLAY_ROTATION=APPLIED" in text
    assert "ENGINE_BASE_V1_MUTATION=0" in text
    assert "LEGACY_TRIO_MUTATION=0" in text
    assert "UNRELATED_SECRET_MUTATION=0" in text
    # No wrangler/deploy path exists in this gate.
    for forbidden in ("pywrangler deploy", "wrangler deploy", "wrangler secret"):
        assert forbidden not in text, forbidden


def test_workflow_readonly_job_is_get_only_and_refuses_non_rotation_states() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "curl -fsS" in text
    assert "GET_ONLY=PASS" in text
    assert "BINDING_NAME_AND_TYPE_ONLY=YES" in text
    assert "SECRET_VALUES_READ=0" in text
    assert "CLOUDFLARE_MUTATION=0" in text
    assert "PRODUCTION_MUTATION=0" in text
    assert 'if [ "${disposition}" != "ROTATION_REQUIRED" ]; then' in text
    assert "Human review required before any mutation" in text


def test_workflow_bounded_failure_evidence_wiring() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    code_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    code_text = "\n".join(code_lines)
    assert re.search(r"(?i)\bmessages?\b", code_text) is None, (
        "workflow code must never select or print Cloudflare message text"
    )
    assert "failure-evidence" in text
    assert '--response "${response}"' in text
    assert '--http-status "${http_status}"' in text
    assert "CLOUDFLARE_ERROR_MESSAGE_OUTPUT=0" in text
    assert "CLOUDFLARE_RESPONSE_BODY_OUTPUT=0" in text
    assert "RESPONSE_TEMP_CLEANUP=PASS" in text
    assert text.count('rm -f "${response}"') >= 2
    assert 'jq -r \'if (.success == true) then "true" else "false" end\'' in text


def test_workflow_never_touches_b62_live_config_or_padiem_chat() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "b62-claw-live-config-activation-gate" not in text
    assert "CONFIRM_ACTIVATE_B62_CLAW_LIVE_CONFIG" not in text
    assert "padiem-chat" not in text
    assert "deploy-production-engine" not in text
    pr_paths = re.search(r"pull_request:\s*\n\s*paths:\n((?:\s+- .*\n)+)", text)
    assert pr_paths is not None
    for line in pr_paths.group(1).splitlines():
        assert "b62" not in line


if __name__ == "__main__":
    test_script_constants_exact()
    test_rotation_dispositions()
    test_build_overlay_payload_is_canonical_single_caller()
    test_overlay_shape_rejects_noncanonical_payloads()
    test_put_body_targets_overlay_only()
    test_overlay_round_trips_through_engine_parser_and_authentication()
    test_engine_overlay_fail_closed_rules_hold_for_gate_payload()
    test_classify_cli_rotation_required()
    test_classify_cli_refusals()
    test_plan_cli_writes_overlay_body_and_never_emits_the_credential()
    test_plan_cli_fails_closed_on_bad_credential_and_existing_output()
    test_verify_cli_post_readback()
    test_failure_evidence_never_emits_cloudflare_message_text()
    test_helper_never_selects_message_fields()
    test_workflow_dispatch_inputs_never_accept_secret_material()
    test_workflow_apply_job_confirmation_and_guards()
    test_workflow_exact_main_guards_fail_closed()
    test_workflow_uses_served_version_never_settings_plane()
    test_workflow_put_targets_overlay_only_and_never_base_v1()
    test_workflow_readonly_job_is_get_only_and_refuses_non_rotation_states()
    test_workflow_bounded_failure_evidence_wiring()
    test_workflow_never_touches_b62_live_config_or_padiem_chat()
    print("B54_ENGINE_CALLER_REGISTRY_OVERLAY_ROTATION_GATE_TESTS=PASS")
