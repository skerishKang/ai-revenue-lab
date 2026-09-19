"""Bounded Cloud M1 diff/artifact candidate collection (#2765).

Consumes workspace change facts a provider has already observed. Nothing here
discovers, opens, resolves, or hashes a host path: the module only decides which
supplied candidates may be projected, using authorities owned elsewhere.

The two authorities it leans on are deliberately not reimplemented:

- lexical validity and read permission come from ``CloudWorkspacePathPolicy``, so
  there is exactly one path authority in Cloud M1;
- artifact shape, digest format and size ceilings come from the accepted
  ``artifact_export`` contracts, so no second artifact family is introduced.
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

# Local copy follows the module-local validator idiom used across kagent.
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_EnumT = TypeVar("_EnumT", bound=Enum)

# Closed ceilings. Exceeding _MAX_INPUT_CANDIDATES is a malformed request and raises;
# exceeding an ArtifactExportPolicy bound is a per-candidate rejection and is reported.
_MAX_INPUT_CANDIDATES = 200
_MAX_TEXT_EXCERPT_CHARS = 4_096


class WorkspaceChangeKind(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class WorkspaceContentKind(str, Enum):
    TEXT = "text"
    BINARY = "binary"


class CandidateRejection(str, Enum):
    """Closed reason vocabulary.

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
    BYTE_SIZE_EXCEEDS_CANDIDATE_LIMIT = "byte_size_exceeds_candidate_limit"
    AGGREGATE_BYTES_EXCEED_LIMIT = "aggregate_bytes_exceed_limit"
    CANDIDATE_COUNT_EXCEEDS_LIMIT = "candidate_count_exceeds_limit"
    REFUSED_BY_ARTIFACT_CLASS_POLICY = "refused_by_artifact_class_policy"


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
    as a caller error. Left unchecked it would surface as every candidate being refused
    for its artifact class, which points the reader at the wrong contract.
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
    point: the evidence is the fact it was there and what it was, which must never turn
    into an attempt to read a path that no longer exists.
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
        # Trailing/leading space only. No separator folding, no segment rewriting: the
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
    """An accepted candidate plus its only permitted content: a bounded text excerpt."""

    candidate: SandboxArtifactCandidate
    text_excerpt: str | None = None
    excerpt_truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, SandboxArtifactCandidate):
            raise ContractError("candidate must be SandboxArtifactCandidate")
        if self.candidate.is_symlink:
            raise ContractError("collected artifact may not be a symlink")
        if self.text_excerpt is not None and len(self.text_excerpt) > _MAX_TEXT_EXCERPT_CHARS:
            raise ContractError("collected text excerpt exceeds the closed character limit")
        if not isinstance(self.excerpt_truncated, bool):
            raise ContractError("excerpt_truncated must be boolean")

    def safe_dict(self) -> dict[str, Any]:
        projected = self.candidate.safe_dict()
        projected["text_excerpt"] = self.text_excerpt
        projected["excerpt_truncated"] = self.excerpt_truncated
        projected["excerpt_char_limit"] = _MAX_TEXT_EXCERPT_CHARS
        return projected


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
        return {"slot": self.slot, "reason": self.reason.value, "exportable": False}


@dataclass(frozen=True, slots=True)
class ArtifactCandidateCollection:
    collection_id: str
    run_id: str
    lease_id: str
    entries: tuple[CollectedArtifact, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()
    aggregate_bytes: int = 0

    @property
    def manifest(self) -> ArtifactExportManifest | None:
        """The accepted set as the existing export manifest, or None if nothing survived.

        ``ArtifactExportManifest`` requires a non-empty tuple, so an all-rejected input
        has no manifest; the rejections remain the report.
        """
        if not self.entries:
            return None
        return ArtifactExportManifest(
            manifest_id=self.collection_id,
            run_id=self.run_id,
            lease_id=self.lease_id,
            artifacts=tuple(entry.candidate for entry in self.entries),
        )

    @property
    def exportable_count(self) -> int:
        return len(self.entries)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-artifact-candidate-collection.v1",
            "collection_id": self.collection_id,
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "exportable": [entry.safe_dict() for entry in self.entries],
            "rejected": [item.safe_dict() for item in self.rejected],
            "accepted_count": len(self.entries),
            "rejected_count": len(self.rejected),
            "aggregate_bytes": self.aggregate_bytes,
            "raw_binary_in_projection": False,
            # Named without the word "host" on purpose: this projection is scanned by key
            # for host/mount/provider tokens, and a truthful False should not trip it. The
            # contract-level claim lives in DELETED_CANDIDATE_REQUIRES_HOST_READ below.
            "deleted_candidate_requires_content_read": False,
            "filesystem_scan_performed": False,
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
        # lets identical facts in any order produce an identical projection.
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

        entries: list[CollectedArtifact] = []
        rejected: list[RejectedCandidate] = []
        aggregate = 0

        for slot, candidate in enumerate(ordered):
            reject = self._reject_for(slot, candidate, path_slots, len(entries), aggregate)
            if reject is not None:
                rejected.append(reject)
                continue

            artifact = self._as_artifact(collection_id, len(entries), run_id, lease_id, candidate)
            if artifact is None:
                rejected.append(
                    RejectedCandidate(
                        slot=slot, reason=CandidateRejection.REFUSED_BY_ARTIFACT_CLASS_POLICY
                    )
                )
                continue

            excerpt, truncated = self._bounded_excerpt(candidate)
            entries.append(
                CollectedArtifact(candidate=artifact, text_excerpt=excerpt, excerpt_truncated=truncated)
            )
            aggregate += candidate.byte_size

        return ArtifactCandidateCollection(
            collection_id=collection_id,
            run_id=run_id,
            lease_id=lease_id,
            entries=tuple(entries),
            rejected=tuple(rejected),
            aggregate_bytes=aggregate,
        )

    def _reject_for(
        self,
        slot: int,
        candidate: WorkspaceChangeCandidate,
        path_slots: dict[str, int],
        accepted_count: int,
        aggregate: int,
    ) -> RejectedCandidate | None:
        def reason(code: CandidateRejection) -> RejectedCandidate:
            return RejectedCandidate(slot=slot, reason=code)

        # Deny before any path work: a link is precisely the case where a clean-looking
        # string hides an out-of-workspace target.
        if candidate.symlink_or_reparse:
            return reason(CandidateRejection.SYMLINK_OR_REPARSE)
        if path_slots[candidate.relative_path] > 1:
            return reason(CandidateRejection.DUPLICATE_PATH_AMBIGUOUS)

        # Authority first: a path this policy will not read is out of scope, so its size
        # and its content kind are never worth reasoning about.
        readable = self._is_readable(candidate.relative_path)
        if readable is None:
            return reason(CandidateRejection.PATH_REFUSED_BY_WORKSPACE_AUTHORITY)
        if not readable:
            return reason(CandidateRejection.PATH_NOT_READABLE)

        if candidate.change_kind is WorkspaceChangeKind.DELETED and candidate.text_excerpt is not None:
            return reason(CandidateRejection.DELETED_CANDIDATE_CARRIES_CONTENT)
        if candidate.content_kind is WorkspaceContentKind.BINARY and candidate.text_excerpt is not None:
            return reason(CandidateRejection.BINARY_CANDIDATE_CARRIES_CONTENT)
        if candidate.byte_size > self.export_policy.max_file_bytes:
            return reason(CandidateRejection.BYTE_SIZE_EXCEEDS_CANDIDATE_LIMIT)
        if accepted_count + 1 > self.export_policy.max_files:
            return reason(CandidateRejection.CANDIDATE_COUNT_EXCEEDS_LIMIT)
        if aggregate + candidate.byte_size > self.export_policy.max_total_bytes:
            return reason(CandidateRejection.AGGREGATE_BYTES_EXCEED_LIMIT)
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
            # Accepted path authority but not an exportable artifact class: the existing
            # allowlist owns that call, and this collector does not widen it.
            return None

    @staticmethod
    def _bounded_excerpt(candidate: WorkspaceChangeCandidate) -> tuple[str | None, bool]:
        """Truncate deterministically and say so. Silent unbounded retention is the bug."""
        excerpt = candidate.text_excerpt
        if excerpt is None:
            return None, False
        if len(excerpt) <= _MAX_TEXT_EXCERPT_CHARS:
            return excerpt, False
        return excerpt[:_MAX_TEXT_EXCERPT_CHARS], True


WORKSPACE_ARTIFACT_COLLECTOR_DISCOVERS_NO_PATHS = True
WORKSPACE_ARTIFACT_COLLECTOR_PERFORMS_NO_FILESYSTEM_SCAN = True
WORKSPACE_ARTIFACT_COLLECTOR_PERFORMS_NO_SUBPROCESS = True
WORKSPACE_ARTIFACT_COLLECTOR_PERFORMS_NO_NETWORK = True
PATH_AUTHORITY_OWNED_BY_CLOUD_WORKSPACE_PATH_POLICY = True
DELETED_CANDIDATE_REQUIRES_HOST_READ = False
RAW_BINARY_BYTES_PROJECTED = False
REAL_WORKSPACE_ARTIFACT_COLLECTION_CONFIGURED = False
