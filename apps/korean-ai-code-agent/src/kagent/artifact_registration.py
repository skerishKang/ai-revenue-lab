"""Canonical provider-neutral artifact registration contract (#3592, parent #3580).

The repository already carries three purpose-built partial artifact shapes:

* ``kagent.artifact_export.SandboxArtifactCandidate`` / ``ArtifactExportManifest``
  (sandbox export candidates, #2016-era bounded files);
* ``kagent.document_export.GeneratedDocumentArtifact`` (in-memory generated
  document handoff, #2115);
* ``claw_document_metadata`` (B62 durable document rows: document_id /
  object_key / filename / media_type / byte_length).

This module does not remove or rewrite any of them. It adds the single
provider-neutral *registration record* every future consumer (Drive, Telegram,
Padiem Chat, Desktop) can reference, plus deterministic adapters from the two
in-repo shapes where the semantics actually align.

An artifact record is **metadata only**. It is never the file content: raw
bytes, base64 payloads, local absolute paths, and any connector/model secret
material are structurally excluded from the record and from its public
projection. Provider-specific location details (a Drive file id, a Telegram
document id, ...) are deliberately NOT canonical fields; a durable location is
carried as ``location_kind`` + opaque ``location_ref`` so no provider becomes
a schema dependency. If a location has not been established yet, the record is
still valid with ``durable_location=None``.

Zero network, zero model, zero provider: deterministic and network-free by
construction, in the same style as the reviewed connector contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .document_export import GeneratedDocumentArtifact


_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_FILENAME_MAX_CHARS = 240
# Bounded to match the widest existing in-repo artifact surface
# (kagent document export 8 MiB bound; sandbox candidates are stricter).
MAX_ARTIFACT_SIZE_BYTES = 8 * 1024 * 1024
_LOCATION_KIND_MAX_CHARS = 48
_LOCATION_REF_MAX_CHARS = 512

# Secret-shaped material that must never be carried or projected by a record.
_FORBIDDEN_FILENAME_NAMES = frozenset(
    {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "credentials", "credentials.json"}
)
_FORBIDDEN_FILENAME_SUFFIXES = frozenset(
    {".pem", ".key", ".p12", ".pfx", ".sqlite", ".db"}
)


class ArtifactRegistrationError(ContractError):
    """Canonical artifact registration contract failure."""


class ArtifactLifecycle(Enum):
    """Minimal lifecycle: generated in memory, registered, or durable."""

    GENERATED = "generated"
    REGISTERED = "registered"
    DURABLE = "durable"


@dataclass(frozen=True, slots=True)
class ArtifactLocation:
    """Provider-neutral durable location (opaque ref, no provider schema)."""

    location_kind: str
    location_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "location_kind", _bounded_kind(self.location_kind))
        object.__setattr__(self, "location_ref", _bounded_location_ref(self.location_ref))


def _bounded_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ArtifactRegistrationError(f"{field_name} must be a bounded safe identifier")
    value = value.strip()
    if _CONTROL_RE.search(value):
        raise ArtifactRegistrationError(f"{field_name} must not contain control characters")
    return value


def _bounded_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ArtifactRegistrationError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if _CONTROL_RE.search(value) or ".." in value:
        raise ArtifactRegistrationError(f"{field_name} must not contain traversal or control characters")
    return value


def _bounded_kind(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > _LOCATION_KIND_MAX_CHARS:
        raise ArtifactRegistrationError("location_kind must be a bounded non-empty label")
    value = value.strip()
    if not _SAFE_ID_RE.fullmatch(value):
        raise ArtifactRegistrationError("location_kind must be a bounded safe identifier")
    return value


def _bounded_location_ref(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactRegistrationError("location_ref must be non-empty text")
    value = value.strip()
    if len(value) > _LOCATION_REF_MAX_CHARS or _CONTROL_RE.search(value):
        raise ArtifactRegistrationError("location_ref must be bounded control-free text")
    # A location ref is an opaque provider reference, never a local path.
    if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("\\\\", "/")):
        raise ArtifactRegistrationError("location_ref must not be a local filesystem path")
    return value


def _bounded_filename(value: str) -> str:
    if not isinstance(value, str):
        raise ArtifactRegistrationError("filename must be text")
    leaf = value.replace("\\", "/").split("/")[-1].strip()
    if not leaf or len(leaf) > _FILENAME_MAX_CHARS or _CONTROL_RE.search(leaf):
        raise ArtifactRegistrationError("filename must be a bounded control-free name")
    if "/" in leaf or "\\" in value and "/" not in value:
        # Any remaining separator after leaf extraction means a path was passed.
        raise ArtifactRegistrationError("filename must be a bare name, not a path")
    lowered = leaf.lower()
    if lowered in _FORBIDDEN_FILENAME_NAMES or any(lowered.endswith(suffix) for suffix in _FORBIDDEN_FILENAME_SUFFIXES):
        raise ArtifactRegistrationError("filename is a forbidden credential/key class")
    return leaf


def _bounded_media_type(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}$", value.strip()):
        raise ArtifactRegistrationError("media_type must be a bounded MIME type")
    return value.strip()


def _bounded_size(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_ARTIFACT_SIZE_BYTES:
        raise ArtifactRegistrationError("size_bytes must be a positive integer within the artifact bound")
    return value


def _bounded_sha256(value: str) -> str:
    digest = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(digest):
        raise ArtifactRegistrationError("integrity ref must be a lowercase SHA-256 digest")
    return digest


@dataclass(frozen=True, slots=True)
class CanonicalArtifactRecord:
    """Provider-neutral registration record for one generated artifact.

    This is a *reference*, never the content. Everything here is bounded,
    JSON-safe metadata; the public projection is the whole record minus the
    provenance fields a caller did not supply.
    """

    artifact_id: str
    artifact_kind: str
    filename: str
    media_type: str
    size_bytes: int
    integrity_ref: str
    lifecycle: ArtifactLifecycle = ArtifactLifecycle.GENERATED
    workspace_ref: str | None = None
    run_ref: str | None = None
    source_ref: str | None = None
    durable_location: ArtifactLocation | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _bounded_id(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "artifact_kind", _bounded_id(self.artifact_kind, "artifact_kind"))
        object.__setattr__(self, "filename", _bounded_filename(self.filename))
        object.__setattr__(self, "media_type", _bounded_media_type(self.media_type))
        object.__setattr__(self, "size_bytes", _bounded_size(self.size_bytes))
        object.__setattr__(self, "integrity_ref", _bounded_sha256(self.integrity_ref))
        if not isinstance(self.lifecycle, ArtifactLifecycle):
            raise ArtifactRegistrationError("lifecycle must be an ArtifactLifecycle value")
        for field_name in ("workspace_ref", "run_ref", "source_ref"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _bounded_ref(value, field_name))
        if self.durable_location is not None and not isinstance(self.durable_location, ArtifactLocation):
            raise ArtifactRegistrationError("durable_location must be an ArtifactLocation or None")
        if self.lifecycle is ArtifactLifecycle.DURABLE and self.durable_location is None:
            raise ArtifactRegistrationError("DURABLE lifecycle requires a durable_location")

    def public_projection(self) -> dict[str, Any]:
        """JSON-safe metadata-only projection (never bytes, never secrets)."""

        projection: dict[str, Any] = {
            "contract_version": "claw-canonical-artifact.v1",
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind,
            "filename": self.filename,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "integrity_ref": self.integrity_ref,
            "lifecycle": self.lifecycle.value,
            "raw_bytes_in_projection": False,
        }
        if self.workspace_ref is not None:
            projection["workspace_ref"] = self.workspace_ref
        if self.run_ref is not None:
            projection["run_ref"] = self.run_ref
        if self.source_ref is not None:
            projection["source_ref"] = self.source_ref
        if self.durable_location is not None:
            projection["durable_location"] = {
                "location_kind": self.durable_location.location_kind,
                "location_ref": self.durable_location.location_ref,
            }
        return projection


def register_canonical_artifact(
    *,
    artifact_id: str,
    artifact_kind: str,
    filename: str,
    media_type: str,
    size_bytes: int,
    integrity_ref: str,
    lifecycle: ArtifactLifecycle = ArtifactLifecycle.GENERATED,
    workspace_ref: str | None = None,
    run_ref: str | None = None,
    source_ref: str | None = None,
    durable_location: ArtifactLocation | None = None,
) -> CanonicalArtifactRecord:
    """Single entry point for artifact registration (validation included)."""

    return CanonicalArtifactRecord(
        artifact_id=artifact_id,
        artifact_kind=artifact_kind,
        filename=filename,
        media_type=media_type,
        size_bytes=size_bytes,
        integrity_ref=integrity_ref,
        lifecycle=lifecycle,
        workspace_ref=workspace_ref,
        run_ref=run_ref,
        source_ref=source_ref,
        durable_location=durable_location,
    )


def from_document_artifact(
    artifact: GeneratedDocumentArtifact,
    *,
    artifact_id: str,
    integrity_ref: str,
    workspace_ref: str | None = None,
    run_ref: str | None = None,
    source_ref: str | None = None,
) -> CanonicalArtifactRecord:
    """Adapter: #2115 generated document -> canonical record.

    The document artifact already bounds bytes (8 MiB), sanitizes the filename
    and pins the media type, so the mapping is direct. Content itself is never
    carried over.
    """

    if not isinstance(artifact, GeneratedDocumentArtifact):
        raise ArtifactRegistrationError("adapter source must be a GeneratedDocumentArtifact")
    return register_canonical_artifact(
        artifact_id=artifact_id,
        artifact_kind=artifact.kind,
        filename=artifact.filename,
        media_type=artifact.media_type,
        size_bytes=artifact.byte_length,
        integrity_ref=integrity_ref,
        lifecycle=ArtifactLifecycle.GENERATED,
        workspace_ref=workspace_ref,
        run_ref=run_ref,
        source_ref=source_ref,
    )


def from_sandbox_candidate(candidate: Any, *, workspace_ref: str | None = None) -> CanonicalArtifactRecord:
    """Adapter: sandbox export candidate -> canonical record.

    The sandbox candidate is a bounded, digest-carrying reference to a
    workspace-relative file (never an absolute path), so ``path`` maps onto
    ``source_ref`` and the candidate carries its own provenance (run/lease).
    The lease id is sandbox-local transport context and intentionally stays out
    of the canonical record.
    """

    # Imported lazily to keep this module import-light for other consumers.
    from .artifact_export import SandboxArtifactCandidate

    if not isinstance(candidate, SandboxArtifactCandidate):
        raise ArtifactRegistrationError("adapter source must be a SandboxArtifactCandidate")
    media_type = _MIME_BY_EXTENSION.get(candidate.path.rsplit(".", 1)[-1].lower())
    if media_type is None:
        # Semantic mismatch guard: the sandbox export allowlist is text-only
        # and its extension set must stay covered by this mapping.
        raise ArtifactRegistrationError("ADAPTER_NOT_APPLICABLE: sandbox candidate extension has no canonical media mapping")
    return register_canonical_artifact(
        artifact_id=candidate.artifact_id,
        artifact_kind=f"claw.sandbox.{candidate.kind}",
        filename=candidate.path.rsplit("/", 1)[-1],
        media_type=media_type,
        size_bytes=candidate.size_bytes,
        integrity_ref=candidate.sha256,
        lifecycle=ArtifactLifecycle.GENERATED,
        workspace_ref=workspace_ref,
        run_ref=candidate.run_id,
        source_ref=candidate.path,
    )


_MIME_BY_EXTENSION = {
    "txt": "text/plain",
    "md": "text/markdown",
    "json": "application/json",
    "csv": "text/csv",
    "log": "text/plain",
    "xml": "application/xml",
    "html": "text/html",
    "diff": "text/x-diff",
    "patch": "text/x-diff",
}
