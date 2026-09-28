"""Engine selected case-folder scope projection/enforcement tests (#3173).

Network-free and credential-free. The Core scope contract is exercised through
the Engine seam so the projection stays bounded and out-of-scope content fails
closed before it can enter Legal/Claw context.
"""

from __future__ import annotations

import pathlib

import pytest

from padiem_ai_core.drive_capability import DRIVE_READ_TOOL_IDS
from padiem_ai_core.drive_case_folder_scope import (
    DriveCaseFolderDecision,
    DriveCaseFolderScope,
    DriveCaseResource,
    DriveTrustedAncestryProof,
)

from app.drive_case_folder_scope_projection import (
    DRIVE_CASE_FOLDER_ENGINE_PROJECTION_VERSION,
    EngineDriveCaseFolderScopeError,
    admit_case_folder_resource,
    admit_case_folder_shortcut,
    case_folder_provider_params,
    project_case_folder_scope_for_engine,
)

BINDING = "bind:drive_legal_case"
CASE_FOLDER = "case_folder_001"
INSIDE_FILE = "file_inside_003"
OUTSIDE_FILE = "file_outside_999"
GOOGLE_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"


def scope() -> DriveCaseFolderScope:
    return DriveCaseFolderScope(binding_ref=BINDING, selected_folder_id=CASE_FOLDER)


def resource(resource_id: str, **overrides: object) -> DriveCaseResource:
    kwargs: dict[str, object] = {
        "binding_ref": BINDING,
        "resource_id": resource_id,
        "mime_type": "text/plain",
    }
    kwargs.update(overrides)
    return DriveCaseResource(**kwargs)  # type: ignore[arg-type]


# --- projection -----------------------------------------------------------


def test_projection_is_bounded_and_credential_free() -> None:
    projection = project_case_folder_scope_for_engine(scope())
    assert projection["projection_version"] == DRIVE_CASE_FOLDER_ENGINE_PROJECTION_VERSION
    assert projection["scope_ref"] == f"case-folder:{CASE_FOLDER}"
    assert projection["binding_ref"] == BINDING
    assert projection["selected_folder_id"] == CASE_FOLDER
    assert projection["reused_read_tool_ids"] == sorted(DRIVE_READ_TOOL_IDS)
    assert projection["all_drives_default"] is False
    assert projection["grants_whole_drive"] is False
    assert projection["second_connector"] is False
    assert projection["second_oauth_authority"] is False
    assert projection["second_tool_runtime"] is False
    assert projection["write_authority"] is False
    assert projection["raw_credentials_present"] is False
    assert projection["oauth_tokens_present"] is False
    assert projection["mints_approval_authority"] is False
    assert projection["live_provider_calls"] == 0
    assert projection["production_activation"] is False


def test_projection_rejects_non_scope() -> None:
    with pytest.raises(ValueError, match="DriveCaseFolderScope"):
        project_case_folder_scope_for_engine(object())  # type: ignore[arg-type]


def test_projection_rejects_non_read_tool_ids() -> None:
    with pytest.raises(ValueError, match="drive_tool_not_bindable"):
        project_case_folder_scope_for_engine(scope(), tool_ids=("drive.upload_file",))


# --- enforcement ----------------------------------------------------------


def test_admit_allows_in_scope_resource_with_bounded_projection() -> None:
    projection = admit_case_folder_resource(
        scope(),
        resource(INSIDE_FILE),
        ancestry=DriveTrustedAncestryProof(
            binding_ref=BINDING, resource_id=INSIDE_FILE, ancestor_folder_ids=(CASE_FOLDER,)
        ),
    )
    assert projection["decision"] == "allow"
    assert projection["allowed"] is True
    assert projection["raw_credentials_present"] is False
    assert projection["content_trusted"] is False


def test_admit_fails_closed_for_out_of_scope_resource() -> None:
    with pytest.raises(EngineDriveCaseFolderScopeError, match="out_of_scope"):
        admit_case_folder_resource(scope(), resource(OUTSIDE_FILE))


def test_admit_decision_matches_core_decision_name() -> None:
    with pytest.raises(EngineDriveCaseFolderScopeError) as excinfo:
        admit_case_folder_resource(scope(), resource(INSIDE_FILE, trashed=True))
    assert DriveCaseFolderDecision.TRASHED.value in str(excinfo.value)


def test_admit_shortcut_requires_target_reauthorization() -> None:
    shortcut = resource(
        "shortcut_1",
        mime_type=GOOGLE_SHORTCUT_MIME,
        shortcut_target_id=OUTSIDE_FILE,
    )
    shortcut_proof = DriveTrustedAncestryProof(
        binding_ref=BINDING, resource_id="shortcut_1", ancestor_folder_ids=(CASE_FOLDER,)
    )
    with pytest.raises(EngineDriveCaseFolderScopeError, match="out_of_scope"):
        admit_case_folder_shortcut(
            scope(),
            shortcut,
            resource(OUTSIDE_FILE),
            shortcut_ancestry=shortcut_proof,
        )

    inside_target = resource(INSIDE_FILE)
    target_proof = DriveTrustedAncestryProof(
        binding_ref=BINDING, resource_id=INSIDE_FILE, ancestor_folder_ids=(CASE_FOLDER,)
    )
    shortcut_inside = resource(
        "shortcut_1",
        mime_type=GOOGLE_SHORTCUT_MIME,
        shortcut_target_id=INSIDE_FILE,
    )
    projection = admit_case_folder_shortcut(
        scope(),
        shortcut_inside,
        inside_target,
        shortcut_ancestry=shortcut_proof,
        target_ancestry=target_proof,
    )
    assert projection["allowed"] is True
    assert projection["resource_ref"] == INSIDE_FILE


def test_provider_params_keep_the_folder_boundary() -> None:
    params = case_folder_provider_params(scope())
    assert f"'{CASE_FOLDER}' in parents" in params["q"]
    assert "corpora" not in params


# --- source posture -------------------------------------------------------


def test_engine_seam_source_has_no_network_or_credentials() -> None:
    base = pathlib.Path(__file__).resolve().parents[1]
    source = (base / "app" / "drive_case_folder_scope_projection.py").read_text(encoding="utf-8")
    for forbidden in (
        "import httpx",
        "import requests",
        "import socket",
        "urllib.request",
        "webbrowser",
        "refresh_token",
        "client_secret",
        "access_token",
        "ToolRuntime(",
        "ToolSpec(",
        "import tool_runtime",
        "tool_runtime import",
        "googleapis.com",
        "oauth2",
    ):
        assert forbidden not in source, f"engine seam contains forbidden token: {forbidden}"
