"""#3934 owner-scoped artifact version labels from existing #3580 authority.

Source-only UI projection, not a registry, file service, ownership grant,
provenance mint, or assertion that the original workbook still exists.
Caller MUST supply canonical records resolved by existing owner-scoped
artifact/Drive port. No raw location, file bytes, local path, token escapes.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from kagent.artifact_lineage import ArtifactLineage, LineageArtifactRef
from kagent.artifact_registration import CanonicalArtifactRecord


class LineageDisplayDenied(ValueError):
    """Unavailable/unproven relation; never expose partial cross-scope refs."""


def _view(role: str, expected: LineageArtifactRef,
          record: CanonicalArtifactRecord) -> dict[str, Any]:
    if (not isinstance(record, CanonicalArtifactRecord)
            or expected.artifact_id != record.artifact_id
            or expected.integrity_ref != record.integrity_ref):
        raise LineageDisplayDenied("canonical ref integrity mismatch")
    return {
        "role": role,
        "artifact_id": record.artifact_id,
        "filename": record.filename,
        "media_type": record.media_type,
        "size_bytes": record.size_bytes,
        "integrity_ref": record.integrity_ref,
        "lifecycle": record.lifecycle.value,
        "open_available": False,
        "download_available": False,
        "restore_available": False,
    }


def build_authorized_lineage_display(
    *,
    lineage: ArtifactLineage,
    owner_resolved_records: Mapping[str, CanonicalArtifactRecord],
    authorized_workspace_ref: str,
    authorized_run_ref: str,
    verified_source_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Project only an EXACT authority-resolved source/working/output set.

    verified_source_bytes must be provided only after a fresh owner-authorized
    read of the ORIGINAL. Without it, do not claim source preservation.
    This module never reads files or verifies logged-in user identity.
    """
    if not isinstance(lineage, ArtifactLineage):
        raise LineageDisplayDenied("canonical lineage required")
    if (not isinstance(authorized_workspace_ref, str)
            or not isinstance(authorized_run_ref, str)
            or lineage.workspace_ref != authorized_workspace_ref
            or lineage.run_ref != authorized_run_ref):
        raise LineageDisplayDenied("lineage scope unavailable")
    if not isinstance(owner_resolved_records, Mapping):
        raise LineageDisplayDenied("owner records unavailable")
    refs = (lineage.source,) + (
        (lineage.working,) if lineage.working is not None else ()
    ) + lineage.outputs
    expected_ids = frozenset(ref.artifact_id for ref in refs)
    if set(owner_resolved_records) != expected_ids:
        raise LineageDisplayDenied("unresolved or extraneous material")
    cards: list[dict[str, Any]] = []
    for index, ref in enumerate(refs):
        record = owner_resolved_records.get(ref.artifact_id)
        if not isinstance(record, CanonicalArtifactRecord):
            raise LineageDisplayDenied("artifact ownership unavailable")
        if (record.workspace_ref != authorized_workspace_ref
                or record.run_ref != authorized_run_ref):
            raise LineageDisplayDenied("foreign artifact in relation")
        role = ("original" if index == 0 else
                "working_copy" if lineage.working is not None and index == 1
                else "output")
        cards.append(_view(role, ref, record))

    source_sha_matches = (
        type(verified_source_bytes) is bytes
        and hashlib.sha256(verified_source_bytes).hexdigest() == lineage.source.integrity_ref
        and len(verified_source_bytes) == owner_resolved_records[lineage.source.artifact_id].size_bytes
    )
    if verified_source_bytes is not None and not source_sha_matches:
        raise LineageDisplayDenied("source content proof mismatch")
    names: dict[str, int] = {}
    for card in cards:
        key = card["filename"].casefold()
        names[key] = names.get(key, 0) + 1
    ambiguous_names = sorted({
        card["filename"] for card in cards if names[card["filename"].casefold()] > 1
    })
    return {
        "contract_version": "claw-lineage-display.v1",
        "lineage_id": lineage.lineage_id,
        "cards": cards,
        "source_integrity_verified_now": bool(source_sha_matches),
        "original_preserved_claim_allowed": bool(source_sha_matches),
        "duplicate_name_needs_selection": bool(ambiguous_names),
        "ambiguous_filenames": ambiguous_names,
        "has_registered_working_copy": lineage.working is not None,
        "has_ephemeral_working_representation": lineage.working_representation_ref is not None,
        "raw_working_ref_exposed": False,
        "source_content_exposed": False,
        "provider_location_exposed": False,
        "all_open_download_restore_actions_disabled": True,
    }
