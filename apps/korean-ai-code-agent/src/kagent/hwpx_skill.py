"""#2937: bounded native HWPX Skill foundation — inspect / read / validate.

This module is a facade and receipt layer over authorities that already exist
and are already accepted. It introduces no ZIP walker, no XML parser, no host
filesystem extraction, no network/provider call and no new runtime dependency.

Composition order (the common gate always runs first)::

    raw HWPX bytes
    -> kagent.file_intake_safety.inspect_file()      (#2824 common gate)
    -> truthful HWPX_CANDIDATE (content, never extension-only)
    -> kagent.document_intake.intake_document()      (routing + isolated Core parse)
    -> bounded HWPX Skill receipt

Authority boundaries
--------------------
- ``inspect_file`` remains the single archive/path/expansion/MIME gate
  (``SECOND_ARCHIVE_GATE_AUTHORITY=0``).
- Core ``extract_hwpx_text`` (via ``intake_document``'s isolated parser
  boundary) remains the single HWPX text parser
  (``SECOND_HWPX_PARSER_AUTHORITY=0``, ``SECOND_XML_AUTHORITY=0``).
- The file extension is advisory; admission requires the gate's
  ``HWPX_CANDIDATE`` decision (``DIRECT_EXTENSION_AUTHORITY=NO``).
- Receipts expose bounded metadata and bounded reason vocabulary only: never
  raw ZIP member names, raw XML, payload bytes or host paths.

Capability mapping uses existing reserved ids — no Skill Registry edit:
``hwpx.inspect`` foundation is served under ``CAPABILITY_FILE_INSPECT``
(``file.inspect``), ``hwpx.read`` under ``CAPABILITY_HWPX_READ``, and
``hwpx.validate`` under ``CAPABILITY_HWPX_VALIDATE``.

Scope honesty (#2825 parent remains OPEN): this child does not implement
create, edit, template-fill, table insertion or image insertion. Validation
scope is package gate admission plus Core text extraction
(``VALIDATION_SCOPE_GATE_AND_TEXT``); full HWPX specification conformance is
never claimed (``full_spec_support_claimed=False`` on every receipt).
"""

from __future__ import annotations

from dataclasses import dataclass

from .claw_skill_registry import (
    CAPABILITY_FILE_INSPECT,
    CAPABILITY_HWPX_READ,
    CAPABILITY_HWPX_VALIDATE,
)
from .document_intake import intake_document
from .document_parser_contract import is_bounded_reason_code
from .file_intake_safety import DetectedFormat, FileIntakeResult, inspect_file

__all__ = [
    "ACCEPTANCE",
    "HWPX_MEDIA_TYPE",
    "REASON_CONTENT_MISMATCH",
    "REASON_HWpx_ROUTE_REQUIRED",
    "REASON_INTAKE_REJECTED",
    "STATUS_OK",
    "STATUS_REFUSED",
    "VALIDATION_SCOPE_GATE_AND_TEXT",
    "HwpxGateMetadata",
    "HwpxInspectReceipt",
    "HwpxReadReceipt",
    "HwpxValidateReceipt",
    "hwpx_inspect",
    "hwpx_read",
    "hwpx_validate",
]

HWPX_MEDIA_TYPE = "application/hwp+zip"

STATUS_OK = "ok"
STATUS_REFUSED = "refused"

REASON_CONTENT_MISMATCH = "content_mismatch"
REASON_HWpx_ROUTE_REQUIRED = "hwpx_route_required"
REASON_INTAKE_REJECTED = "intake_rejected"

#: The only validation claim this foundation makes: the common gate admitted
#: the package and the existing Core parser produced (or refused) text.
VALIDATION_SCOPE_GATE_AND_TEXT = "gate_admission_and_text_extraction"

ACCEPTANCE: dict[str, str] = {
    "HWPX_INSPECT_FOUNDATION": "PASS",
    "HWPX_READ_FOUNDATION": "PASS",
    "HWPX_VALIDATE_FOUNDATION": "PASS",
    "COMMON_FILE_INTAKE_GATE_REUSED": "YES",
    "DIRECT_EXTENSION_AUTHORITY": "NO",
    "SECOND_HWPX_PARSER_AUTHORITY": "0",
    "SECOND_ARCHIVE_GATE_AUTHORITY": "0",
    "SECOND_XML_AUTHORITY": "0",
    "HOST_FS_EXTRACTION": "0",
    "RAW_XML_PUBLIC_OUTPUT": "0",
    "PAYLOAD_PUBLIC_OUTPUT": "0",
    "UNSUPPORTED_FEATURES_EXPLICIT": "YES",
    "NEW_RUNTIME_DEPENDENCY": "0",
    "NETWORK_CALLS": "0",
    "PROVIDER_CALLS": "0",
    "EXTERNAL_SEND": "0",
    "PRODUCTION_MUTATION": "0",
    "HWPX_CREATE": "NOT_CLAIMED",
    "HWPX_EDIT": "NOT_CLAIMED",
    "HWPX_TEMPLATE_FILL": "NOT_CLAIMED",
    "TABLE_INSERT": "NOT_CLAIMED",
    "IMAGE_INSERT": "NOT_CLAIMED",
}


def _require_receipt_fields(status: str, reason_code: str) -> None:
    if status not in (STATUS_OK, STATUS_REFUSED):
        raise ValueError("hwpx_skill: receipt status must be ok or refused")
    if not is_bounded_reason_code(reason_code):
        raise ValueError("hwpx_skill: receipt reason_code must be a bounded identifier")
    if status == STATUS_OK and reason_code != "ok":
        raise ValueError("hwpx_skill: an ok receipt must carry reason_code ok")
    if status == STATUS_REFUSED and reason_code == "ok":
        raise ValueError("hwpx_skill: a refused receipt must not claim reason ok")


@dataclass(frozen=True, slots=True)
class HwpxGateMetadata:
    """Bounded projection of the common gate result.

    Mirrors ``FileIntakeResult.safe_dict`` minus the filename: media type,
    byte size, archive counts, depth, mismatch/encrypted/safety state only.
    Never contains entry names, entry contents, raw bytes or any path.
    """

    decision: str
    reason_code: str
    detected_format: str
    detected_media_type: str
    extension_media_type: str | None
    mismatch: bool
    encrypted: bool
    byte_size: int
    archive_entry_count: int
    archive_uncompressed_bytes: int
    archive_depth: int
    safe_to_parse: bool
    hwpx_candidate: bool

    def __post_init__(self) -> None:
        if not is_bounded_reason_code(self.reason_code):
            raise ValueError("hwpx_skill: gate reason_code must be a bounded identifier")

    @classmethod
    def from_gate(cls, gate: FileIntakeResult) -> HwpxGateMetadata:
        return cls(
            decision=gate.decision.value,
            reason_code=gate.reason_code,
            detected_format=gate.detected_format.value,
            detected_media_type=gate.detected_media_type,
            extension_media_type=gate.extension_media_type,
            mismatch=gate.mismatch,
            encrypted=gate.encrypted,
            byte_size=gate.raw_bytes,
            archive_entry_count=gate.archive_entry_count,
            archive_uncompressed_bytes=gate.archive_uncompressed_bytes,
            archive_depth=gate.archive_depth_reached,
            safe_to_parse=gate.safe_to_parse,
            hwpx_candidate=gate.detected_format is DetectedFormat.HWPX_CANDIDATE,
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "reason_code": self.reason_code,
            "detected_format": self.detected_format,
            "detected_media_type": self.detected_media_type,
            "extension_media_type": self.extension_media_type,
            "mismatch": self.mismatch,
            "encrypted": self.encrypted,
            "byte_size": self.byte_size,
            "archive_entry_count": self.archive_entry_count,
            "archive_uncompressed_bytes": self.archive_uncompressed_bytes,
            "archive_depth": self.archive_depth,
            "safe_to_parse": self.safe_to_parse,
            "hwpx_candidate": self.hwpx_candidate,
        }


@dataclass(frozen=True, slots=True)
class HwpxInspectReceipt:
    """Bounded hwpx.inspect result over the common gate only (no parser run)."""

    status: str
    capability_id: str
    reason_code: str
    gate: HwpxGateMetadata

    def __post_init__(self) -> None:
        _require_receipt_fields(self.status, self.reason_code)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "gate": self.gate.to_public_dict(),
        }


@dataclass(frozen=True, slots=True)
class HwpxReadReceipt:
    """Bounded hwpx.read result: extracted text on success, note/reason only on refusal."""

    status: str
    capability_id: str
    reason_code: str
    note: str | None
    text: str | None

    def __post_init__(self) -> None:
        _require_receipt_fields(self.status, self.reason_code)
        if self.status == STATUS_OK and self.text is None:
            raise ValueError("hwpx_skill: an ok read receipt must carry text")
        if self.status == STATUS_REFUSED and self.text is not None:
            raise ValueError("hwpx_skill: a refused read receipt must not carry text")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "note": self.note,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class HwpxValidateReceipt:
    """Bounded hwpx.validate result: gate metadata + parse outcome, scope-explicit.

    ``full_spec_support_claimed`` is always False: this foundation validates
    package admission and text extraction only, and never silently claims that
    every HWPX construct is supported.
    """

    status: str
    capability_id: str
    reason_code: str
    note: str | None
    scope: str
    full_spec_support_claimed: bool
    text_present: bool
    gate: HwpxGateMetadata

    def __post_init__(self) -> None:
        _require_receipt_fields(self.status, self.reason_code)
        if self.scope != VALIDATION_SCOPE_GATE_AND_TEXT:
            raise ValueError("hwpx_skill: scope must stay at gate admission and text extraction")
        if self.full_spec_support_claimed:
            raise ValueError("hwpx_skill: full HWPX spec support is never claimed")
        if self.status == STATUS_OK and not self.text_present:
            raise ValueError("hwpx_skill: an ok validate receipt must report text_present")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "note": self.note,
            "scope": self.scope,
            "full_spec_support_claimed": self.full_spec_support_claimed,
            "text_present": self.text_present,
            "gate": self.gate.to_public_dict(),
        }


def _gate_refusal(gate: FileIntakeResult) -> str | None:
    """Bounded stage-one refusal code, or None once HWPX_CANDIDATE is confirmed."""

    if not gate.safe_to_parse:
        return gate.reason_code
    if gate.detected_format is not DetectedFormat.HWPX_CANDIDATE:
        return REASON_CONTENT_MISMATCH
    return None


def hwpx_inspect(filename: str, payload: bytes) -> HwpxInspectReceipt:
    """Bounded HWPX inspection over the common gate. Runs no parser.

    Admits only a truthful ``HWPX_CANDIDATE``: content decides, the
    extension stays advisory. Refusals carry the gate's bounded reason code
    or ``content_mismatch`` with the detected format in the gate metadata.
    """

    gate = inspect_file(filename, payload)
    metadata = HwpxGateMetadata.from_gate(gate)
    refusal = _gate_refusal(gate)
    if refusal is None:
        return HwpxInspectReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_FILE_INSPECT,
            reason_code="ok",
            gate=metadata,
        )
    return HwpxInspectReceipt(
        status=STATUS_REFUSED,
        capability_id=CAPABILITY_FILE_INSPECT,
        reason_code=refusal,
        gate=metadata,
    )


def hwpx_read(filename: str, payload: bytes) -> HwpxReadReceipt:
    """Bounded HWPX text extraction.

    Runs the common gate first, requires ``HWPX_CANDIDATE``, then reuses
    ``intake_document`` (which re-runs the same gate before its isolated Core
    parse). Refusals surface a bounded reason code plus, when the refusal came
    from the existing intake/parser layer, that layer's existing bounded note.
    """

    gate = inspect_file(filename, payload)
    refusal = _gate_refusal(gate)
    if refusal is not None:
        return HwpxReadReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_READ,
            reason_code=refusal,
            note=None,
            text=None,
        )

    intake = intake_document(filename, payload)
    if intake is None:
        return HwpxReadReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_READ,
            reason_code=REASON_HWpx_ROUTE_REQUIRED,
            note=None,
            text=None,
        )
    if intake.text is not None:
        return HwpxReadReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_HWPX_READ,
            reason_code="ok",
            note=None,
            text=intake.text,
        )
    return HwpxReadReceipt(
        status=STATUS_REFUSED,
        capability_id=CAPABILITY_HWPX_READ,
        reason_code=REASON_INTAKE_REJECTED,
        note=intake.note,
        text=None,
    )


def hwpx_validate(filename: str, payload: bytes) -> HwpxValidateReceipt:
    """Bounded HWPX validation receipt: gate result composed with parser result.

    Malformed, encrypted, unsafe-path, archive-bomb, mimetype-mismatch and
    missing section/package cases remain refusals at the gate stage. An
    admitted package that the Core parser rejects (corrupt section XML, no
    extractable text) is refused with the existing bounded intake note.
    Scope stays ``gate_admission_and_text_extraction``; full specification
    conformance is never claimed.
    """

    gate = inspect_file(filename, payload)
    metadata = HwpxGateMetadata.from_gate(gate)
    refusal = _gate_refusal(gate)
    if refusal is not None:
        return HwpxValidateReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_VALIDATE,
            reason_code=refusal,
            note=None,
            scope=VALIDATION_SCOPE_GATE_AND_TEXT,
            full_spec_support_claimed=False,
            text_present=False,
            gate=metadata,
        )

    read = hwpx_read(filename, payload)
    if read.status == STATUS_OK:
        return HwpxValidateReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_HWPX_VALIDATE,
            reason_code="ok",
            note=None,
            scope=VALIDATION_SCOPE_GATE_AND_TEXT,
            full_spec_support_claimed=False,
            text_present=read.text is not None and read.text != "",
            gate=metadata,
        )
    return HwpxValidateReceipt(
        status=STATUS_REFUSED,
        capability_id=CAPABILITY_HWPX_VALIDATE,
        reason_code=read.reason_code,
        note=read.note,
        scope=VALIDATION_SCOPE_GATE_AND_TEXT,
        full_spec_support_claimed=False,
        text_present=False,
        gate=metadata,
    )
