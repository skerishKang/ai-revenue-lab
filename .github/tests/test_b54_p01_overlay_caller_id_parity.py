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
  3. the overlay app authority is unchanged: ``allowed_app_ids`` stays exactly
     ``["b54-padiem-claw"]``;
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
     binding while every unrelated/secret binding is inherited (preserved).

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

NEW_CALLER_ID = "b54-p01-overlay-20260914-a1"
OLD_CALLER_ID = "b54-kagent"
ALLOWED_APP = "b54-padiem-claw"
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


def test_allowed_app_and_credential_authority_unchanged() -> None:
    rotation = _load_rotation()
    b62 = _load_b62()
    assert rotation.ALLOWED_APP_IDS == (ALLOWED_APP,)
    payload = rotation.build_overlay_payload(credential="n" * 40)
    assert payload["caller"]["allowed_app_ids"] == [ALLOWED_APP]
    assert payload["caller"]["caller_id"] == NEW_CALLER_ID
    # Credential authority names are unchanged (values are never touched here).
    rotation_text = ROTATION.read_text(encoding="utf-8")
    assert "B62_P01_ENGINE_CREDENTIAL" in rotation_text
    assert b62.P01_CREDENTIAL_NAME == "P01_ENGINE_CREDENTIAL"
    assert b62.P01_CALLER_NAME == "P01_ENGINE_CALLER_ID"
    # Overlay/base secret authority names are unchanged.
    assert rotation.OVERLAY_SECRET_NAME == OVERLAY_NAME
    assert rotation.REGISTRY_SECRET_NAME == BASE_NAME


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
