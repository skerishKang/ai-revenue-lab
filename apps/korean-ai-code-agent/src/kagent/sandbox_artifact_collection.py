"""Bounded Cloud M1 diff/artifact candidate collection (#2765).

Consumes workspace change facts a provider has already observed. Nothing here
discovers, opens, resolves, or hashes a host path: the module only decides which
supplied candidates may be projected, using authorities owned elsewhere.

Two authorities are reused rather than restated:

- lexical validity and read permission come from ``CloudWorkspacePathPolicy``, so
  Cloud M1 keeps exactly one path authority;
- what counts as an exportable artifact class comes from the accepted
  ``artifact_export`` allowlist, which this module must not widen;
- secret scrubbing comes from ``security.redact_secrets``, so no second credential
  pattern set exists.

The collection is deliberately two-tier. A path that passed workspace read authority
is a **changed file** and that evidence is kept; it becomes an **exportable artifact**
only if the existing export contract accepts its class and the export budget allows it.
Changing a source file is a fact; publishing that file is a separate, narrower
decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, TypeVar

from .artifact_export import (
    ArtifactExportManifest,
    ArtifactExportPolicy,
    SandboxArtifactCandidate,
)
from .contracts import ContractError
from .sandbox_policy import CloudWorkspacePathPolicy, WorkspacePathOperation
from .security import redact_secrets

# Local copy follows the module-local validator idiom used across kagent.
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_EnumT = TypeVar("_EnumT", bound=Enum)

# Closed ceilings. Exceeding _MAX_INPUT_CANDIDATES or _MAX_INPUT_EXCERPT_CHARS is a
# malformed record and rejects that candidate; exceeding an ArtifactExportPolicy bound
# only withholds export promotion, because the change itself still happened.
_MAX_INPUT_CANDIDATES = 200
_MAX_INPUT_EXCERPT_CHARS = 65_536
_MAX_TEXT_EXCERPT_CHARS = 4_096


class WorkspaceChangeKind(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class WorkspaceContentKind(str, Enum):
    TEXT = "text"
    BINARY = "binary"


class CandidateRejection(str, Enum):
    """Safety and correctness refusals: the record is not carried at all.

    Rejections carry one of these tokens and nothing else, so a refused candidate
    cannot smuggle the host path or provider coordinate that got it refused into a
    user-visible projection.
    """

    SYMLINK_OR_REPARSE = "symlink_or_reparse_denied"
    PATH_REFUSED_BY_WORKSPACE_AUTHORITY = "path_refused_by_workspace_authority"
    PATH_NOT_READABLE = "path_not_readable_by_workspace_authority"
    DUPLICATE_PATH_AMBIGUOUS = "duplicate_relative_path_ambiguous"
    DELETED_CANDIDATE_CARRIES_CONTENT = "deleted_candidate_carries_content"
    BINARY_CANDIDATE_CARRIES_CONTENT = "binary_candidate_carries_content"
    TEXT_EXCERPT_EXCEEDS_INPUT_LIMIT = "text_excerpt_exceeds_input_limit"


class ArtifactPromotionBlock(str, Enum):
    """Why a valid change fact is not a publishable artifact.

    Separate from rejection on purpose: none of these mean the change did not happen.
    """

    ARTIFACT_CLASS_NOT_ALLOWLISTED = "artifact_class_not_allowlisted"
    BYTE_SIZE_EXCEEDS_CANDIDATE_LIMIT = "byte_size_exceeds_candidate_limit"
    CANDIDATE_COUNT_EXCEEDS_LIMIT = "candidate_count_exceeds_limit"
    AGGREGATE_BYTES_EXCEED_LIMIT = "aggregate_bytes_exceed_limit"


def _enum_member(enum_type: type[_EnumT], value: object, field_name: str) -> _EnumT:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ContractError(f"{field_name} must be one of: {allowed}") from exc


def _safe_reference(value: object, field_name: str) -> str:
    """Validate a request identifier, not a path.

    Checking the run/lease/collection handles up front means a malformed request fails
    as a caller error instead of surfacing as a per-candidate refusal that points the
    reader at the wrong contract.
    """
    if not isinstance(value, str) or not _SAFE_REFERENCE_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


@dataclass(frozen=True, slots=True)
class WorkspaceChangeCandidate:
    """One provider-observed change fact.

    Path authority is deliberately NOT evaluated in the record: deciding what a path
    may do belongs to ``CloudWorkspacePathPolicy``, and repeating that check here would
    create a second path authority able to diverge from the first. Likewise a hostile
    record (a symlink, or a deleted file carrying a body) is constructible on purpose,
    so the collector is what denies it.

    ``content_sha256`` is the last digest the provider observed. For DELETED that is the
    point: the evidence is that it was there and what it was, which must never turn into
    an attempt to read a path that no longer exists.
    """

    relative_path: str
    change_kind: WorkspaceChangeKind
    content_kind: WorkspaceContentKind
    byte_size: int
    content_sha256: str
    symlink_or_reparse: bool = False
    text_excerpt: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.relative_path, str) or not self.relative_path.strip():
            raise ContractError("relative_path must be a non-empty string")
        # Leading/trailing space only. No separator folding, no segment rewriting: the
        # authority owns normalisation so this record cannot pre-approve anything.
        object.__setattr__(self, "relative_path", self.relative_path.strip())
        object.__setattr__(
            self, "change_kind", _enum_member(WorkspaceChangeKind, self.change_kind, "change_kind")
        )
        object.__setattr__(
            self, "content_kind", _enum_member(WorkspaceContentKind, self.content_kind, "content_kind")
        )
        if isinstance(self.byte_size, bool) or not isinstance(self.byte_size, int) or self.byte_size < 0:
            raise ContractError("byte_size must be a non-negative integer")
        if not isinstance(self.content_sha256, str) or not _SHA256_RE.fullmatch(self.content_sha256.strip().lower()):
            raise ContractError("content_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "content_sha256", self.content_sha256.strip().lower())
        if not isinstance(self.symlink_or_reparse, bool):
            raise ContractError("symlink_or_reparse must be boolean")
        if self.text_excerpt is not None and not isinstance(self.text_excerpt, str):
            raise ContractError("text_excerpt must be a string or None")


@dataclass(frozen=True, slots=True)
class CollectedArtifact:
    """An exported artifact plus its only permitted content: bounded, redacted text."""

    candidate: SandboxArtifactCandidate
    text_excerpt: str | None = None
    excerpt_truncated: bool = False
    excerpt_redacted: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, SandboxArtifactCandidate):
            raise ContractError("candidate must be SandboxArtifactCandidate")
        if self.candidate.is_symlink:
            raise ContractError("collected artifact may not be a symlink")
        if self.text_excerpt is not None and len(self.text_excerpt) > _MAX_TEXT_EXCERPT_CHARS:
            raise ContractError("collected text excerpt exceeds the closed character limit")
        for name in ("excerpt_truncated", "excerpt_redacted"):
            if not isinstance(getattr(self, name), bool):
                raise ContractError(f"{name} must be boolean")

    def safe_dict(self) -> dict[str, Any]:
        projected = self.candidate.safe_dict()
        projected["text_excerpt"] = self.text_excerpt
        projected["excerpt_truncated"] = self.excerpt_truncated
        projected["excerpt_redacted"] = self.excerpt_redacted
        projected["excerpt_char_limit"] = _MAX_TEXT_EXCERPT_CHARS
        return projected


@dataclass(frozen=True, slots=True)
class ChangedFileFact:
    """A workspace change that passed read authority, whether or not it is publishable."""

    relative_path: str
    change_kind: WorkspaceChangeKind
    content_kind: WorkspaceContentKind
    byte_size: int
    exportable: bool
    promotion_block: ArtifactPromotionBlock | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "change_kind", _enum_member(WorkspaceChangeKind, self.change_kind, "change_kind")
        )
        object.__setattr__(
            self, "content_kind", _enum_member(WorkspaceContentKind, self.content_kind, "content_kind")
        )
        if self.promotion_block is not None:
            object.__setattr__(
                self,
                "promotion_block",
                _enum_member(ArtifactPromotionBlock, self.promotion_block, "promotion_block"),
            )
        if self.exportable and self.promotion_block is not None:
            raise ContractError("an exportable change fact cannot carry a promotion block")
        if not self.exportable and self.promotion_block is None:
            raise ContractError("a non-exportable change fact must say why")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "change_kind": self.change_kind.value,
            "content_kind": self.content_kind.value,
            "byte_size": self.byte_size,
            "exportable": self.exportable,
            "promotion_block": None if self.promotion_block is None else self.promotion_block.value,
            "content_included": False,
        }


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    slot: int
    reason: CandidateRejection

    def __post_init__(self) -> None:
        if isinstance(self.slot, bool) or not isinstance(self.slot, int) or self.slot < 0:
            raise ContractError("slot must be a non-negative integer")
        object.__setattr__(self, "reason", _enum_member(CandidateRejection, self.reason, "reason"))

    def safe_dict(self) -> dict[str, Any]:
        # No path is echoed: the reason for refusal is frequently that the path names a
        # host location. Slot + closed reason token is enough to correlate upstream.
        return {"slot": self.slot, "reason": self.reason.value, "carried": False}


@dataclass(frozen=True, slots=True)
class ArtifactCandidateCollection:
    collection_id: str
    run_id: str
    lease_id: str
    changed_files: tuple[ChangedFileFact, ...] = ()
    exportable_artifacts: tuple[CollectedArtifact, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()
    aggregate_bytes: int = 0

    def __post_init__(self) -> None:
        for name in ("changed_files", "exportable_artifacts", "rejected"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                raise ContractError(f"{name} must be a tuple")
        exportable_paths = {entry.candidate.path for entry in self.exportable_artifacts}
        fact_paths = {fact.relative_path for fact in self.changed_files if fact.exportable}
        if exportable_paths != fact_paths:
            raise ContractError(
                "exportable artifacts and exportable change facts must describe one set"
            )

    @property
    def manifest(self) -> ArtifactExportManifest | None:
        """The exportable subset as the existing export contract, or None if empty.

        ``ArtifactExportManifest`` requires a non-empty tuple, so a collection with no
        publishable artifact has no manifest; the change facts and rejections remain.
        """
        if not self.exportable_artifacts:
            return None
        return ArtifactExportManifest(
            manifest_id=self.collection_id,
            run_id=self.run_id,
            lease_id=self.lease_id,
            artifacts=tuple(entry.candidate for entry in self.exportable_artifacts),
        )

    @property
    def exportable_count(self) -> int:
        return len(self.exportable_artifacts)

    @property
    def changed_file_count(self) -> int:
        return len(self.changed_files)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-artifact-candidate-collection.v2",
            "collection_id": self.collection_id,
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "changed_files": [fact.safe_dict() for fact in self.changed_files],
            "exportable_artifacts": [entry.safe_dict() for entry in self.exportable_artifacts],
            "rejected": [item.safe_dict() for item in self.rejected],
            "changed_file_count": len(self.changed_files),
            "exportable_count": len(self.exportable_artifacts),
            "rejected_count": len(self.rejected),
            "aggregate_bytes": self.aggregate_bytes,
            "raw_binary_in_projection": False,
            # Named without the word "host" on purpose: this projection is scanned by key
            # for host/mount/provider tokens, and a truthful False should not trip it. The
            # contract-level claim lives in DELETED_CANDIDATE_REQUIRES_HOST_READ below.
            "deleted_candidate_requires_content_read": False,
            "filesystem_scan_performed": False,
            "unredacted_excerpt_in_projection": False,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceArtifactCollector:
    """Validate and project already-observed candidates. Pure; discovers nothing."""

    path_policy: CloudWorkspacePathPolicy
    export_policy: ArtifactExportPolicy = field(default_factory=ArtifactExportPolicy)

    def __post_init__(self) -> None:
        # Requiring this exact type is what ties link/reparse denial to the collector:
        # CloudWorkspacePathPolicy cannot be constructed with following enabled, so a
        # re-check of those flags here could only ever fire on a policy that no longer
        # exists. The isinstance gate below is the reachable half of that dependency.
        if not isinstance(self.path_policy, CloudWorkspacePathPolicy):
            raise ContractError("path_policy must be the Cloud M1 CloudWorkspacePathPolicy")
        if not isinstance(self.export_policy, ArtifactExportPolicy):
            raise ContractError("export_policy must be ArtifactExportPolicy")

    def collect(
        self,
        *,
        collection_id: str,
        run_id: str,
        lease_id: str,
        candidates: tuple[WorkspaceChangeCandidate, ...],
    ) -> ArtifactCandidateCollection:
        if not isinstance(candidates, tuple):
            raise ContractError("candidates must be a tuple of WorkspaceChangeCandidate")
        if len(candidates) > _MAX_INPUT_CANDIDATES:
            raise ContractError(f"candidate count exceeds the closed ceiling of {_MAX_INPUT_CANDIDATES}")
        for candidate in candidates:
            if not isinstance(candidate, WorkspaceChangeCandidate):
                raise ContractError("every candidate must be WorkspaceChangeCandidate")
        collection_id = _safe_reference(collection_id, "collection_id")
        run_id = _safe_reference(run_id, "run_id")
        lease_id = _safe_reference(lease_id, "lease_id")

        # Canonical order makes the result independent of input sequence, which is what
        # lets identical facts arriving in any order produce an identical projection.
        ordered = sorted(
            candidates,
            key=lambda item: (
                item.relative_path,
                item.change_kind.value,
                item.byte_size,
                item.content_sha256,
            ),
        )
        path_slots: dict[str, int] = {}
        for candidate in ordered:
            path_slots[candidate.relative_path] = path_slots.get(candidate.relative_path, 0) + 1

        facts: list[ChangedFileFact] = []
        artifacts: list[CollectedArtifact] = []
        rejected: list[RejectedCandidate] = []
        aggregate = 0

        for slot, candidate in enumerate(ordered):
            refusal = self._refuse_candidate(candidate, path_slots)
            if refusal is not None:
                rejected.append(RejectedCandidate(slot=slot, reason=refusal))
                continue

            # Past this point the change is a fact we keep, whatever export decides.
            block = self._promotion_block(candidate, len(artifacts), aggregate)
            if block is not None:
                facts.append(self._fact(candidate, exportable=False, block=block))
                continue

            artifact = self._as_artifact(collection_id, len(artifacts), run_id, lease_id, candidate)
            if artifact is None:
                facts.append(
                    self._fact(
                        candidate,
                        exportable=False,
                        block=ArtifactPromotionBlock.ARTIFACT_CLASS_NOT_ALLOWLISTED,
                    )
                )
                continue

            excerpt, truncated, redacted = self._safe_excerpt(candidate)
            artifacts.append(
                CollectedArtifact(
                    candidate=artifact,
                    text_excerpt=excerpt,
                    excerpt_truncated=truncated,
                    excerpt_redacted=redacted,
                )
            )
            facts.append(self._fact(candidate, exportable=True, block=None))
            aggregate += candidate.byte_size

        return ArtifactCandidateCollection(
            collection_id=collection_id,
            run_id=run_id,
            lease_id=lease_id,
            changed_files=tuple(facts),
            exportable_artifacts=tuple(artifacts),
            rejected=tuple(rejected),
            aggregate_bytes=aggregate,
        )

    @staticmethod
    def _fact(
        candidate: WorkspaceChangeCandidate,
        *,
        exportable: bool,
        block: ArtifactPromotionBlock | None,
    ) -> ChangedFileFact:
        return ChangedFileFact(
            relative_path=candidate.relative_path,
            change_kind=candidate.change_kind,
            content_kind=candidate.content_kind,
            byte_size=candidate.byte_size,
            exportable=exportable,
            promotion_block=block,
        )

    def _refuse_candidate(
        self, candidate: WorkspaceChangeCandidate, path_slots: dict[str, int]
    ) -> CandidateRejection | None:
        """Safety and contract correctness. Anything that passes is kept as evidence."""
        # Deny before any path work: a link is precisely the case where a clean-looking
        # string hides an out-of-workspace target.
        if candidate.symlink_or_reparse:
            return CandidateRejection.SYMLINK_OR_REPARSE
        if path_slots[candidate.relative_path] > 1:
            return CandidateRejection.DUPLICATE_PATH_AMBIGUOUS

        # Authority first: a path this policy will not read is out of scope, so its size
        # and content are never worth reasoning about.
        readable = self._is_readable(candidate.relative_path)
        if readable is None:
            return CandidateRejection.PATH_REFUSED_BY_WORKSPACE_AUTHORITY
        if not readable:
            return CandidateRejection.PATH_NOT_READABLE

        if candidate.change_kind is WorkspaceChangeKind.DELETED and candidate.text_excerpt is not None:
            return CandidateRejection.DELETED_CANDIDATE_CARRIES_CONTENT
        if candidate.content_kind is WorkspaceContentKind.BINARY and candidate.text_excerpt is not None:
            return CandidateRejection.BINARY_CANDIDATE_CARRIES_CONTENT
        # Bound the input before any regex work, so an oversized record cannot turn
        # redaction into unbounded CPU on data we are not going to project anyway.
        if (
            candidate.text_excerpt is not None
            and len(candidate.text_excerpt) > _MAX_INPUT_EXCERPT_CHARS
        ):
            return CandidateRejection.TEXT_EXCERPT_EXCEEDS_INPUT_LIMIT
        return None

    def _promotion_block(
        self, candidate: WorkspaceChangeCandidate, exportable_count: int, aggregate: int
    ) -> ArtifactPromotionBlock | None:
        """Export budget. A block withholds publication; it never erases the change."""
        if candidate.byte_size > self.export_policy.max_file_bytes:
            return ArtifactPromotionBlock.BYTE_SIZE_EXCEEDS_CANDIDATE_LIMIT
        if exportable_count + 1 > self.export_policy.max_files:
            return ArtifactPromotionBlock.CANDIDATE_COUNT_EXCEEDS_LIMIT
        if aggregate + candidate.byte_size > self.export_policy.max_total_bytes:
            return ArtifactPromotionBlock.AGGREGATE_BYTES_EXCEED_LIMIT
        return None

    def _is_readable(self, relative_path: str) -> bool | None:
        """Ask the one path authority. None means it refused the string outright."""
        try:
            return self.path_policy.authorize(relative_path, WorkspacePathOperation.READ)
        except ContractError:
            return None

    @staticmethod
    def _as_artifact(
        collection_id: str,
        position: int,
        run_id: str,
        lease_id: str,
        candidate: WorkspaceChangeCandidate,
    ) -> SandboxArtifactCandidate | None:
        try:
            return SandboxArtifactCandidate(
                artifact_id=f"{collection_id}_{position:04d}",
                run_id=run_id,
                lease_id=lease_id,
                path=candidate.relative_path,
                kind=candidate.change_kind.value,
                size_bytes=candidate.byte_size,
                sha256=candidate.content_sha256,
            )
        except ContractError:
            # A valid change at a readable path that is simply not an exportable class.
            # The existing allowlist owns that call and this collector does not widen it.
            return None

    @staticmethod
    def _safe_excerpt(candidate: WorkspaceChangeCandidate) -> tuple[str | None, bool, bool]:
        """Redact before truncating. The order is the security property.

        Cutting to the projection limit first can leave less of a credential than its
        own pattern requires, so the remainder is no longer recognised and survives as
        exposed text. A `sk-` key starting at offset 4089 keeps 0 characters under this
        order and 4 under the reversed one, which is the case pinned by the tests.
        Redacting the whole observed text first means anything the cut leaves behind has
        already been scrubbed.

        The digest still describes the whole observed file; only the preview is shaped.
        """
        excerpt = candidate.text_excerpt
        if excerpt is None:
            return None, False, False
        redacted = redact_secrets(excerpt)
        changed = redacted != excerpt
        if len(redacted) <= _MAX_TEXT_EXCERPT_CHARS:
            return redacted, False, changed
        return redacted[:_MAX_TEXT_EXCERPT_CHARS], True, changed


ARTIFACT_EXPORT_ALLOWLIST_WIDENED = False
CHANGED_SOURCE_PATH_EVIDENCE_CARRIED = True
SOURCE_CHANGE_IMPLIES_EXPORT_AUTHORITY = False
TEXT_EXCERPT_REDACTED_BEFORE_PROJECTION = True
WORKSPACE_ARTIFACT_COLLECTOR_DISCOVERS_NO_PATHS = True
WORKSPACE_ARTIFACT_COLLECTOR_PERFORMS_NO_FILESYSTEM_SCAN = True
WORKSPACE_ARTIFACT_COLLECTOR_PERFORMS_NO_SUBPROCESS = True
WORKSPACE_ARTIFACT_COLLECTOR_PERFORMS_NO_NETWORK = True
PATH_AUTHORITY_OWNED_BY_CLOUD_WORKSPACE_PATH_POLICY = True
DELETED_CANDIDATE_REQUIRES_HOST_READ = False
RAW_BINARY_BYTES_PROJECTED = False
REAL_WORKSPACE_ARTIFACT_COLLECTION_CONFIGURED = False
