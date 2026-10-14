"""Canonical provider-neutral artifact lineage contract (#3599, parent #3580).

#3592/#3594 defined ONE canonical artifact
(``kagent.artifact_registration.CanonicalArtifactRecord``). This module defines
the *relation between artifacts* — how one original source becomes an optional
working representation and one or more generated output artifacts:

```text
ORIGINAL SOURCE
  -> OPTIONAL WORKING COPY
  -> OUTPUT ARTIFACT(S)
```

This is a **reference** contract, not a second artifact record. It carries only
``artifact_id`` + integrity bindings. When a ``CanonicalArtifactRecord`` is
supplied, this module can mechanically derive that pair from #3594. When a
caller supplies a ``LineageArtifactRef`` directly, prior canonical registration
is an **input precondition owned by the existing artifact authority/caller
composition boundary**, not an attestation this module can make: there is no
registry lookup here. The artifact authority stays in #3594; the run/workspace
authority stays wherever it already lives; this module mints neither.

Invariants enforced at construction (fail closed, never silently corrected):

* ``SOURCE_IDENTITY_PRESERVED`` — the source artifact id is its own field and
  is never rewritten by a lineage;
* ``SOURCE_INTEGRITY_PRESERVED`` — the source integrity digest is pinned;
* ``WORKING_COPY_OPTIONAL`` — a lineage is valid with no working copy at all
  (``source -> output`` and ``source`` alone are both legal);
* ``WORKING_COPY_REPLACES_SOURCE=NO`` — a working *canonical artifact* may
  never alias the source id. A working representation that is not a canonical
  artifact is expressed through the opaque ``working_representation_ref``, and
  that token may not alias the source id either;
* ``OUTPUTS_DISTINCT_CANONICAL_ARTIFACTS`` — every output id is distinct from
  the source, from the working artifact and from every other output;
* ``MULTIPLE_OUTPUT_BOUND`` — ``MAX_OUTPUT_ARTIFACTS`` bounds the list; there
  is no unbounded output list.

Provider neutrality. A Drive file id, a Google Sheets id, a Telegram document
id, a local Windows path, an S3/R2 object key are **not** fields of this
contract and are never interpreted here. A provider-backed working copy is
registered as a canonical artifact (#3594) whose durable location is already
carried as ``location_kind`` + opaque ``location_ref``, and is then referenced
through ``working_artifact_id``. Nothing in this module requires Google Drive,
Google Sheets, Telegram, Desktop, R2 or S3.

No lifecycle/state field is added: a lineage is pure relation metadata, and a
new state machine would be a new authority that no invariant here requires.

Metadata only, never content: raw bytes, base64, local absolute paths,
``file://`` URIs, OAuth/connector secrets, Telegram chat ids and model/provider
material are structurally excluded, and the raw working representation token is
never projected (only its presence is).

Zero network, zero model, zero provider: deterministic and network-free by
construction, in the same style as ``artifact_registration``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from .artifact_registration import CanonicalArtifactRecord
from .contracts import ContractError


_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_OPAQUE_REF_MAX_CHARS = 512

# Deterministic bound on one lineage's fan-out. A lineage describes a bounded
# transformation of one source; an unbounded list is a collection contract, not
# a lineage, and is rejected instead of truncated.
MAX_OUTPUT_ARTIFACTS = 16

_CREDENTIAL_PREFIXES = (
    "secret",
    "oauth",
    "token",
    "api_key",
    "apikey",
    "bearer",
    "password",
    "credential",
)


class ArtifactLineageError(ContractError):
    """Canonical artifact lineage contract failure."""


def _bounded_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ArtifactLineageError(f"{field_name} must be a bounded safe identifier")
    value = value.strip()
    if _CONTROL_RE.search(value):
        raise ArtifactLineageError(f"{field_name} must not contain control characters")
    return value


def _bounded_ref(value: str, field_name: str) -> str:
    """Identifier-semantics provenance ref (workspace_ref / run_ref / ...).

    These are identity tokens consumed from the existing run/workspace
    authority, not addresses: no URL scheme, no credential-shaped prefix, no
    traversal or control characters.
    """
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ArtifactLineageError(f"{field_name} must be a bounded safe identifier")
    value = value.strip()
    if _CONTROL_RE.search(value) or ".." in value:
        raise ArtifactLineageError(f"{field_name} must not contain traversal or control characters")
    lowered = value.lower()
    if "://" in lowered or ":" in value:
        raise ArtifactLineageError(f"{field_name} must be an identifier, not a URL or scheme-prefixed token")
    if any(lowered.startswith(prefix) for prefix in _CREDENTIAL_PREFIXES):
        raise ArtifactLineageError(f"{field_name} must not carry credential-like material")
    return value


def _bounded_representation_ref(value: str) -> str:
    """Opaque, provider-neutral handle to a NON-canonical working representation.

    This is the escape hatch for a working copy that has not been registered as
    a canonical artifact (``source -> ephemeral working -> output``). The token
    is opaque: this contract never interprets it, and a provider-backed working
    copy must instead be registered through #3594 and referenced by
    ``working_artifact_id``.

    Local references (drive letter, UNC, absolute POSIX), ``file://`` URIs, any
    URL with query/fragment material, whitespace-bearing credential material
    and credential-like prefixes fail closed.
    """
    if not isinstance(value, str) or not value.strip():
        raise ArtifactLineageError("working_representation_ref must be non-empty text")
    value = value.strip()
    if len(value) > _OPAQUE_REF_MAX_CHARS or _CONTROL_RE.search(value):
        raise ArtifactLineageError("working_representation_ref must be bounded control-free text")
    lowered = value.lower()
    if (
        re.match(r"^[A-Za-z]:[\\/]", value)
        or value.startswith(("\\\\", "/", "file:", "file://"))
        or "file://" in lowered
        or "://" in lowered
        or ".." in value
        or "?" in value
        or "#" in value
        or " " in value
        or "=" in value
        or ";" in value
        or "," in value
        or lowered.startswith(("bearer ", "basic ", "token "))
    ):
        raise ArtifactLineageError(
            "working_representation_ref must be an opaque reference without URL/credential/local-path material"
        )
    for prefix in _CREDENTIAL_PREFIXES:
        if lowered.startswith(prefix + ":"):
            raise ArtifactLineageError("working_representation_ref must not carry credential-like material")
    return value


def _bounded_sha256(value: str) -> str:
    digest = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(digest):
        raise ArtifactLineageError("integrity ref must be a lowercase SHA-256 digest")
    return digest


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ArtifactLineageError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class LineageArtifactRef:
    """``(artifact_id, integrity_ref)`` binding to an existing canonical artifact.

    Deliberately not a second artifact record: no filename, media type, size or
    kind. A ref derived from ``CanonicalArtifactRecord`` is mechanically bound
    to #3594's record. A directly constructed ref is accepted under the input
    precondition that the existing artifact authority/caller already resolved
    it from a canonical artifact; this module validates shape/integrity format
    but does not attest registry existence.
    """

    artifact_id: str
    integrity_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _bounded_id(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "integrity_ref", _bounded_sha256(self.integrity_ref))

    def public_projection(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "integrity_ref": self.integrity_ref}


def ref_from_canonical_artifact(record: CanonicalArtifactRecord) -> LineageArtifactRef:
    """Adapter: #3594 canonical artifact -> lineage ref (identity + integrity only).

    This is the mechanically verifiable adapter when the canonical record is
    available: the lineage consumes the artifact record and copies exactly two
    fields out of it. ``declare_lineage`` also accepts a pre-resolved
    ``LineageArtifactRef``; canonical origin of that direct ref is an input
    precondition, not an attestation by this module.
    """

    if not isinstance(record, CanonicalArtifactRecord):
        raise ArtifactLineageError("adapter source must be a CanonicalArtifactRecord")
    return LineageArtifactRef(artifact_id=record.artifact_id, integrity_ref=record.integrity_ref)


def _coerce_ref(value: Any, field_name: str) -> LineageArtifactRef:
    if isinstance(value, LineageArtifactRef):
        return value
    if isinstance(value, CanonicalArtifactRecord):
        return ref_from_canonical_artifact(value)
    raise ArtifactLineageError(
        f"{field_name} must be a LineageArtifactRef or a CanonicalArtifactRecord"
    )


@dataclass(frozen=True, slots=True)
class ArtifactLineage:
    """Provider-neutral lineage: source -> optional working copy -> output(s).

    Frozen, metadata-only, and never the content. ``source`` is required and
    immutable; ``working`` and ``working_representation_ref`` are optional and
    mutually exclusive; ``outputs`` may be empty (a lineage may be declared
    before any output exists).
    """

    lineage_id: str
    source: LineageArtifactRef
    transformation_kind: str
    workspace_ref: str
    run_ref: str
    created_at: datetime
    outputs: tuple[LineageArtifactRef, ...] = ()
    working: LineageArtifactRef | None = None
    working_representation_ref: str | None = None
    operation_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "lineage_id", _bounded_id(self.lineage_id, "lineage_id"))
        object.__setattr__(self, "source", _coerce_ref(self.source, "source"))
        object.__setattr__(
            self, "transformation_kind", _bounded_id(self.transformation_kind, "transformation_kind")
        )
        object.__setattr__(self, "workspace_ref", _bounded_ref(self.workspace_ref, "workspace_ref"))
        object.__setattr__(self, "run_ref", _bounded_ref(self.run_ref, "run_ref"))
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))

        outputs = _bounded_outputs(self.outputs)
        object.__setattr__(self, "outputs", outputs)

        if self.working is not None:
            object.__setattr__(self, "working", _coerce_ref(self.working, "working"))
        if self.working_representation_ref is not None:
            object.__setattr__(
                self,
                "working_representation_ref",
                _bounded_representation_ref(self.working_representation_ref),
            )
        if self.operation_ref is not None:
            object.__setattr__(self, "operation_ref", _bounded_ref(self.operation_ref, "operation_ref"))

        self._enforce_invariants(outputs)

    def _enforce_invariants(self, outputs: tuple[LineageArtifactRef, ...]) -> None:
        source_id = self.source.artifact_id
        working_id = self.working.artifact_id if self.working is not None else None
        representation_ref = self.working_representation_ref

        if working_id is not None and working_id == source_id:
            raise ArtifactLineageError(
                "working copy must not alias the source artifact id (WORKING_COPY_REPLACES_SOURCE=NO)"
            )
        if working_id is not None and representation_ref is not None:
            raise ArtifactLineageError(
                "working_artifact_id and working_representation_ref are mutually exclusive"
            )
        if representation_ref is not None and representation_ref == source_id:
            raise ArtifactLineageError("working representation must not alias the source artifact id")

        seen: set[str] = set()
        for output in outputs:
            if output.artifact_id == source_id:
                raise ArtifactLineageError("source artifact must not be listed as an output")
            if working_id is not None and output.artifact_id == working_id:
                raise ArtifactLineageError("working artifact must not be listed as an output")
            if representation_ref is not None and output.artifact_id == representation_ref:
                raise ArtifactLineageError("working representation must not be listed as an output")
            if output.artifact_id in seen:
                raise ArtifactLineageError("output artifact ids must be distinct")
            seen.add(output.artifact_id)

    @property
    def source_artifact_id(self) -> str:
        return self.source.artifact_id

    @property
    def source_integrity_ref(self) -> str:
        return self.source.integrity_ref

    @property
    def working_artifact_id(self) -> str | None:
        return self.working.artifact_id if self.working is not None else None

    @property
    def working_integrity_ref(self) -> str | None:
        return self.working.integrity_ref if self.working is not None else None

    @property
    def output_artifact_ids(self) -> tuple[str, ...]:
        return tuple(output.artifact_id for output in self.outputs)

    @property
    def output_integrity_refs(self) -> tuple[str, ...]:
        return tuple(output.integrity_ref for output in self.outputs)

    def public_projection(self) -> dict[str, Any]:
        """JSON-safe metadata-only projection (never bytes, never secrets).

        The raw ``working_representation_ref`` is intentionally absent: like
        #3594's raw ``location_ref``, it is a handle whose meaning belongs to
        the consumer. Only its presence is projected.
        """

        projection: dict[str, Any] = {
            "contract_version": "claw-canonical-artifact-lineage.v1",
            "lineage_id": self.lineage_id,
            "source_artifact_id": self.source.artifact_id,
            "source_integrity_ref": self.source.integrity_ref,
            "transformation_kind": self.transformation_kind,
            "workspace_ref": self.workspace_ref,
            "run_ref": self.run_ref,
            "created_at": _iso(self.created_at),
            "output_artifact_ids": list(self.output_artifact_ids),
            "output_integrity_refs": list(self.output_integrity_refs),
            "working_copy_optional": True,
            "working_copy_replaces_source": False,
            "raw_bytes_in_lineage": False,
        }
        if self.working is not None:
            projection["working_artifact_id"] = self.working.artifact_id
            projection["working_integrity_ref"] = self.working.integrity_ref
        if self.working_representation_ref is not None:
            projection["working_representation_present"] = True
        if self.operation_ref is not None:
            projection["operation_ref"] = self.operation_ref
        return projection


def _bounded_outputs(value: Any) -> tuple[LineageArtifactRef, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Iterable):
        raise ArtifactLineageError("outputs must be a sequence of artifact refs")
    items = tuple(value)
    if len(items) > MAX_OUTPUT_ARTIFACTS:
        raise ArtifactLineageError(
            f"outputs must not exceed MAX_OUTPUT_ARTIFACTS ({MAX_OUTPUT_ARTIFACTS})"
        )
    resolved = tuple(_coerce_ref(item, "output") for item in items)
    return resolved


def declare_lineage(
    *,
    lineage_id: str,
    source: Any,
    transformation_kind: str,
    workspace_ref: str,
    run_ref: str,
    created_at: datetime,
    outputs: Iterable[Any] = (),
    working: Any = None,
    working_representation_ref: str | None = None,
    operation_ref: str | None = None,
) -> ArtifactLineage:
    """Single entry point for lineage declaration (validation included).

    ``source`` / ``working`` / each output accept either a
    ``LineageArtifactRef`` or a #3594 ``CanonicalArtifactRecord``. Passing the
    record gives this module a mechanically verifiable adapter path. Passing a
    ref directly means canonical registration was already resolved upstream;
    this module does not contain or query a registry to attest that provenance.
    """

    return ArtifactLineage(
        lineage_id=lineage_id,
        source=source,
        transformation_kind=transformation_kind,
        workspace_ref=workspace_ref,
        run_ref=run_ref,
        created_at=created_at,
        outputs=outputs,
        working=working,
        working_representation_ref=working_representation_ref,
        operation_ref=operation_ref,
    )
