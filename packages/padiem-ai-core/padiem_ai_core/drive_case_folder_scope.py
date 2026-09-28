"""Canonical Core selected case-folder READ boundary (#3173, parent #3138).

Promotes the reviewed read-only *resource-scope* semantics of the historical
B54 contract (``apps/korean-ai-code-agent/src/kagent/google_drive_scope.py``,
issues #1637/#1660/#2345) into canonical Padiem AI Core, layered on top of the
already-promoted Drive READ authority in
:mod:`padiem_ai_core.drive_capability` (#2166/#2644).

What this adds
--------------
A Drive *connection* is not Drive *authority*. A Padiem Legal matter binds one
selected Drive case folder as a bounded authority: only a resource that is
exactly the selected folder, an explicitly allowed file, or a descendant of the
selected folder **proven by a trusted ancestry proof** may be read.

Security invariants (all fail closed)
-------------------------------------
* ``binding_ref`` must match between the scope and the resource;
* trashed resources are never readable;
* an observed/caller-supplied parent claim is never authority — only a
  :class:`DriveTrustedAncestryProof`, produced by a trusted server-side
  resolver, can prove descendant ancestry;
* a shortcut's *location* never grants its *target* authority: the target is
  re-authorized independently from its own proof, and a non-shortcut resource
  can never relay a target through the shortcut admission path;
* the Shared Drive identity must equal the exact scope drive identity; there is
  no implicit ``allDrives`` widening;
* this module performs zero provider calls and holds zero credentials.

Honesty boundary (this source slice)
------------------------------------
The trusted ancestry *proof contract* is implemented here. A live recursive
provider ancestry resolver that walks the provider parent chain is a follow-up
slice: :data:`DRIVE_CASE_FOLDER_LIVE_ANCESTRY_RESOLVER` stays ``False`` so no
caller can claim recursive containment that is not actually proven.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping

from .drive_capability import (
    DRIVE_CONNECTOR_ID,
    DRIVE_READ_TOOL_IDS,
    GOOGLE_SHORTCUT_MIME,
    DriveContractError,
    DriveFileProjection,
    drive_search_query,
    project_drive_file,
)

DRIVE_CASE_FOLDER_SCOPE_VERSION = "padiem-drive-case-folder-scope.v1"

GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"

MAX_CASE_FOLDER_QUERY_CHARS = 1_000
CASE_FOLDER_PAGE_SIZE = 25

# Fail-closed review state for this source slice. These are the machine-checked
# mirrors of the #3173 hard locks; a later slice flips a value only with an
# explicit CENTRAL authorization.
DRIVE_CASE_FOLDER_READ_ONLY = True
DRIVE_CASE_FOLDER_ALL_DRIVES_DEFAULT = False
DRIVE_CASE_FOLDER_LIVE_ANCESTRY_RESOLVER = False
DRIVE_CASE_FOLDER_SHORTCUT_INHERITS_LOCATION = False
DRIVE_CASE_FOLDER_SECOND_CONNECTOR = False
DRIVE_CASE_FOLDER_SECOND_OAUTH_AUTHORITY = False
DRIVE_CASE_FOLDER_SECOND_TOOL_RUNTIME = False
DRIVE_CASE_FOLDER_WRITE_AUTHORITY = False
DRIVE_CASE_FOLDER_RAW_CREDENTIALS = False
DRIVE_CASE_FOLDER_LIVE_PROVIDER_CALLS = 0

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


# --- bounded validation helpers (mirrors the reviewed Core Drive bounds) ---


def _safe_id(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise DriveContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_ID_RE.fullmatch(normalized):
        raise DriveContractError(f"{field_name} must be a bounded safe identifier")
    return normalized


def _optional_id(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _safe_id(value, field_name)


def _id_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise DriveContractError(f"{field_name} must be a tuple of ids")
    normalized = tuple(_safe_id(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise DriveContractError(f"{field_name} values must be unique")
    return normalized


def _bounded_mime(value: str, field_name: str = "mime_type") -> str:
    if not isinstance(value, str) or not value.strip():
        raise DriveContractError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > 255:
        raise DriveContractError(f"{field_name} exceeds 255 characters")
    return normalized


class DriveCaseResourceKind(str, Enum):
    """Kind of one bounded Drive resource inside the case-folder boundary."""

    FOLDER = "folder"
    FILE = "file"
    SHORTCUT = "shortcut"


class DriveCaseFolderDecision(str, Enum):
    """Fail-closed authorization outcome for one resource."""

    ALLOW = "allow"
    BINDING_MISMATCH = "binding_mismatch"
    OUT_OF_SCOPE = "out_of_scope"
    TRASHED = "trashed"
    SHARED_DRIVE_MISMATCH = "shared_drive_mismatch"
    NOT_A_SHORTCUT = "not_a_shortcut"
    SHORTCUT_TARGET_REQUIRED = "shortcut_target_required"
    SHORTCUT_TARGET_MISMATCH = "shortcut_target_mismatch"


@dataclass(frozen=True, slots=True)
class DriveCaseFolderScope:
    """One bounded selected case-folder authority for a connector binding.

    ``selected_folder_id`` is the trusted, server-resolved folder; it is never
    taken from caller/model JSON. ``allowed_file_ids`` carries only extra files
    that were explicitly attached to the matter. There is no whole-Drive or
    implicit ``allDrives`` mode.
    """

    binding_ref: str
    selected_folder_id: str
    shared_drive_id: str | None = None
    allowed_file_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_id(self.binding_ref, "binding_ref"))
        object.__setattr__(
            self, "selected_folder_id", _safe_id(self.selected_folder_id, "selected_folder_id")
        )
        object.__setattr__(self, "shared_drive_id", _optional_id(self.shared_drive_id, "shared_drive_id"))
        object.__setattr__(self, "allowed_file_ids", _id_tuple(self.allowed_file_ids, "allowed_file_id"))
        if self.selected_folder_id in self.allowed_file_ids:
            raise DriveContractError("selected_folder_id must not also be an allowed file id")

    @property
    def scope_ref(self) -> str:
        return f"case-folder:{self.selected_folder_id}"

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": DRIVE_CASE_FOLDER_SCOPE_VERSION,
            "scope_ref": self.scope_ref,
            "binding_ref": self.binding_ref,
            "selected_folder_id": self.selected_folder_id,
            "shared_drive_id": self.shared_drive_id,
            "allowed_file_ids": list(self.allowed_file_ids),
            "all_drives_default": False,
            "grants_whole_drive": False,
            "second_connector": False,
            "second_oauth_authority": False,
            "write_authority": False,
        }


@dataclass(frozen=True, slots=True)
class DriveTrustedAncestryProof:
    """Ancestry facts produced by a trusted server-side Drive resolver.

    This object is constructed only after the trusted port/resolver has walked
    the provider's own parent chain; it is never parsed from caller/model JSON.
    The ancestry *proof contract* is implemented here, while a live recursive
    provider resolver is a follow-up slice
    (:data:`DRIVE_CASE_FOLDER_LIVE_ANCESTRY_RESOLVER` is ``False``).
    """

    binding_ref: str
    resource_id: str
    ancestor_folder_ids: tuple[str, ...] = ()
    resolver_ref: str = "trusted-drive-ancestry-resolver"

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_id(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "resource_id", _safe_id(self.resource_id, "resource_id"))
        object.__setattr__(
            self,
            "ancestor_folder_ids",
            _id_tuple(self.ancestor_folder_ids, "ancestor_folder_id"),
        )
        object.__setattr__(self, "resolver_ref", _safe_id(self.resolver_ref, "resolver_ref"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": DRIVE_CASE_FOLDER_SCOPE_VERSION,
            "binding_ref": self.binding_ref,
            "resource_id": self.resource_id,
            "ancestor_folder_ids": list(self.ancestor_folder_ids),
            "resolver_ref": self.resolver_ref,
            "trusted_server_side_proof": True,
            "caller_supplied": False,
        }


@dataclass(frozen=True, slots=True)
class DriveCaseResource:
    """Bounded observed facts about one Drive resource.

    ``observed_parent_ids`` is exactly what the provider reported; it is
    deliberately *not* used for authorization, so a caller cannot grant itself
    authority by claiming a parent. ``evidence`` carries the bounded,
    credential-free version/checksum projection for readable resources.
    """

    binding_ref: str
    resource_id: str
    mime_type: str
    observed_parent_ids: tuple[str, ...] = ()
    shared_drive_id: str | None = None
    trashed: bool = False
    shortcut_target_id: str | None = None
    evidence: DriveFileProjection | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_id(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "resource_id", _safe_id(self.resource_id, "resource_id"))
        object.__setattr__(self, "mime_type", _bounded_mime(self.mime_type))
        object.__setattr__(
            self,
            "observed_parent_ids",
            _id_tuple(self.observed_parent_ids, "observed_parent_id"),
        )
        object.__setattr__(self, "shared_drive_id", _optional_id(self.shared_drive_id, "shared_drive_id"))
        if not isinstance(self.trashed, bool):
            raise DriveContractError("trashed must be boolean")
        object.__setattr__(
            self,
            "shortcut_target_id",
            _optional_id(self.shortcut_target_id, "shortcut_target_id"),
        )
        if self.evidence is not None and not isinstance(self.evidence, DriveFileProjection):
            raise DriveContractError("evidence must be a DriveFileProjection")

    @property
    def kind(self) -> DriveCaseResourceKind:
        if self.shortcut_target_id is not None or self.mime_type == GOOGLE_SHORTCUT_MIME:
            return DriveCaseResourceKind.SHORTCUT
        if self.mime_type == GOOGLE_FOLDER_MIME:
            return DriveCaseResourceKind.FOLDER
        return DriveCaseResourceKind.FILE

    @property
    def space_kind(self) -> str:
        return "shared_drive" if self.shared_drive_id else "my_drive"

    @classmethod
    def from_provider(cls, *, binding_ref: str, metadata: Mapping[str, Any]) -> "DriveCaseResource":
        """Build bounded resource facts from provider metadata.

        A trashed resource is still representable (so the decision can fail
        closed with ``TRASHED``) but never receives an evidence projection.
        """

        if not isinstance(metadata, Mapping):
            raise DriveContractError("Drive provider resource metadata must be a mapping")
        raw_id = metadata.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise DriveContractError("Drive provider resource is missing id")
        mime = metadata.get("mimeType")
        mime_value = mime.strip() if isinstance(mime, str) and mime.strip() else "application/octet-stream"
        parents = metadata.get("parents")
        if parents is None:
            parent_values: tuple[str, ...] = ()
        elif isinstance(parents, (list, tuple)):
            parent_values = tuple(
                item.strip() for item in parents if isinstance(item, str) and item.strip()
            )
        else:
            raise DriveContractError("Drive parents must be a list of ids")
        shortcut = metadata.get("shortcutDetails")
        target_id = None
        if isinstance(shortcut, Mapping):
            raw_target = shortcut.get("targetId")
            target_id = raw_target.strip() if isinstance(raw_target, str) and raw_target.strip() else None
        drive_id = metadata.get("driveId")
        trashed = metadata.get("trashed") is True
        evidence = None if trashed else project_drive_file(metadata)
        return cls(
            binding_ref=binding_ref,
            resource_id=raw_id.strip(),
            mime_type=mime_value,
            observed_parent_ids=parent_values,
            shared_drive_id=drive_id.strip() if isinstance(drive_id, str) and drive_id.strip() else None,
            trashed=trashed,
            shortcut_target_id=target_id,
            evidence=evidence,
        )


def _trusted_ancestry_for(
    scope: DriveCaseFolderScope,
    resource: DriveCaseResource,
    ancestry: DriveTrustedAncestryProof | None,
) -> tuple[bool, tuple[str, ...]]:
    """Return (proof_is_valid_for_this_resource, trusted_ancestor_ids).

    A proof issued for a different binding or a different resource is not
    evidence for this resource and is discarded.
    """

    if ancestry is None:
        return True, ()
    if ancestry.binding_ref != scope.binding_ref or ancestry.resource_id != resource.resource_id:
        return False, ()
    return True, ancestry.ancestor_folder_ids


def authorize_case_folder_resource(
    scope: DriveCaseFolderScope,
    resource: DriveCaseResource,
    ancestry: DriveTrustedAncestryProof | None = None,
) -> DriveCaseFolderDecision:
    """Fail-closed decision for one resource inside the selected-folder boundary."""

    if not isinstance(scope, DriveCaseFolderScope) or not isinstance(resource, DriveCaseResource):
        raise DriveContractError("scope/resource types are invalid")
    if ancestry is not None and not isinstance(ancestry, DriveTrustedAncestryProof):
        raise DriveContractError("ancestry must be a trusted DriveTrustedAncestryProof")

    if resource.binding_ref != scope.binding_ref:
        return DriveCaseFolderDecision.BINDING_MISMATCH
    if resource.trashed:
        return DriveCaseFolderDecision.TRASHED
    if resource.shared_drive_id != scope.shared_drive_id:
        return DriveCaseFolderDecision.SHARED_DRIVE_MISMATCH

    proof_ok, trusted_ancestors = _trusted_ancestry_for(scope, resource, ancestry)
    if not proof_ok:
        return DriveCaseFolderDecision.BINDING_MISMATCH

    exact_folder = resource.resource_id == scope.selected_folder_id
    exact_file = resource.resource_id in scope.allowed_file_ids
    proven_descendant = scope.selected_folder_id in trusted_ancestors
    if not (exact_folder or exact_file or proven_descendant):
        return DriveCaseFolderDecision.OUT_OF_SCOPE

    if resource.kind is DriveCaseResourceKind.SHORTCUT:
        # Location never grants target authority: the caller must re-authorize
        # the shortcut target from the target's own proof.
        return DriveCaseFolderDecision.SHORTCUT_TARGET_REQUIRED
    return DriveCaseFolderDecision.ALLOW


def authorize_case_folder_shortcut(
    scope: DriveCaseFolderScope,
    shortcut: DriveCaseResource,
    target: DriveCaseResource,
    *,
    shortcut_ancestry: DriveTrustedAncestryProof | None = None,
    target_ancestry: DriveTrustedAncestryProof | None = None,
) -> DriveCaseFolderDecision:
    """Authorize a shortcut only by independently authorizing its target.

    Fail closed unless ``shortcut`` is unambiguously a shortcut. An ordinary
    in-scope file or folder must never be able to relay an out-of-scope
    ``target`` into an ``ALLOW`` (target laundering).
    """

    if not isinstance(shortcut, DriveCaseResource) or not isinstance(target, DriveCaseResource):
        raise DriveContractError("shortcut/target must be DriveCaseResource")
    # A non-shortcut first argument is not shortcut authorization for the target:
    # do not propagate a plain ALLOW from the location resource.
    if shortcut.kind is not DriveCaseResourceKind.SHORTCUT:
        return DriveCaseFolderDecision.NOT_A_SHORTCUT
    location_decision = authorize_case_folder_resource(scope, shortcut, shortcut_ancestry)
    if location_decision is not DriveCaseFolderDecision.SHORTCUT_TARGET_REQUIRED:
        return location_decision
    if shortcut.shortcut_target_id is None:
        return DriveCaseFolderDecision.SHORTCUT_TARGET_REQUIRED
    if target.resource_id != shortcut.shortcut_target_id:
        return DriveCaseFolderDecision.SHORTCUT_TARGET_MISMATCH
    # Deliberately re-authorize the target from its own location/ancestry proof.
    return authorize_case_folder_resource(scope, target, target_ancestry)


def case_folder_parent_query(
    scope: DriveCaseFolderScope,
    *,
    text_query: str | None = None,
) -> str:
    """Build a bounded Drive ``q`` constrained to the selected folder.

    The folder predicate is built from the trusted scope value only. The
    optional ``text_query`` is treated as literal text through the reviewed
    Core search builder and ANDed, so model/caller input can never widen the
    boundary or become raw Drive query authority.
    """

    if not isinstance(scope, DriveCaseFolderScope):
        raise DriveContractError("scope must be DriveCaseFolderScope")
    predicate = f"'{scope.selected_folder_id}' in parents and trashed = false"
    if text_query is None:
        return predicate
    if not isinstance(text_query, str) or not text_query.strip():
        raise DriveContractError("text_query must be a non-empty string when supplied")
    normalized = text_query.strip()
    if len(normalized) > MAX_CASE_FOLDER_QUERY_CHARS:
        raise DriveContractError(f"text_query exceeds {MAX_CASE_FOLDER_QUERY_CHARS} characters")
    return f"({drive_search_query(normalized)}) and {predicate}"


def case_folder_scope_params(scope: DriveCaseFolderScope, *, text_query: str | None = None) -> dict[str, str]:
    """Provider request params for a selected-folder search/list.

    ``allDrives``-style widening stays OFF for a My Drive scope. For a Shared
    Drive scope the exact drive identity is required and the request is scoped
    to that one drive rather than all drives.
    """

    if not isinstance(scope, DriveCaseFolderScope):
        raise DriveContractError("scope must be DriveCaseFolderScope")
    params: dict[str, str] = {
        "q": case_folder_parent_query(scope, text_query=text_query),
        "pageSize": str(CASE_FOLDER_PAGE_SIZE),
    }
    if scope.shared_drive_id is not None:
        params["corpora"] = "drive"
        params["driveId"] = scope.shared_drive_id
        params["includeItemsFromAllDrives"] = "true"
        params["supportsAllDrives"] = "true"
    return params


def project_case_folder_decision(
    scope: DriveCaseFolderScope,
    resource: DriveCaseResource,
    decision: DriveCaseFolderDecision,
    *,
    ancestry: DriveTrustedAncestryProof | None = None,
) -> dict[str, Any]:
    """Bounded, credential-free provenance for a scope decision.

    Keeps the facts later Legal/evidence wiring needs (binding, file ref,
    selected-folder scope ref, provider version/checksum evidence, proof
    result, source type) and nothing that could leak credentials, owner email,
    unrelated file names, or an unrestricted Drive listing.
    """

    if not isinstance(scope, DriveCaseFolderScope) or not isinstance(resource, DriveCaseResource):
        raise DriveContractError("scope/resource types are invalid")
    if not isinstance(decision, DriveCaseFolderDecision):
        raise DriveContractError("decision must be DriveCaseFolderDecision")
    if ancestry is not None and not isinstance(ancestry, DriveTrustedAncestryProof):
        raise DriveContractError("ancestry must be a trusted DriveTrustedAncestryProof")

    proof_ok, trusted_ancestors = _trusted_ancestry_for(scope, resource, ancestry)
    return {
        "contract_version": DRIVE_CASE_FOLDER_SCOPE_VERSION,
        "decision": decision.value,
        "allowed": decision is DriveCaseFolderDecision.ALLOW,
        "scope_ref": scope.scope_ref,
        "binding_ref": scope.binding_ref,
        "selected_folder_id": scope.selected_folder_id,
        "shared_drive_id": scope.shared_drive_id,
        "resource_ref": resource.resource_id,
        "resource_kind": resource.kind.value,
        "resource_mime_type": resource.mime_type,
        "resource_space_kind": resource.space_kind,
        "resource_version_evidence": (
            resource.evidence.version_evidence() if resource.evidence is not None else None
        ),
        "shortcut_target_ref": resource.shortcut_target_id,
        "ancestry_proof_present": ancestry is not None,
        "ancestry_proof_trusted": ancestry is not None and proof_ok,
        "ancestry_resolver_ref": ancestry.resolver_ref if ancestry is not None else None,
        "trusted_ancestor_count": len(trusted_ancestors),
        "source_type": "drive",
        "all_drives_default": False,
        "shortcut_target_escape": False,
        "whole_drive_authority": False,
        "write_authority": False,
        "content_trusted": False,
        "raw_credentials_present": False,
        "oauth_tokens_present": False,
        "live_provider_calls": 0,
    }


def drive_case_folder_scope_snapshot() -> dict[str, Any]:
    """Deterministic, network-free snapshot of the selected-folder contract."""

    return {
        "contract_version": DRIVE_CASE_FOLDER_SCOPE_VERSION,
        "connector_id": DRIVE_CONNECTOR_ID,
        "reused_read_tool_ids": list(DRIVE_READ_TOOL_IDS),
        "read_only_scope_only": DRIVE_CASE_FOLDER_READ_ONLY,
        "all_drives_default": DRIVE_CASE_FOLDER_ALL_DRIVES_DEFAULT,
        "live_ancestry_resolver": DRIVE_CASE_FOLDER_LIVE_ANCESTRY_RESOLVER,
        "shortcut_inherits_location": DRIVE_CASE_FOLDER_SHORTCUT_INHERITS_LOCATION,
        "second_connector": DRIVE_CASE_FOLDER_SECOND_CONNECTOR,
        "second_oauth_authority": DRIVE_CASE_FOLDER_SECOND_OAUTH_AUTHORITY,
        "second_tool_runtime": DRIVE_CASE_FOLDER_SECOND_TOOL_RUNTIME,
        "write_authority": DRIVE_CASE_FOLDER_WRITE_AUTHORITY,
        "raw_credentials_present": DRIVE_CASE_FOLDER_RAW_CREDENTIALS,
        "live_provider_calls": DRIVE_CASE_FOLDER_LIVE_PROVIDER_CALLS,
        "caller_folder_id_grants_authority": False,
        "provider_scope_grants_padiem_authority": False,
        "production_activation": False,
    }


__all__ = [
    "DRIVE_CASE_FOLDER_SCOPE_VERSION",
    "GOOGLE_FOLDER_MIME",
    "MAX_CASE_FOLDER_QUERY_CHARS",
    "CASE_FOLDER_PAGE_SIZE",
    "DRIVE_CASE_FOLDER_READ_ONLY",
    "DRIVE_CASE_FOLDER_ALL_DRIVES_DEFAULT",
    "DRIVE_CASE_FOLDER_LIVE_ANCESTRY_RESOLVER",
    "DRIVE_CASE_FOLDER_SHORTCUT_INHERITS_LOCATION",
    "DRIVE_CASE_FOLDER_SECOND_CONNECTOR",
    "DRIVE_CASE_FOLDER_SECOND_OAUTH_AUTHORITY",
    "DRIVE_CASE_FOLDER_SECOND_TOOL_RUNTIME",
    "DRIVE_CASE_FOLDER_WRITE_AUTHORITY",
    "DRIVE_CASE_FOLDER_RAW_CREDENTIALS",
    "DRIVE_CASE_FOLDER_LIVE_PROVIDER_CALLS",
    "DriveCaseResourceKind",
    "DriveCaseFolderDecision",
    "DriveCaseFolderScope",
    "DriveTrustedAncestryProof",
    "DriveCaseResource",
    "authorize_case_folder_resource",
    "authorize_case_folder_shortcut",
    "case_folder_parent_query",
    "case_folder_scope_params",
    "project_case_folder_decision",
    "drive_case_folder_scope_snapshot",
]
