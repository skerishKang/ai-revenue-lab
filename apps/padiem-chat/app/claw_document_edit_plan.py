"""#3933: fail-closed structured document-edit proposal for the generic Claw.

This is NOT an XLSX editor, parser, filename resolver or permission grant.
The caller supplies a canonical #3580 artifact record resolved by existing
workspace/owner authority and the model explicitly selected by the user.
Actual file content, Office/Drive WRITE, output receipts and PDF fidelity are
owned by approved P01 + #3580 / LOCAL B tools. No implicit B66 dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from kagent.artifact_registration import CanonicalArtifactRecord

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_SHA = re.compile(r"^[a-f0-9]{64}$")
_MODEL = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_ALLOWED = frozenset({
    "source_artifact_id", "source_sha256", "model_id", "requested_edits",
    "output_formats", "preserve_unrequested", "overwrite_original",
})


class DocumentEditPlanRejected(ValueError):
    """Untrusted plan cannot be authorized or safely resolved."""


@dataclass(frozen=True, slots=True)
class DocumentFieldEdit:
    """Semantic proposal only: field-to-cell binding must be separately verified."""
    field: str
    value: str | int


@dataclass(frozen=True, slots=True)
class DocumentEditProposal:
    artifact_id: str
    integrity_ref: str
    workspace_ref: str
    run_ref: str
    model_id: str
    edits: tuple[DocumentFieldEdit, ...]
    output_formats: tuple[str, ...]

    def public_projection(self) -> dict[str, object]:
        # Never claim work happened, and do not project arbitrary model values.
        return {
            "contract_version": "claw-document-edit-proposal.v1",
            "source_artifact_id": self.artifact_id,
            "source_integrity_ref": self.integrity_ref,
            "requested_edit_fields": [item.field for item in self.edits],
            "requested_output_formats": list(self.output_formats),
            "selected_model_id": self.model_id,
            "preserve_unrequested": True,
            "overwrite_original": False,
            "authorization_minted": False,
            "file_modified": False,
            "pdf_exported": False,
            "fidelity_verified": False,
        }


def validate_document_edit_proposal(
    payload: object,
    *,
    trusted_source: CanonicalArtifactRecord,
    workspace_ref: str,
    run_ref: str,
    selected_model_id: str,
) -> DocumentEditProposal:
    """Validate a bounded proposal against SERVER-resolved immutable authority.

    Accepting it does not grant access, identify a workbook cell or start a
    tool. The separate approved executor must map each semantic selector to a
    single verified workbook location; ambiguity MUST halt execution.
    """
    if not isinstance(trusted_source, CanonicalArtifactRecord):
        raise DocumentEditPlanRejected("canonical source record required")
    if (trusted_source.artifact_kind != "source.xlsx"
            or trusted_source.media_type != _XLSX_MIME
            or not trusted_source.filename.lower().endswith(".xlsx")
            or not isinstance(trusted_source.integrity_ref, str)
            or _SHA.fullmatch(trusted_source.integrity_ref) is None
            or trusted_source.workspace_ref != workspace_ref
            or trusted_source.run_ref != run_ref
            or not isinstance(workspace_ref, str) or not workspace_ref
            or not isinstance(run_ref, str) or not run_ref):
        raise DocumentEditPlanRejected("untrusted or wrong-scope XLSX source")
    if (not isinstance(selected_model_id, str)
            or _MODEL.fullmatch(selected_model_id) is None):
        raise DocumentEditPlanRejected("exact user model selection required")
    if not isinstance(payload, dict) or type(payload) is not dict or set(payload) != _ALLOWED:
        raise DocumentEditPlanRejected("unexpected or missing plan fields")
    if (payload["source_artifact_id"] != trusted_source.artifact_id
            or payload["source_sha256"] != trusted_source.integrity_ref):
        raise DocumentEditPlanRejected("source identity/hash drift")
    if payload["model_id"] != selected_model_id:
        raise DocumentEditPlanRejected("model substitution or fallback forbidden")
    if payload["preserve_unrequested"] is not True or payload["overwrite_original"] is not False:
        raise DocumentEditPlanRejected("only copy-on-write is supported")

    inputs = payload["requested_edits"]
    if type(inputs) is not list or not 1 <= len(inputs) <= 16:
        raise DocumentEditPlanRejected("bounded requested edits required")
    edits: list[DocumentFieldEdit] = []
    seen: set[str] = set()
    for item in inputs:
        if type(item) is not dict or set(item) != {"field", "value"}:
            raise DocumentEditPlanRejected("only semantic field/value edits allowed")
        name, value = item["field"], item["value"]
        if not isinstance(name, str) or _FIELD.fullmatch(name) is None or name in seen:
            raise DocumentEditPlanRejected("invalid or duplicated semantic field")
        if type(value) is str:
            if (not 1 <= len(value) <= 240
                    or value.lstrip().startswith(("=", "+", "-", "@"))
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise DocumentEditPlanRejected("untrusted or empty edit value")
        elif type(value) is int:
            if not -(10 ** 15) < value < (10 ** 15):
                raise DocumentEditPlanRejected("numeric edit exceeds bound")
        else:
            # Reject floats (money rounding), booleans, dicts, formulas/macros.
            raise DocumentEditPlanRejected("only bounded literal text/integer changes supported")
        seen.add(name)
        edits.append(DocumentFieldEdit(name, value))
    output = payload["output_formats"]
    if type(output) is not list or not 1 <= len(output) <= 2:
        raise DocumentEditPlanRejected("bounded formats required")
    if (any(type(fmt) is not str or fmt not in {"xlsx", "pdf"} for fmt in output)
            or len(output) != len(set(output))):
        raise DocumentEditPlanRejected("unsupported/duplicate output format")
    return DocumentEditProposal(
        artifact_id=trusted_source.artifact_id,
        integrity_ref=trusted_source.integrity_ref,
        workspace_ref=workspace_ref,
        run_ref=run_ref,
        model_id=selected_model_id,
        edits=tuple(edits),
        output_formats=tuple(output),
    )
