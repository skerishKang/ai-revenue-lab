"""#3929 trusted same-conversation follow-up artifact locator, not a memory store.

No LLM/filename/local-path authority. The trusted caller supplies the owner
identity resolved by the existing canonical session, and a store that MUST
revalidate owner+conversation+workspace for every request. Returned candidates
are checked AGAIN before any source reference is selected. A selected reference
is not a READ grant: consumers revalidate permission and SHA with #3580.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Protocol

from .artifact_lineage import LineageArtifactRef
from .artifact_registration import ArtifactLifecycle, CanonicalArtifactRecord
from .contracts import ContractError

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MAX_CANDIDATES = 30
_KIND_TO_MEDIA = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
_KIND_SUFFIX = {"xlsx": ".xlsx", "pdf": ".pdf"}


def _id(value: object) -> str:
    if (not isinstance(value, str) or not _SAFE_ID.fullmatch(value)
            or ".." in value or ":" in value
            or value.casefold().startswith((
                "secret", "token", "apikey", "api_key", "oauth", "password",
                "credential", "bearer"
            ))):
        raise ContractError("bounded canonical identity required")
    return value


@dataclass(frozen=True, slots=True)
class FollowupSelection:
    """Structured intent, not a model-issued authorization or natural-language parser."""

    owner_id: str
    conversation_id: str
    workspace_ref: str
    output_kind: str  # xlsx or pdf
    selector: str = "latest"  # latest / filename / exact
    filename: str | None = None
    artifact_id: str | None = None
    integrity_ref: str | None = None

    def __post_init__(self) -> None:
        for field in ("owner_id", "conversation_id", "workspace_ref"):
            _id(getattr(self, field))
        if self.output_kind not in _KIND_TO_MEDIA:
            raise ContractError("supported XLSX or PDF output kind required")
        if self.selector not in ("latest", "filename", "exact"):
            raise ContractError("explicit bounded follow-up selector required")
        if self.selector == "filename":
            if (not isinstance(self.filename, str)
                    or not 1 <= len(self.filename) <= 180
                    or any(c in self.filename for c in ("\\", "/", "\r", "\n", "\x00"))
                    or self.artifact_id is not None or self.integrity_ref is not None):
                raise ContractError("exact display filename required")
        elif self.selector == "exact":
            _id(self.artifact_id)
            if (not isinstance(self.integrity_ref, str)
                    or re.fullmatch("[0-9a-f]{64}", self.integrity_ref) is None
                    or self.filename is not None):
                raise ContractError("confirmed artifact requires exact SHA-256 and ID")
        elif any(x is not None for x in (self.filename, self.artifact_id, self.integrity_ref)):
            raise ContractError("implicit latest request cannot carry raw artifact hints")


@dataclass(frozen=True, slots=True)
class AuthorizedConversationArtifact:
    """Record as returned by an existing *trusted* owner-scoped durable index."""

    owner_id: str
    conversation_id: str
    workspace_ref: str
    source_run_ref: str
    ordinal: int
    record: CanonicalArtifactRecord

    def __post_init__(self) -> None:
        for name in ("owner_id", "conversation_id", "workspace_ref", "source_run_ref"):
            _id(getattr(self, name))
        if type(self.ordinal) is not int or self.ordinal <= 0:
            raise ContractError("server-assigned positive chronology ordinal required")
        if not isinstance(self.record, CanonicalArtifactRecord):
            raise ContractError("canonical artifact required")
        if (self.record.run_ref != self.source_run_ref
                or self.record.workspace_ref != self.workspace_ref
                or self.record.lifecycle is not ArtifactLifecycle.DURABLE
                or self.record.durable_location is None):
            raise ContractError("owner index requires durable, bound artifact provenance")


class OwnedConversationArtifactIndex(Protocol):
    """Existing authenticated database authority, NEVER browser or model data."""

    def verify_conversation_access(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
    ) -> bool: ...

    def list_authorized_artifacts(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        limit: int,
    ) -> tuple[AuthorizedConversationArtifact, ...]: ...


class FollowupStatus(str, Enum):
    RESOLVED = "resolved"
    CONFIRMATION_REQUIRED = "confirmation_required"
    NOT_AVAILABLE = "not_available"


@dataclass(frozen=True, slots=True)
class FollowupChoice:
    """Only source-safe labels. Never a local path, provider file ID or byte payload."""

    artifact_id: str
    filename: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class FollowupResult:
    status: FollowupStatus
    artifact_ref: LineageArtifactRef | None = None
    source_run_ref: str | None = None
    choices: tuple[FollowupChoice, ...] = ()

    def public_projection(self) -> dict[str, object]:
        return {
            "contract_version": "claw-conversation-artifact-followup.v1",
            "status": self.status.value,
            "source_artifact_id": self.artifact_ref.artifact_id if self.artifact_ref else None,
            "source_run_ref": self.source_run_ref,
            "choices": [
                {"artifact_id": x.artifact_id, "filename": x.filename, "ordinal": x.ordinal}
                for x in self.choices
            ],
            "read_grant_issued": False,
            "source_material_loaded": False,
            "memory_restored": False,
            "provider_write_authorized": False,
        }


def resolve_followup_artifact(
    *, selection: FollowupSelection, index: OwnedConversationArtifactIndex,
) -> FollowupResult:
    """Resolve a verified durable reference; never read bytes or dispatch a tool.

    Ambiguous duplicate filenames (even for 'latest') and tied chronology
    fail closed until an exact artifact ID+digest is selected. A filename alone
    never selects an artifact in another workspace or a non-durable record.
    An independently bound #3580 file READ grant is required downstream.
    """
    if not isinstance(selection, FollowupSelection):
        raise ContractError("typed source request required")
    verify = getattr(index, "verify_conversation_access", None)
    list_items = getattr(index, "list_authorized_artifacts", None)
    if not callable(verify) or not callable(list_items):
        raise ContractError("trusted owner-scoped artifact index required")
    kwargs = dict(
        owner_id=selection.owner_id,
        conversation_id=selection.conversation_id,
        workspace_ref=selection.workspace_ref,
    )
    # A previously stored login, browser conversation ID or model-selected
    # source name is never proof of CURRENT access.
    if verify(**kwargs) is not True:
        return FollowupResult(FollowupStatus.NOT_AVAILABLE)
    rows = list_items(**kwargs, limit=MAX_CANDIDATES)
    if type(rows) is not tuple or len(rows) > MAX_CANDIDATES:
        raise ContractError("bounded server-trusted artifact index result required")
    ids: set[str] = set()
    matches: list[AuthorizedConversationArtifact] = []
    for item in rows:
        if not isinstance(item, AuthorizedConversationArtifact):
            raise ContractError("untrusted artifact index item")
        if (item.owner_id != selection.owner_id
                or item.conversation_id != selection.conversation_id
                or item.workspace_ref != selection.workspace_ref
                or item.record.workspace_ref != selection.workspace_ref):
            raise ContractError("artifact index scope contamination")
        if item.record.artifact_id in ids:
            raise ContractError("duplicate canonical artifact identity in index")
        ids.add(item.record.artifact_id)
        if (item.record.media_type == _KIND_TO_MEDIA[selection.output_kind]
                and item.record.filename.lower().endswith(_KIND_SUFFIX[selection.output_kind])):
            matches.append(item)
    if selection.selector == "exact":
        matches = [m for m in matches if (
            m.record.artifact_id == selection.artifact_id
            and m.record.integrity_ref == selection.integrity_ref
        )]
    elif selection.selector == "filename":
        matches = [m for m in matches if (
            m.record.filename.casefold() == selection.filename.casefold()
        )]
    if not matches:
        return FollowupResult(FollowupStatus.NOT_AVAILABLE)
    if selection.selector != "exact":
        # Two different artifact versions with the same visible name are not
        # disambiguated by recency, even if one was generated later.
        names = [item.record.filename.casefold() for item in matches]
        ambiguous_filename = len(names) != len(set(names))
        top = max(item.ordinal for item in matches)
        ambiguous_order = sum(m.ordinal == top for m in matches) != 1
        if selection.selector == "filename" or ambiguous_filename or ambiguous_order:
            if len(matches) != 1 or ambiguous_filename or ambiguous_order:
                choices = tuple(
                    FollowupChoice(m.record.artifact_id, m.record.filename, m.ordinal)
                    for m in sorted(matches, key=lambda x: (-x.ordinal, x.record.artifact_id))
                )
                return FollowupResult(FollowupStatus.CONFIRMATION_REQUIRED, choices=choices)
        selected = max(matches, key=lambda x: x.ordinal)
    else:
        if len(matches) != 1:
            raise ContractError("exact verified source identity must be unique")
        selected = matches[0]
    return FollowupResult(
        FollowupStatus.RESOLVED,
        artifact_ref=LineageArtifactRef(
            selected.record.artifact_id, selected.record.integrity_ref
        ),
        source_run_ref=selected.source_run_ref,
    )

# This module never stores artifacts or initializes a Production scope itself.
PRODUCTION_CONVERSATION_INDEX_COMPOSED = False
PRODUCTION_DURABLE_FOLLOWUP_ENABLED = False
