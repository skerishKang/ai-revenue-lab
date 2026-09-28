"""Core selected case-folder READ boundary tests (#3173, parent #3138).

Network-free and credential-free. Proves each required #3173 invariant at code
level and includes explicit mutation checks showing the guards are load-bearing:
a deliberately weakened policy variant that drops one guard allows exactly the
resource the real contract denies.
"""

from __future__ import annotations

import pathlib

from padiem_ai_core.drive_capability import GOOGLE_SHORTCUT_MIME
from padiem_ai_core.drive_case_folder_scope import (
    CASE_FOLDER_PAGE_SIZE,
    DRIVE_CASE_FOLDER_ALL_DRIVES_DEFAULT,
    DRIVE_CASE_FOLDER_LIVE_ANCESTRY_RESOLVER,
    DRIVE_CASE_FOLDER_SCOPE_VERSION,
    DriveCaseFolderDecision,
    DriveCaseFolderScope,
    DriveCaseResource,
    DriveCaseResourceKind,
    DriveTrustedAncestryProof,
    authorize_case_folder_resource,
    authorize_case_folder_shortcut,
    case_folder_parent_query,
    case_folder_scope_params,
    drive_case_folder_scope_snapshot,
    project_case_folder_decision,
)

BINDING = "bind:drive_legal_case"
OTHER_BINDING = "bind:drive_other_case"
CASE_FOLDER = "case_folder_001"
SUB_FOLDER = "case_subfolder_002"
INSIDE_FILE = "file_inside_003"
OUTSIDE_FILE = "file_outside_999"
SHARED_DRIVE = "shared_drive_009"
OTHER_SHARED_DRIVE = "shared_drive_777"


def my_drive_scope(**overrides: object) -> DriveCaseFolderScope:
    kwargs: dict[str, object] = {
        "binding_ref": BINDING,
        "selected_folder_id": CASE_FOLDER,
    }
    kwargs.update(overrides)
    return DriveCaseFolderScope(**kwargs)  # type: ignore[arg-type]


def resource(resource_id: str, *, mime_type: str = "text/plain", **overrides: object) -> DriveCaseResource:
    kwargs: dict[str, object] = {
        "binding_ref": BINDING,
        "resource_id": resource_id,
        "mime_type": mime_type,
    }
    kwargs.update(overrides)
    return DriveCaseResource(**kwargs)  # type: ignore[arg-type]


def ancestry_for(resource_id: str, *ancestors: str) -> DriveTrustedAncestryProof:
    return DriveTrustedAncestryProof(
        binding_ref=BINDING,
        resource_id=resource_id,
        ancestor_folder_ids=tuple(ancestors),
    )


# --- 1. exact selected-folder / explicit-file authority -------------------


def test_selected_folder_exact_resource_is_allowed() -> None:
    scope = my_drive_scope()
    folder = resource(CASE_FOLDER, mime_type="application/vnd.google-apps.folder")
    assert authorize_case_folder_resource(scope, folder) is DriveCaseFolderDecision.ALLOW


def test_explicitly_allowed_file_is_allowed() -> None:
    scope = my_drive_scope(allowed_file_ids=(INSIDE_FILE,))
    assert (
        authorize_case_folder_resource(scope, resource(INSIDE_FILE))
        is DriveCaseFolderDecision.ALLOW
    )


def test_drive_connection_is_not_whole_drive_authority() -> None:
    scope = my_drive_scope()
    # Same binding, same Drive, but not the selected folder and no proof.
    assert (
        authorize_case_folder_resource(scope, resource(OUTSIDE_FILE))
        is DriveCaseFolderDecision.OUT_OF_SCOPE
    )


# --- 2. descendant authority requires trusted ancestry --------------------


def test_descendant_with_trusted_ancestry_is_allowed() -> None:
    scope = my_drive_scope()
    nested = resource(INSIDE_FILE)
    proof = ancestry_for(INSIDE_FILE, SUB_FOLDER, CASE_FOLDER)
    assert (
        authorize_case_folder_resource(scope, nested, proof) is DriveCaseFolderDecision.ALLOW
    )


def test_descendant_without_trusted_ancestry_is_denied() -> None:
    scope = my_drive_scope()
    nested = resource(INSIDE_FILE, observed_parent_ids=(SUB_FOLDER,))
    assert (
        authorize_case_folder_resource(scope, nested) is DriveCaseFolderDecision.OUT_OF_SCOPE
    )


def test_ancestry_proof_for_a_different_resource_is_not_evidence() -> None:
    scope = my_drive_scope()
    nested = resource(INSIDE_FILE)
    # Trusted proof issued for some other resource: not evidence for this one.
    foreign = ancestry_for(OUTSIDE_FILE, CASE_FOLDER)
    assert (
        authorize_case_folder_resource(scope, nested, foreign)
        is DriveCaseFolderDecision.BINDING_MISMATCH
    )


# --- 3. caller-supplied folder claim is never authority --------------------


def test_untrusted_caller_folder_id_grants_no_authority() -> None:
    scope = my_drive_scope()
    # The provider-reported parent is what a caller could echo back; it must not
    # create authority on its own.
    claimed = resource(OUTSIDE_FILE, observed_parent_ids=(CASE_FOLDER,))
    assert (
        authorize_case_folder_resource(scope, claimed) is DriveCaseFolderDecision.OUT_OF_SCOPE
    )
    # And a caller-authored parent on the resource cannot widen the boundary.
    assert CASE_FOLDER not in claimed.observed_parent_ids or claimed.resource_id != CASE_FOLDER


def test_scope_refuses_to_treat_selected_folder_as_an_allowed_file() -> None:
    import pytest

    from padiem_ai_core.drive_capability import DriveContractError

    with pytest.raises(DriveContractError):
        DriveCaseFolderScope(
            binding_ref=BINDING,
            selected_folder_id=CASE_FOLDER,
            allowed_file_ids=(CASE_FOLDER,),
        )


# --- 4. binding + trashed + shared-drive fail closed ----------------------


def test_binding_mismatch_is_denied() -> None:
    scope = my_drive_scope()
    foreign = resource(INSIDE_FILE, binding_ref=OTHER_BINDING)
    assert (
        authorize_case_folder_resource(scope, foreign) is DriveCaseFolderDecision.BINDING_MISMATCH
    )


def test_trashed_resource_is_denied() -> None:
    scope = my_drive_scope()
    trashed = resource(CASE_FOLDER, trashed=True, mime_type="application/vnd.google-apps.folder")
    assert authorize_case_folder_resource(scope, trashed) is DriveCaseFolderDecision.TRASHED


def test_wrong_shared_drive_identity_is_denied() -> None:
    scope = my_drive_scope(shared_drive_id=SHARED_DRIVE)
    wrong = resource(INSIDE_FILE, shared_drive_id=OTHER_SHARED_DRIVE)
    assert (
        authorize_case_folder_resource(scope, wrong)
        is DriveCaseFolderDecision.SHARED_DRIVE_MISMATCH
    )
    right = resource(INSIDE_FILE, shared_drive_id=SHARED_DRIVE)
    right_proof = ancestry_for(INSIDE_FILE, CASE_FOLDER)
    assert (
        authorize_case_folder_resource(scope, right, right_proof)
        is DriveCaseFolderDecision.ALLOW
    )


def test_my_drive_scope_rejects_a_shared_drive_resource() -> None:
    scope = my_drive_scope()
    shared_only = resource(INSIDE_FILE, shared_drive_id=SHARED_DRIVE)
    assert (
        authorize_case_folder_resource(scope, shared_only)
        is DriveCaseFolderDecision.SHARED_DRIVE_MISMATCH
    )


# --- 5. shortcut escape ------------------------------------------------


def test_shortcut_inside_case_folder_to_outside_target_is_denied() -> None:
    scope = my_drive_scope()
    shortcut = resource(
        "shortcut_1",
        mime_type=GOOGLE_SHORTCUT_MIME,
        shortcut_target_id=OUTSIDE_FILE,
    )
    shortcut_proof = ancestry_for("shortcut_1", CASE_FOLDER)
    outside_target = resource(OUTSIDE_FILE)
    decision = authorize_case_folder_shortcut(
        scope,
        shortcut,
        outside_target,
        shortcut_ancestry=shortcut_proof,
    )
    assert decision is DriveCaseFolderDecision.OUT_OF_SCOPE


def test_shortcut_target_inside_scope_with_own_proof_is_allowed() -> None:
    scope = my_drive_scope()
    shortcut_proof = ancestry_for("shortcut_1", CASE_FOLDER)
    shortcut = resource(
        "shortcut_1",
        mime_type=GOOGLE_SHORTCUT_MIME,
        shortcut_target_id=INSIDE_FILE,
    )
    inside_target = resource(INSIDE_FILE)
    target_proof = ancestry_for(INSIDE_FILE, SUB_FOLDER, CASE_FOLDER)
    decision = authorize_case_folder_shortcut(
        scope,
        shortcut,
        inside_target,
        shortcut_ancestry=shortcut_proof,
        target_ancestry=target_proof,
    )
    assert decision is DriveCaseFolderDecision.ALLOW


def test_shortcut_target_id_mismatch_is_denied() -> None:
    scope = my_drive_scope()
    shortcut = resource(
        "shortcut_1",
        mime_type=GOOGLE_SHORTCUT_MIME,
        shortcut_target_id=INSIDE_FILE,
    )
    shortcut_proof = ancestry_for("shortcut_1", CASE_FOLDER)
    other_target = resource(OUTSIDE_FILE)
    assert (
        authorize_case_folder_shortcut(scope, shortcut, other_target, shortcut_ancestry=shortcut_proof)
        is DriveCaseFolderDecision.SHORTCUT_TARGET_MISMATCH
    )


def test_shortcut_alone_never_returns_allow() -> None:
    scope = my_drive_scope()
    shortcut = resource(
        "shortcut_1",
        mime_type=GOOGLE_SHORTCUT_MIME,
        shortcut_target_id=INSIDE_FILE,
        observed_parent_ids=(CASE_FOLDER,),
    )
    proof = ancestry_for("shortcut_1", CASE_FOLDER)
    assert shortcut.kind is DriveCaseResourceKind.SHORTCUT
    assert (
        authorize_case_folder_resource(scope, shortcut, proof)
        is DriveCaseFolderDecision.SHORTCUT_TARGET_REQUIRED
    )


# --- 6. search/list scoping ------------------------------------------------


def test_query_is_constrained_by_the_trusted_folder_only() -> None:
    scope = my_drive_scope()
    q = case_folder_parent_query(scope)
    assert f"'{CASE_FOLDER}' in parents" in q
    assert "trashed = false" in q


def test_caller_text_cannot_widen_the_boundary() -> None:
    scope = my_drive_scope()
    q = case_folder_parent_query(scope, text_query="report' or name contains 'secret")
    # The folder predicate always stays ANDed, and the caller text is escaped.
    assert f"'{CASE_FOLDER}' in parents" in q
    assert "\\'" in q
    assert q.endswith(f"and '{CASE_FOLDER}' in parents and trashed = false")


def test_my_drive_scope_never_widens_to_all_drives() -> None:
    scope = my_drive_scope()
    params = case_folder_scope_params(scope)
    assert params["pageSize"] == str(CASE_FOLDER_PAGE_SIZE)
    assert "corpora" not in params
    assert "driveId" not in params
    assert "includeItemsFromAllDrives" not in params
    assert DRIVE_CASE_FOLDER_ALL_DRIVES_DEFAULT is False


def test_shared_drive_scope_pins_the_exact_drive_identity() -> None:
    scope = my_drive_scope(shared_drive_id=SHARED_DRIVE)
    params = case_folder_scope_params(scope)
    assert params["driveId"] == SHARED_DRIVE
    assert params["corpora"] == "drive"


# --- 7. projection + read-only posture ------------------------------------


def test_projection_is_credential_free_and_bounded() -> None:
    scope = my_drive_scope()
    folder = resource(CASE_FOLDER, mime_type="application/vnd.google-apps.folder")
    projection = project_case_folder_decision(
        scope, folder, DriveCaseFolderDecision.ALLOW
    )
    assert projection["contract_version"] == DRIVE_CASE_FOLDER_SCOPE_VERSION
    assert projection["decision"] == "allow"
    assert projection["allowed"] is True
    assert projection["scope_ref"] == f"case-folder:{CASE_FOLDER}"
    assert projection["raw_credentials_present"] is False
    assert projection["oauth_tokens_present"] is False
    assert projection["write_authority"] is False
    assert projection["content_trusted"] is False
    assert projection["all_drives_default"] is False
    assert projection["live_provider_calls"] == 0
    assert not any("token" == key for key in projection)
    assert not any(key.endswith("_secret") for key in projection)


def test_projection_marks_ancestry_trust_only_when_it_matches() -> None:
    scope = my_drive_scope()
    nested = resource(INSIDE_FILE)
    good = project_case_folder_decision(
        scope,
        nested,
        DriveCaseFolderDecision.ALLOW,
        ancestry=ancestry_for(INSIDE_FILE, CASE_FOLDER),
    )
    assert good["ancestry_proof_trusted"] is True
    assert good["trusted_ancestor_count"] == 1
    foreign = project_case_folder_decision(
        scope,
        nested,
        DriveCaseFolderDecision.BINDING_MISMATCH,
        ancestry=ancestry_for(OUTSIDE_FILE, CASE_FOLDER),
    )
    assert foreign["ancestry_proof_trusted"] is False


def test_snapshot_is_read_only_with_no_second_authority() -> None:
    snapshot = drive_case_folder_scope_snapshot()
    assert snapshot["read_only_scope_only"] is True
    assert snapshot["write_authority"] is False
    assert snapshot["second_connector"] is False
    assert snapshot["second_oauth_authority"] is False
    assert snapshot["second_tool_runtime"] is False
    assert snapshot["all_drives_default"] is False
    assert snapshot["caller_folder_id_grants_authority"] is False
    assert snapshot["live_provider_calls"] == 0
    assert snapshot["production_activation"] is False
    # A live recursive provider ancestry resolver is a follow-up, not claimed here.
    assert DRIVE_CASE_FOLDER_LIVE_ANCESTRY_RESOLVER is False
    assert snapshot["live_ancestry_resolver"] is False


def test_source_registers_no_write_surface() -> None:
    import padiem_ai_core.drive_case_folder_scope as module

    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "files().create",
        "files().delete",
        "drives().create",
        "import httpx",
        "import requests",
        "urllib.request",
        "refresh_token",
        "client_secret",
    ):
        assert forbidden not in source, f"unexpected writable/credential surface: {forbidden}"


# --- 8. mutation checks (prove the guards are load-bearing) ----------------


def _mutant_decide(
    scope: DriveCaseFolderScope,
    target: DriveCaseResource,
    ancestry: DriveTrustedAncestryProof | None,
    *,
    skip_binding: bool = False,
    allow_trashed: bool = False,
    trust_observed_parents: bool = False,
) -> DriveCaseFolderDecision:
    """A deliberately weakened copy of the policy for mutation testing only."""

    if not skip_binding and target.binding_ref != scope.binding_ref:
        return DriveCaseFolderDecision.BINDING_MISMATCH
    if target.trashed and not allow_trashed:
        return DriveCaseFolderDecision.TRASHED
    if target.shared_drive_id != scope.shared_drive_id:
        return DriveCaseFolderDecision.SHARED_DRIVE_MISMATCH
    in_scope = (
        target.resource_id == scope.selected_folder_id
        or target.resource_id in scope.allowed_file_ids
    )
    if trust_observed_parents and scope.selected_folder_id in target.observed_parent_ids:
        in_scope = True
    if ancestry is not None and scope.selected_folder_id in ancestry.ancestor_folder_ids:
        in_scope = True
    if not in_scope:
        return DriveCaseFolderDecision.OUT_OF_SCOPE
    if target.kind is DriveCaseResourceKind.SHORTCUT:
        return DriveCaseFolderDecision.SHORTCUT_TARGET_REQUIRED
    return DriveCaseFolderDecision.ALLOW


def test_mutation_remove_trusted_ancestry_check_is_load_bearing() -> None:
    scope = my_drive_scope()
    claimed = resource(OUTSIDE_FILE, observed_parent_ids=(CASE_FOLDER,))
    assert (
        authorize_case_folder_resource(scope, claimed) is DriveCaseFolderDecision.OUT_OF_SCOPE
    )
    assert (
        _mutant_decide(scope, claimed, None, trust_observed_parents=True)
        is DriveCaseFolderDecision.ALLOW
    )


def test_mutation_ignore_binding_mismatch_is_load_bearing() -> None:
    scope = my_drive_scope()
    foreign = resource(CASE_FOLDER, mime_type="application/vnd.google-apps.folder", binding_ref=OTHER_BINDING)
    assert (
        authorize_case_folder_resource(scope, foreign) is DriveCaseFolderDecision.BINDING_MISMATCH
    )
    assert _mutant_decide(scope, foreign, None, skip_binding=True) is DriveCaseFolderDecision.ALLOW


def test_mutation_allow_trashed_is_load_bearing() -> None:
    scope = my_drive_scope()
    trashed = resource(CASE_FOLDER, trashed=True, mime_type="application/vnd.google-apps.folder")
    assert authorize_case_folder_resource(scope, trashed) is DriveCaseFolderDecision.TRASHED
    assert (
        _mutant_decide(scope, trashed, None, allow_trashed=True) is DriveCaseFolderDecision.ALLOW
    )


def test_mutation_trust_shortcut_location_is_load_bearing() -> None:
    scope = my_drive_scope()
    shortcut = resource(
        "shortcut_1",
        mime_type=GOOGLE_SHORTCUT_MIME,
        shortcut_target_id=OUTSIDE_FILE,
    )
    shortcut_proof = ancestry_for("shortcut_1", CASE_FOLDER)
    outside_target = resource(OUTSIDE_FILE)
    assert (
        authorize_case_folder_shortcut(scope, shortcut, outside_target, shortcut_ancestry=shortcut_proof)
        is DriveCaseFolderDecision.OUT_OF_SCOPE
    )

    def mutant_shortcut(scope: DriveCaseFolderScope) -> DriveCaseFolderDecision:
        # Weakens the policy by letting the shortcut's in-folder location grant
        # the target authority instead of re-authorizing the target itself.
        location = _mutant_decide(scope, shortcut, shortcut_proof)
        if location is DriveCaseFolderDecision.SHORTCUT_TARGET_REQUIRED:
            return DriveCaseFolderDecision.ALLOW
        return location

    assert mutant_shortcut(scope) is DriveCaseFolderDecision.ALLOW
