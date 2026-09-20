"""#2013/#2824-S2: gated binary-document intake for the review and draft flows.

Composition order — the gate always runs before any Core parser:

.. code-block:: text

    raw bytes
    -> inspect_file()                  (common pre-parser safety gate, #2824)
    -> admission decision
    -> supported document routing
    -> padiem_ai_core extract_binary_document()

``kagent.file_intake_safety.inspect_file`` is the single admission authority and
`:mod:`kagent.document_intake` stays the routing layer. No Core parser call can
happen for input the gate denied, and the file extension is a *claim* about the
content that the gate has to confirm rather than an authority:

* ``.pdf`` is admitted only when the gate's content signature is PDF, so a PNG,
  JPEG or ZIP renamed ``.pdf`` never reaches the parser (``PDF_EXTENSION !=
  PDF_AUTHORITY``);
* ``.hwpx`` is admitted only when the gate returns ``HWPX_CANDIDATE`` after its
  structural preflight (``mimetype`` + ``Contents/section``), so a plain ZIP
  renamed ``.hwpx`` is rejected before extraction;
* ``.docx`` is admitted only after the gate's archive walk passed and the
  existing OOXML signature is present; Core OOXML validation still runs after
  that, and archive path/nesting/expansion rejections cannot be bypassed;
* legacy ``.hwp`` keeps its existing unsupported posture, but the gate runs
  first so OLE2 content is inspected before the deterministic note is returned.
  No HWP parser is added.

Rejections are reported as bounded notes carrying the gate's ``reason_code``
only — never raw bytes, host paths, archive member content, exception text or
credentials. Inputs with no supported document route (plain text, images,
unknown extensions) still return ``None`` so the caller's existing UTF-8 text
path is unchanged, and no image parser authority is introduced here.

HWPX read support landed in #2012; legacy ``.hwp`` stays unsupported by decision
(OLE2 compound binary) and yields a deterministic note. A Core rejection
(encrypted, corrupt, over-limit, dependency-unavailable, no extractable text /
OCR disabled) yields a note carrying the Core reason code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from padiem_ai_core.document_normalization import (
    DocumentNormalizationError,
    extract_binary_document,
)

from .file_intake_safety import DetectedFormat, FileIntakeResult, inspect_file

PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
HWPX_MEDIA_TYPE = "application/hwp+zip"

LEGACY_HWP_NOTE = "legacy HWP 미지원(OLE2 바이너리, #2012 결정)"

# Existing OOXML routing signature. It is a *routing* discriminator between a
# DOCX and a generic ZIP container, not archive policy: every archive bound is
# enforced by the gate before this is consulted.
DOCX_SIGNATURE = b"word/document.xml"

_MEDIA_BY_SUFFIX = {
    ".pdf": PDF_MEDIA_TYPE,
    ".docx": DOCX_MEDIA_TYPE,
    ".hwpx": HWPX_MEDIA_TYPE,
}

# The content signature the gate must report for each routed suffix. A route is
# a claim; the gate validates it. Nothing is admitted on extension alone.
_REQUIRED_FORMAT_BY_SUFFIX = {
    ".pdf": DetectedFormat.PDF,
    ".docx": DetectedFormat.ZIP_CONTAINER,
    ".hwpx": DetectedFormat.HWPX_CANDIDATE,
}

_LEGACY_HWP_SUFFIXES = frozenset({".hwp"})

# Bounded note vocabulary. ``reason_code`` and ``detected_format`` are bounded
# enumerations, so a note can carry them without exposing payload, path or
# exception detail.
GATE_REJECTION_NOTE_PREFIX = "file_intake_rejected:"
ROUTE_MISMATCH_NOTE_PREFIX = f"{GATE_REJECTION_NOTE_PREFIX}content_mismatch:"
DOCX_SIGNATURE_MISSING_NOTE = f"{GATE_REJECTION_NOTE_PREFIX}document_signature_missing"


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """Outcome of a document intake attempt.

    ``text`` is set on a successful binary-document extraction; ``note`` is set
    when the file must be skipped (legacy ``.hwp``, a pre-parser gate rejection,
    or Core rejection). When both are ``None`` the file is not a routed document
    and the caller falls back to the existing UTF-8 text path.
    """

    text: str | None = None
    note: str | None = None


def _rejection_note(exc: DocumentNormalizationError) -> str:
    code = exc.code
    if code == "pdf_empty_text":
        return f"PDF 텍스트 추출 불가(OCR 미지원) — {code}"
    if code == "document_dependency_unavailable":
        return f"문서 추출 의존성 미설치 — {code}"
    return f"문서 변환 실패 — {code}"


def _gate_rejection_note(result: FileIntakeResult) -> str:
    """Bounded note for a file the pre-parser gate refused to admit."""

    return f"{GATE_REJECTION_NOTE_PREFIX}{result.reason_code}"


def _route_mismatch_note(result: FileIntakeResult) -> str:
    """Bounded note for content that disagrees with the routed extension.

    The detected format is part of the gate's bounded vocabulary, so the note
    reports the real content class without quoting the payload or the name.
    """

    return f"{ROUTE_MISMATCH_NOTE_PREFIX}{result.detected_format.value}"


def intake_document(name: str, data: bytes) -> IntakeResult | None:
    """Run the pre-parser gate, then route an admitted document to Core.

    Returns an ``IntakeResult`` for PDF/DOCX/HWPX inputs and for legacy ``.hwp``
    inputs, or ``None`` when the file has no supported document route and the
    caller should carry on with the existing text path. Every return path
    except ``None`` means the common gate executed at this boundary.
    """

    suffix = Path(name).suffix.lower()
    is_supported_route = (
        suffix in _MEDIA_BY_SUFFIX or suffix in _LEGACY_HWP_SUFFIXES
    )

    # The common gate runs for every input that crosses this boundary, before
    # any routing or parser admission decision.
    gate = inspect_file(name, data)

    if not is_supported_route:
        # Plain text, images and unknown extensions keep the existing caller
        # text path. No parser authority is added for them here.
        return None

    if suffix in _LEGACY_HWP_SUFFIXES:
        # Gate executed first; the unsupported product posture is unchanged and
        # no HWP parser exists.
        return IntakeResult(note=LEGACY_HWP_NOTE)

    if not gate.safe_to_parse:
        return IntakeResult(note=_gate_rejection_note(gate))

    if gate.detected_format is not _REQUIRED_FORMAT_BY_SUFFIX[suffix]:
        # Content outranks the extension: a rename cannot buy parser admission.
        return IntakeResult(note=_route_mismatch_note(gate))

    if gate.detected_format is DetectedFormat.ZIP_CONTAINER and (
        DOCX_SIGNATURE not in data
    ):
        # An admitted ZIP container without the OOXML signature is not a DOCX.
        return IntakeResult(note=DOCX_SIGNATURE_MISSING_NOTE)

    try:
        document = extract_binary_document(
            name=name, media_type=_MEDIA_BY_SUFFIX[suffix], payload=data
        )
    except DocumentNormalizationError as exc:
        return IntakeResult(note=_rejection_note(exc))
    return IntakeResult(text=document.text)


__all__ = [
    "DOCX_SIGNATURE_MISSING_NOTE",
    "GATE_REJECTION_NOTE_PREFIX",
    "LEGACY_HWP_NOTE",
    "ROUTE_MISMATCH_NOTE_PREFIX",
    "IntakeResult",
    "intake_document",
]
