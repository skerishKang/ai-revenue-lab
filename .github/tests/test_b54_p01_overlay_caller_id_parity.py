"""#2520 parity contract: the dedicated overlay-only Engine caller id.

Proves statically and locally (no network) that:
  1. the Engine overlay authority (b54_engine_caller_registry_overlay_rotation.py)
     and the Chat/P01 caller binding authority
     (b62_claw_live_config_activation.py) emit the SAME dedicated caller id
     ``b54-p01-overlay-20260914-a1``;
  2. the legacy shared id ``b54-kagent`` is no longer emitted by either source
     authority (case-insensitive scan), so the overlay no longer collides with
     the base V1 caller and the runtime ``duplicate_service_caller`` guard is
     never tripped by this pairing;
  3. the overlay app authority is exactly the canonical trio: ``allowed_app_ids``
     is exactly ``["b54-padiem-claw", "b54-padiem-claw-drive",
     "b54-padiem-claw-telegram"]`` — the Claw app authority is preserved, the
     canonical Drive app was added (#2645), and the canonical Telegram reader
     app is added for the #2712 getMe READ canary, while
     any further app id remains rejected by the Engine runtime;
  4. the credential authority is unchanged: the rotation still consumes ONLY
     ``B62_P01_ENGINE_CREDENTIAL`` and the Chat credential binding stays
     ``P01_ENGINE_CREDENTIAL`` (secret_text semantics untouched);
  5. the runtime duplicate-caller rejection is UNCHANGED and still fires for a
     base/overlay caller-id collision (behavioral, via the Engine's own
     identity_enforcement module);
  6. no caller-specific bypass/shadowing or dual-id acceptance was introduced:
     each authority defines exactly one caller-id constant assignment and the
     old id appears nowhere in either authority;
  7. the base V1 mutation path remains structurally absent: the rotation PUT
     body name is fixed to the OVERLAY secret and can never name the base;
  8. the Chat activation patch changes ONLY the intended plain-text caller-id
     binding while every unrelated/secret binding is inherited (preserved);
  9. (#2521 blocker) EVERY current caller-id authority emits that one id:
     Engine overlay CALLER_ID, Chat P01_CALLER_VALUE, Engine
     authority_diagnostic EXPECTED_OVERLAY_CALLER_ID, Engine
     auth_boundary_diagnostic P01_CHAT_CALLER_ID, credential-equivalence
     CALLER_ID, and the CALLER_ID / PADIEM_ENGINE_SMOKE_CALLER_ID names in the
     production smoke-only gate and the production deploy-gate smoke job;
 10. the ONE deliberate exception is documented and pinned: the historical
     base-collision evidence constant keeps the legacy id under its original
     field name, so "does the opaque base still carry the old caller?" stays
     answerable while the legacy id appears nowhere else in any current
     authority (and nowhere in the A9/A10/A11/A12 smoke scripts, which read the
     id from the workflow environment).

Safety locks asserted here:
BASE_V1_MUTATION=0
RUNTIME_DUPLICATE_REJECTION_CHANGE=0
OVERLAY_SHADOWING=NO
CREDENTIAL_ROTATION=NO (authority name/semantics unchanged; no value touched)
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROTATION = ROOT / ".github/scripts/b54_engine_caller_registry_overlay_rotation.py"
B62 = ROOT / ".github/scripts/b62_claw_live_config_activation.py"
IDENTITY = ROOT / "apps/padiem-ai-engine/app/identity_enforcement.py"
AUTHORITY_DIAGNOSTIC = ROOT / "apps/padiem-ai-engine/app/authority_diagnostic.py"
AUTH_BOUNDARY_DIAGNOSTIC = (
    ROOT / "apps/padiem-ai-engine/app/auth_boundary_diagnostic.py"
)
CREDENTIAL_EQUIVALENCE = (
    ROOT / ".github/scripts/b54_engine_credential_equivalence_diagnostic.py"
)
SMOKE_ONLY_WORKFLOW = (
    ROOT / ".github/workflows/b54-engine-production-smoke-only-gate.yml"
)
DEPLOY_GATE_WORKFLOW = (
    ROOT / ".github/workflows/b54-engine-production-deploy-gate.yml"
)
SMOKE_SCRIPTS = (
    ROOT / "apps/padiem-ai-engine/scripts/a9_production_smoke.py",
    ROOT / "apps/padiem-ai-engine/scripts/a10_continuation_production_smoke.py",
    ROOT / "apps/padiem-ai-engine/scripts/a11_gmail_tool_runtime_smoke.py",
    ROOT / "apps/padiem-ai-engine/scripts/a12_stream_replay_production_smoke.py",
)

# Every name the two production smoke jobs use to carry the caller id.
SMOKE_CALLER_ENV_PATTERN = r"^\s*(CALLER_ID|PADIEM_ENGINE_SMOKE_CALLER_ID): (\S+)$"

NEW_CALLER_ID = "b54-p01-overlay-20260914-a1"
OLD_CALLER_ID = "b54-kagent"
ALLOWED_APP = "b54-padiem-claw"
DRIVE_APP = "b54-padiem-claw-drive"
TELEGRAM_APP = "b54-padiem-claw-telegram"
# #2645 + the Telegram reader extension: the canonical overlay app authority is
# exactly this trio, in order.
ALLOWED_APPS = (ALLOWED_APP, DRIVE_APP, TELEGRAM_APP)
BASE_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
OVERLAY_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_rotation():
    return _load("b54_overlay_rotation_parity", ROTATION)


def _load_b62():
    return _load("b62_claw_live_config_parity", B62)


def _load_engine_identity():
    """Load the Engine identity modules without importing the heavy app package."""
    engine_root = ROOT / "apps" / "padiem-ai-engine"
    app_pkg = types.ModuleType("app")
    sys.modules["app"] = app_pkg
    service_identity = _load(
        "app.service_identity", engine_root / "app" / "service_identity.py"
    )
    app_pkg.service_identity = service_identity
    return _load(
        "app.identity_enforcement", engine_root / "app" / "identity_enforcement.py"
    )


def test_engine_chat_caller_id_parity() -> None:
    rotation = _load_rotation()
    b62 = _load_b62()
    assert rotation.CALLER_ID == NEW_CALLER_ID
    assert b62.P01_CALLER_VALUE == NEW_CALLER_ID
    assert rotation.CALLER_ID == b62.P01_CALLER_VALUE


def test_old_caller_id_no_longer_emitted_by_either_authority() -> None:
    for path in (ROTATION, B62):
        text = path.read_text(encoding="utf-8")
        assert OLD_CALLER_ID not in text, f"{path.name} still emits the legacy caller id"
        assert OLD_CALLER_ID.upper().replace("-", "_") not in text, (
            f"{path.name} still references the legacy caller id in another casing"
        )


def test_canonical_app_and_credential_authority_pinned() -> None:
    rotation = _load_rotation()
    b62 = _load_b62()
    # #2645 + the Telegram reader extension: exactly the canonical
    # Claw + Drive + Telegram trio, in order, no duplicates.
    assert rotation.ALLOWED_APP_IDS == ALLOWED_APPS
    assert rotation.ALLOWED_APP_IDS == (ALLOWED_APP, DRIVE_APP, TELEGRAM_APP)
    assert len(rotation.ALLOWED_APP_IDS) == 3
    assert len(set(rotation.ALLOWED_APP_IDS)) == 3
    payload = rotation.build_overlay_payload(credential="n" * 40)
    assert payload["caller"]["allowed_app_ids"] == [
        ALLOWED_APP,
        DRIVE_APP,
        TELEGRAM_APP,
    ]
    assert payload["caller"]["caller_id"] == NEW_CALLER_ID
    # Credential authority names are unchanged (values are never touched here).
    rotation_text = ROTATION.read_text(encoding="utf-8")
    assert "B62_P01_ENGINE_CREDENTIAL" in rotation_text
    assert b62.P01_CREDENTIAL_NAME == "P01_ENGINE_CREDENTIAL"
    assert b62.P01_CALLER_NAME == "P01_ENGINE_CALLER_ID"
    # Overlay/base secret authority names are unchanged.
    assert rotation.OVERLAY_SECRET_NAME == OVERLAY_NAME
    assert rotation.REGISTRY_SECRET_NAME == BASE_NAME


def test_2645_both_canonical_apps_authenticate_and_third_app_is_rejected() -> None:
    """#2645: Claw PASS, Drive PASS, arbitrary third app REJECT.

    Runs the Engine's own authenticator over the exact overlay payload the
    rotation gate PUTs, so this is behavioural proof rather than a text scan.
    """
    rotation = _load_rotation()
    identity = _load_engine_identity()
    credential = "n" * 40
    overlay_text = rotation.build_overlay_put_body(
        rotation.build_overlay_payload(credential=credential)
    )["text"]
    base_registry = {
        "version": 1,
        "callers": [
            {
                "caller_id": "storymemory-b61",
                "credential": "b" * 40,
                "allowed_app_ids": ["b61"],
            }
        ],
    }
    env = type(
        "Env",
        (),
        {
            identity.CALLER_REGISTRY_V1_ENV: json.dumps(base_registry),
            identity.CALLER_REGISTRY_V1_OVERLAY_ENV: overlay_text,
        },
    )()

    def _authenticate(app_id: str) -> None:
        identity.authenticate_request(
            env=env,
            headers={
                identity.CALLER_ID_HEADER: NEW_CALLER_ID,
                identity.CALLER_CREDENTIAL_HEADER: credential,
            },
            requested_app_id=app_id,
        )

    # Existing Claw authority PASS.
    _authenticate(ALLOWED_APP)
    # Canonical Drive authority PASS.
    _authenticate(DRIVE_APP)

    # Arbitrary third apps REJECT, including near-miss lookalikes so a prefix or
    # substring match can never widen the authority.
    for foreign in (
        "b62",
        "b61",
        f"{DRIVE_APP}-write",
        f"{DRIVE_APP}2",
        f"{ALLOWED_APP}x",
    ):
        try:
            _authenticate(foreign)
        except identity.ServiceIdentityError as exc:
            assert exc.code == "service_app_not_authorized", (foreign, exc.code)
        else:
            raise AssertionError(f"third app must be rejected: {foreign!r}")


def test_2645_runtime_identity_modules_stay_app_agnostic() -> None:
    """#2645: the Drive app is authorized as registry DATA, never runtime code."""
    for path in (
        IDENTITY,
        ROOT / "apps/padiem-ai-engine/app/service_identity.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert DRIVE_APP not in text, f"{path.name} hardcodes the Drive app id"
        # The runtime still authorizes purely from the registry payload.
        assert "allowed_app_ids" in text, f"{path.name} lost the data-driven app check"


def test_runtime_duplicate_service_caller_rejection_unchanged() -> None:
    identity = _load_engine_identity()
    rotation = _load_rotation()
    assert "duplicate_service_caller" in IDENTITY.read_text(encoding="utf-8")
    overlay_text = rotation.build_overlay_put_body(
        rotation.build_overlay_payload(credential="n" * 40)
    )["text"]
    # A base V1 that still contains the SAME caller id as the overlay must fail
    # closed with duplicate_service_caller — the rejection is data-driven and
    # was not weakened for the new id (no bypass/shadowing).
    base_dup = {
        "version": 1,
        "callers": [
            {
                "caller_id": NEW_CALLER_ID,
                "credential": "d" * 40,
                "allowed_app_ids": [ALLOWED_APP],
            }
        ],
    }
    env = type(
        "Env",
        (),
        {
            identity.CALLER_REGISTRY_V1_ENV: json.dumps(base_dup),
            identity.CALLER_REGISTRY_V1_OVERLAY_ENV: overlay_text,
        },
    )()
    try:
        identity.authenticate_request(
            env=env,
            headers={
                identity.CALLER_ID_HEADER: NEW_CALLER_ID,
                identity.CALLER_CREDENTIAL_HEADER: "n" * 40,
            },
            requested_app_id=ALLOWED_APP,
        )
    except identity.ServiceIdentityError as exc:
        assert exc.code == "duplicate_service_caller"
    else:
        raise AssertionError("duplicate base/overlay caller id must still fail closed")
    # And the dedicated id does NOT duplicate the legacy base caller: with the
    # base holding only b54-kagent, the overlay authenticates normally.
    base_legacy = {
        "version": 1,
        "callers": [
            {
                "caller_id": OLD_CALLER_ID,
                "credential": "d" * 40,
                "allowed_app_ids": [ALLOWED_APP],
            }
        ],
    }
    ok_env = type(
        "Env",
        (),
        {
            identity.CALLER_REGISTRY_V1_ENV: json.dumps(base_legacy),
            identity.CALLER_REGISTRY_V1_OVERLAY_ENV: overlay_text,
        },
    )()
    identity.authenticate_request(
        env=ok_env,
        headers={
            identity.CALLER_ID_HEADER: NEW_CALLER_ID,
            identity.CALLER_CREDENTIAL_HEADER: "n" * 40,
        },
        requested_app_id=ALLOWED_APP,
    )


def test_no_dual_id_or_shadowing_in_either_authority() -> None:
    # Each authority carries exactly ONE caller-id constant assignment.
    assert re.findall(r'^CALLER_ID = "[^"]+"$', ROTATION.read_text(encoding="utf-8"), re.M) == [
        f'CALLER_ID = "{NEW_CALLER_ID}"'
    ]
    assert re.findall(
        r'^P01_CALLER_VALUE = "[^"]+"$', B62.read_text(encoding="utf-8"), re.M
    ) == [f'P01_CALLER_VALUE = "{NEW_CALLER_ID}"']
    # No caller-id list/tuple of accepted callers was introduced in either file.
    for path in (ROTATION, B62):
        text = path.read_text(encoding="utf-8")
        assert not re.search(
            r"(caller_?ids?|CALLERS)\s*=\s*[\[(]", text, re.I
        ), f"{path.name} introduces a multi-caller acceptance structure"


def test_base_v1_mutation_path_structurally_absent() -> None:
    rotation = _load_rotation()
    payload = rotation.build_overlay_payload(credential="n" * 40)
    body = rotation.build_overlay_put_body(payload)
    assert body["name"] == OVERLAY_NAME
    assert body["name"] != BASE_NAME
    assert body["type"] == "secret_text"
    # The PUT body builder is the single mutation-shaping primitive and it is
    # hard-wired to the overlay name; the base name never appears as a PUT target.
    text = ROTATION.read_text(encoding="utf-8")
    assert '"name": OVERLAY_SECRET_NAME' in text
    assert '"name": REGISTRY_SECRET_NAME' not in text


def test_chat_patch_changes_only_the_caller_id_binding() -> None:
    b62 = _load_b62()
    # Live config where every target is exact except the caller id, which still
    # carries the legacy shared value: the patch must set ONLY that binding.
    bindings = [
        {"name": b62.P01_SERVICE_NAME, "type": "service", "service": "padiem-ai-engine"},
        {"name": b62.P01_CALLER_NAME, "type": "plain_text", "text": OLD_CALLER_ID},
        {"name": b62.P01_CREDENTIAL_NAME, "type": "secret_text"},
        {"name": "PADIEM_WORKSPACE_FILES", "type": "r2_bucket", "bucket_name": "ws"},
        {"name": "SOMETHING_UNRELATED", "type": "plain_text", "text": "keep"},
    ]
    for name, value in b62.QUOTA_VALUES.items():
        bindings.append({"name": name, "type": "plain_text", "text": value})
    settings = {"success": True, "result": {"bindings": bindings}}
    result = b62.build_activation_patch(
        settings,
        engine_service_name="padiem-ai-engine",
        r2_bucket_name="ws",
        target_sha="0" * 40,
    )
    assert result["changes"] == ["P01_CALLER_SET"]
    assert result["credential_create_required"] is False
    changed = [b for b in result["payload"]["bindings"] if b["type"] != "inherit"]
    assert changed == [
        {"name": b62.P01_CALLER_NAME, "type": "plain_text", "text": NEW_CALLER_ID}
    ]
    inherited = {b["name"] for b in result["payload"]["bindings"] if b["type"] == "inherit"}
    assert b62.P01_CREDENTIAL_NAME in inherited
    assert "SOMETHING_UNRELATED" in inherited


# --- #2521 blocker: ONE canonical caller-id contract over every authority ------


def _engine_app_module(name: str, path: Path):
    """Load an Engine ``app.*`` module under its production name (app stub)."""
    _load_engine_identity()  # registers the stubbed ``app`` package + identity modules
    package = sys.modules["app"]
    if not hasattr(package, "__path__"):
        package.__path__ = [str(path.parent)]  # type: ignore[attr-defined]
    if name in sys.modules:
        return sys.modules[name]
    return _load(name, path)


def _load_authority_diagnostic():
    return _engine_app_module("app.authority_diagnostic", AUTHORITY_DIAGNOSTIC)


def _load_auth_boundary_diagnostic():
    return _engine_app_module("app.auth_boundary_diagnostic", AUTH_BOUNDARY_DIAGNOSTIC)


def _load_credential_equivalence():
    return _load("b54_cred_equivalence_parity", CREDENTIAL_EQUIVALENCE)


def _deploy_gate_smoke_block() -> str:
    """The production smoke job only — never the deploy or rollback jobs."""
    text = DEPLOY_GATE_WORKFLOW.read_text(encoding="utf-8")
    return text.split("smoke-idempotency:", 1)[1].split(
        "rollback-production-engine:", 1
    )[0]


def _smoke_caller_env(block: str, scope: str) -> dict[str, str]:
    return {
        f"{scope}_{name}": value
        for name, value in re.findall(SMOKE_CALLER_ENV_PATTERN, block, re.M)
    }


def test_single_canonical_caller_id_contract_across_every_authority() -> None:
    """All nine live/canonical authorities must carry the SAME one caller id."""
    authorities: dict[str, str] = {
        "engine_overlay_CALLER_ID": _load_rotation().CALLER_ID,
        "chat_P01_CALLER_VALUE": _load_b62().P01_CALLER_VALUE,
        "authority_diagnostic_EXPECTED_OVERLAY_CALLER_ID": (
            _load_authority_diagnostic().EXPECTED_OVERLAY_CALLER_ID
        ),
        "auth_boundary_diagnostic_P01_CHAT_CALLER_ID": (
            _load_auth_boundary_diagnostic().P01_CHAT_CALLER_ID
        ),
        "credential_equivalence_CALLER_ID": (
            _load_credential_equivalence().CALLER_ID
        ),
    }
    authorities.update(
        _smoke_caller_env(
            SMOKE_ONLY_WORKFLOW.read_text(encoding="utf-8"), "production_smoke"
        )
    )
    authorities.update(
        _smoke_caller_env(_deploy_gate_smoke_block(), "production_deploy_smoke")
    )

    assert sorted(authorities) == [
        "auth_boundary_diagnostic_P01_CHAT_CALLER_ID",
        "authority_diagnostic_EXPECTED_OVERLAY_CALLER_ID",
        "chat_P01_CALLER_VALUE",
        "credential_equivalence_CALLER_ID",
        "engine_overlay_CALLER_ID",
        "production_deploy_smoke_CALLER_ID",
        "production_deploy_smoke_PADIEM_ENGINE_SMOKE_CALLER_ID",
        "production_smoke_CALLER_ID",
        "production_smoke_PADIEM_ENGINE_SMOKE_CALLER_ID",
    ]
    mismatched = {
        name: value for name, value in authorities.items() if value != NEW_CALLER_ID
    }
    assert not mismatched, f"caller-id drift across authorities: {mismatched}"
    assert set(authorities.values()) == {NEW_CALLER_ID}


def test_contract_loads_the_verbatim_production_diagnostic_modules() -> None:
    # The parity values above are read from the real production modules, not from
    # text patterns, so the contract can not drift from the runtime authorities.
    assert _load_authority_diagnostic().__name__ == "app.authority_diagnostic"
    assert _load_auth_boundary_diagnostic().__name__ == "app.auth_boundary_diagnostic"


def test_legacy_id_is_gone_from_every_current_authority() -> None:
    for path in (
        ROTATION,
        B62,
        AUTH_BOUNDARY_DIAGNOSTIC,
        CREDENTIAL_EQUIVALENCE,
        SMOKE_ONLY_WORKFLOW,
    ):
        text = path.read_text(encoding="utf-8")
        assert OLD_CALLER_ID not in text, f"{path.name} still carries the legacy id"
    assert OLD_CALLER_ID not in _deploy_gate_smoke_block()


def test_historical_base_evidence_keeps_the_legacy_id_under_its_original_name() -> None:
    # Deliberate, documented exception: the historical base-collision evidence
    # constant is NOT renamed. Exactly one legacy literal may remain, and it must
    # be that constant.
    text = AUTHORITY_DIAGNOSTIC.read_text(encoding="utf-8")
    assert text.count(f'"{OLD_CALLER_ID}"') == 1
    assert f'LEGACY_BASE_CALLER_ID = "{OLD_CALLER_ID}"' in text
    assert f'EXPECTED_OVERLAY_CALLER_ID = "{NEW_CALLER_ID}"' in text
    module = _load_authority_diagnostic()
    assert module.LEGACY_BASE_CALLER_ID == OLD_CALLER_ID
    assert module.LEGACY_BASE_CALLER_ID != module.EXPECTED_OVERLAY_CALLER_ID
    assert "BASE_CONTAINS_B54_KAGENT" in module.CLOSED_FIELDS


def test_historical_base_collision_question_still_answered_for_the_legacy_id() -> None:
    module = _load_authority_diagnostic()
    legacy_base = json.dumps(
        {
            "version": 1,
            "callers": [
                {
                    "caller_id": OLD_CALLER_ID,
                    "credential": "d" * 40,
                    "allowed_app_ids": [ALLOWED_APP],
                }
            ],
        }
    )
    overlay = json.dumps(
        {
            "version": 1,
            "caller": {
                "caller_id": NEW_CALLER_ID,
                "credential": "n" * 40,
                "allowed_app_ids": [ALLOWED_APP],
            },
        }
    )
    fields = module.classify_authority_payloads(legacy_base, overlay)
    # Historical evidence keeps its original meaning ...
    assert fields["BASE_CONTAINS_B54_KAGENT"] == "YES"
    # ... while the duplicate question is data-driven for the NEW id: a base that
    # only carries the legacy caller no longer collides with the overlay.
    assert fields["DUPLICATE_CALLER_ID"] == "NO"
    assert fields["OVERLAY_CALLER_ID_MATCH"] == "YES"


def test_no_dual_id_or_alias_in_any_diagnostic_authority() -> None:
    for path, pattern, expected in (
        (
            AUTHORITY_DIAGNOSTIC,
            r'^EXPECTED_OVERLAY_CALLER_ID = "[^"]+"$',
            f'EXPECTED_OVERLAY_CALLER_ID = "{NEW_CALLER_ID}"',
        ),
        (
            AUTH_BOUNDARY_DIAGNOSTIC,
            r'^P01_CHAT_CALLER_ID = "[^"]+"$',
            f'P01_CHAT_CALLER_ID = "{NEW_CALLER_ID}"',
        ),
        (
            CREDENTIAL_EQUIVALENCE,
            r'^CALLER_ID = "[^"]+"$',
            f'CALLER_ID = "{NEW_CALLER_ID}"',
        ),
    ):
        text = path.read_text(encoding="utf-8")
        assert re.findall(pattern, text, re.M) == [expected], path.name
        # No accepted-caller list/tuple (alias, dual-id or fallback set) exists.
        assert not re.search(r"(caller_?ids?|CALLERS)\s*=\s*[\[(]", text, re.I), path.name


def test_smoke_scripts_read_the_caller_id_from_the_environment() -> None:
    # Phase-A / A10-A12 source is NOT part of this change: every smoke script
    # takes the caller id from the workflow env, never from a literal.
    for script in SMOKE_SCRIPTS:
        text = script.read_text(encoding="utf-8")
        assert NEW_CALLER_ID not in text, script.name
        assert OLD_CALLER_ID not in text, script.name
        assert "os.environ.get(" in text, script.name


def test_deploy_gate_rollback_and_deploy_authority_are_untouched() -> None:
    text = DEPLOY_GATE_WORKFLOW.read_text(encoding="utf-8")
    rollback_block = text.split("rollback-production-engine:", 1)[1]
    assert "wrangler@4 rollback" in rollback_block
    assert "CALLER_ID" not in rollback_block
    # The smoke-only gate performs no mutation at all.
    assert "PRODUCTION_MUTATION=0" in SMOKE_ONLY_WORKFLOW.read_text(encoding="utf-8")


if __name__ == "__main__":
    for _name, _value in sorted(globals().items()):
        if _name.startswith("test_") and callable(_value):
            _value()
    print("P01_OVERLAY_CALLER_ID_PARITY=PASS")
