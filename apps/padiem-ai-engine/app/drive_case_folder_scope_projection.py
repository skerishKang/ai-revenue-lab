"""Engine selected case-folder scope projection/enforcement seam (#3173).

Smallest Engine-side extension of the existing Drive trusted binding seam
(``app/drive_capability_projection.py``): it exposes a bounded, credential-free
representation of one Core selected case-folder scope and one fail-closed
admission check that runs *before* provider content can enter the Legal/Claw
context.

Boundaries preserved:

* Core remains the sole scope authority (``padiem_ai_core.
  drive_case_folder_scope``); the Engine never re-implements the decision and
  never instantiates a second tool runtime;
* this seam carries capability/scope *facts* only — no OAuth access material,
  no OAuth refresh material, no client credential, no provider endpoint;
* no live provider call and no Production composition change: the seam is inert
  until a later slice wires it into ``worker_identity`` composition;
* every requested tool id must classify as READ or the projection refuses;
* an out-of-scope resource fails closed with an error rather than returning
  content.
"""

from __future__ import annotations

from typing import Any

from padiem_ai_core.drive_capability import DRIVE_READ_TOOL_IDS
from padiem_ai_core.drive_case_folder_scope import (
    DRIVE_CASE_FOLDER_SCOPE_VERSION,
    DriveCaseFolderDecision,
    DriveCaseFolderScope,
    DriveCaseResource,
    DriveTrustedAncestryProof,
    authorize_case_folder_resource,
    authorize_case_folder_shortcut,
    case_folder_scope_params,
    project_case_folder_decision,
)

from app.drive_capability_projection import classify_drive_tool_for_binding

DRIVE_CASE_FOLDER_ENGINE_PROJECTION_VERSION = "engine-drive-case-folder-scope.v1"


class EngineDriveCaseFolderScopeError(ValueError):
    """Fail-closed denial when a resource is outside the selected case folder."""


def project_case_folder_scope_for_engine(
    scope: DriveCaseFolderScope,
    *,
    tool_ids: tuple[str, ...] = DRIVE_READ_TOOL_IDS,
) -> dict[str, Any]:
    """Project bounded selected-folder scope facts for Engine transports.

    Deterministic, network-free, credential-free: the projection contains scope
    identifiers and hard-lock flags only. Every requested tool id must classify
    as READ or the projection refuses.
    """

    if not isinstance(scope, DriveCaseFolderScope):
        raise ValueError("scope must be a Core DriveCaseFolderScope")
    if not tool_ids:
        raise ValueError("tool_ids must not be empty")
    for tool_id in tool_ids:
        classify_drive_tool_for_binding(tool_id)
    return {
        "projection_version": DRIVE_CASE_FOLDER_ENGINE_PROJECTION_VERSION,
        "contract_version": DRIVE_CASE_FOLDER_SCOPE_VERSION,
        "scope_ref": scope.scope_ref,
        "binding_ref": scope.binding_ref,
        "selected_folder_id": scope.selected_folder_id,
        "shared_drive_id": scope.shared_drive_id,
        "allowed_file_ids": list(scope.allowed_file_ids),
        "reused_read_tool_ids": sorted(tool_ids),
        "all_drives_default": False,
        "grants_whole_drive": False,
        "second_connector": False,
        "second_oauth_authority": False,
        "second_tool_runtime": False,
        "write_authority": False,
        "raw_credentials_present": False,
        "oauth_tokens_present": False,
        "mints_approval_authority": False,
        "live_provider_calls": 0,
        "production_activation": False,
    }


def admit_case_folder_resource(
    scope: DriveCaseFolderScope,
    resource: DriveCaseResource,
    *,
    ancestry: DriveTrustedAncestryProof | None = None,
) -> dict[str, Any]:
    """Admit one resource or fail closed before content reaches Legal/Claw.

    Returns the bounded Core provenance projection on ``ALLOW``; raises
    :class:`EngineDriveCaseFolderScopeError` carrying the Core decision
    otherwise, so an out-of-scope resource never returns content.
    """

    decision = authorize_case_folder_resource(scope, resource, ancestry)
    if decision is not DriveCaseFolderDecision.ALLOW:
        raise EngineDriveCaseFolderScopeError(f"drive_case_folder_scope_denied:{decision.value}")
    return project_case_folder_decision(scope, resource, decision, ancestry=ancestry)


def admit_case_folder_shortcut(
    scope: DriveCaseFolderScope,
    shortcut: DriveCaseResource,
    target: DriveCaseResource,
    *,
    shortcut_ancestry: DriveTrustedAncestryProof | None = None,
    target_ancestry: DriveTrustedAncestryProof | None = None,
) -> dict[str, Any]:
    """Admit a shortcut-resolved resource only after independent target proof."""

    decision = authorize_case_folder_shortcut(
        scope,
        shortcut,
        target,
        shortcut_ancestry=shortcut_ancestry,
        target_ancestry=target_ancestry,
    )
    if decision is not DriveCaseFolderDecision.ALLOW:
        raise EngineDriveCaseFolderScopeError(f"drive_case_folder_scope_denied:{decision.value}")
    return project_case_folder_decision(scope, target, decision, ancestry=target_ancestry)


def case_folder_provider_params(scope: DriveCaseFolderScope, *, text_query: str | None = None) -> dict[str, str]:
    """Trusted-boundary provider params for a selected-folder search/list."""

    return case_folder_scope_params(scope, text_query=text_query)


__all__ = [
    "DRIVE_CASE_FOLDER_ENGINE_PROJECTION_VERSION",
    "EngineDriveCaseFolderScopeError",
    "project_case_folder_scope_for_engine",
    "admit_case_folder_resource",
    "admit_case_folder_shortcut",
    "case_folder_provider_params",
]
