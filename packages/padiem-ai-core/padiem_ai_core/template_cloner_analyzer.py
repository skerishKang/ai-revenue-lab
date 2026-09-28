"""Provider-neutral template-cloner analyzer adapter (#3185 phase A).

The adapter turns trusted document evidence into a bounded
:class:`~padiem_ai_core.document_template.DocumentTemplateCandidate`.

Pipeline::

    trusted evidence -> analyzer request -> injected executor boundary
                     -> bounded analyzer result -> validated candidate -> STOP

Hard boundaries:

* The executor is an injected boundary. Phase A ships no live route: a test
  double or an in-memory executor is used, and the concrete provider/model
  route stays an owner decision (#3143).
* Raw analyzer output is never trusted directly. It is validated field by field
  before a candidate is built.
* The adapter never approves, persists, defaults or activates anything. The
  candidate is where analysis stops; the product review flow owns approval.
* Source text and images are untrusted data. The adapter never interprets them
  as instructions and never lets them select a model, a tool or an approval.
* Evidence carries no raw bytes: vision evidence is described by media type,
  bounded size, hash and reference only, reusing the existing b14 multimodal
  bounds.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from .b14_multimodal import MAX_B14_IMAGE_BYTES, MAX_B14_MULTIMODAL_PARTS
from .document_normalization import ExtractionStatus, NormalizedDocument
from .document_parser_boundary import parse_binary_document_via_authority
from .document_template import (
    DOCUMENT_TEMPLATE_SCHEMA_VERSION,
    DocumentTemplateCandidate,
    DocumentTemplateError,
    DocumentTemplateSourceProvenance,
)
from .multimodal_execution_runtime import MultimodalExecutionRequest
from .template_cloner_skill import (
    TEMPLATE_CLONER_ANALYZER_KIND,
    TEMPLATE_CLONER_RENDERER_CONTRACT_REF,
    TEMPLATE_CLONER_TEMPLATE_KIND,
)

TEMPLATE_CLONER_ANALYZER_SCHEMA_VERSION = 1

ANALYZER_STATUS_COMPLETED = "completed"
ANALYZER_STATUS_TIMEOUT = "timeout"
ANALYZER_STATUS_TRANSPORT_ERROR = "transport_error"
ANALYZER_STATUS_UNAVAILABLE = "unavailable"

#: Reuse the existing multimodal part bound for how much evidence one request
#: may carry.
MAX_ANALYZER_EVIDENCE_ITEMS = MAX_B14_MULTIMODAL_PARTS
MAX_ANALYZER_EVIDENCE_TEXT_CHARS = 12_000
MAX_ANALYZER_INTENT_CHARS = 240
MAX_ANALYZER_UNKNOWNS = 32
MAX_ANALYZER_WARNINGS = 32
MAX_ANALYZER_EVIDENCE_REFS = 16
MAX_ANALYZER_REPORT_ITEMS = 16
MAX_ANALYZER_EVIDENCE_LABEL_CHARS = 60
MAX_ANALYZER_EVIDENCE_VALUE_CHARS = 200

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")
_CODE_RE = re.compile(r"^[a-z][a-z0-9._:-]{0,63}$")
_MEDIA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,63}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_PROFILE_FIELDS = ("structure_profile", "style_profile", "fixed_content", "variable_slots")

_ALLOWED_OUTPUT_KEYS = frozenset(
    {
        "name",
        "template_kind",
        "structure_profile",
        "style_profile",
        "fixed_content",
        "variable_slots",
        "warnings",
        "unknowns",
        "confidence",
        "evidence",
        "renderer_contract_ref",
    }
)

#: Keys the analyzer output may never carry. Enabled by the document_template
#: freeze step as well; declared here so the refusal code is explicit.
_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "approved",
        "approval",
        "approved_by_ref",
        "authority",
        "credential",
        "credentials",
        "api_key",
        "provider",
        "provider_id",
        "model",
        "model_id",
        "model_policy_ref",
        "tool",
        "tools",
        "connector",
        "connectors",
        "template_id",
        "fingerprint",
    }
)


class TemplateClonerAnalyzerError(ValueError):
    """Raised when the analyzer boundary cannot produce a valid candidate."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _ID_RE.fullmatch(code):
            raise ValueError("analyzer error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


class TemplateClonerEvidenceKind(str, Enum):
    NATIVE_DOCUMENT_TEXT = "native_document_text"
    VISION_IMAGE = "vision_image"


@dataclass(frozen=True, slots=True)
class TemplateClonerEvidence:
    """One bounded piece of evidence handed to the analyzer boundary."""

    kind: TemplateClonerEvidenceKind
    media_type: str
    text: str | None = None
    media_bytes: int | None = None
    page_count: int | None = None
    content_sha256: str | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TemplateClonerEvidenceKind):
            raise TemplateClonerAnalyzerError("invalid_analyzer_evidence", "evidence kind is invalid")
        if not isinstance(self.media_type, str) or not _MEDIA_RE.fullmatch(self.media_type):
            raise TemplateClonerAnalyzerError("invalid_analyzer_evidence", "evidence media type is invalid")

        if self.page_count is not None:
            if isinstance(self.page_count, bool) or not isinstance(self.page_count, int) or self.page_count < 1:
                raise TemplateClonerAnalyzerError("invalid_analyzer_evidence", "page count is invalid")

        if self.content_sha256 is not None and (
            not isinstance(self.content_sha256, str) or not _SHA256_RE.fullmatch(self.content_sha256)
        ):
            raise TemplateClonerAnalyzerError("invalid_analyzer_evidence", "content hash is invalid")

        if self.evidence_ref is not None:
            if not isinstance(self.evidence_ref, str) or not _REF_RE.fullmatch(self.evidence_ref):
                raise TemplateClonerAnalyzerError("invalid_analyzer_evidence", "evidence reference is invalid")

        if self.kind is TemplateClonerEvidenceKind.NATIVE_DOCUMENT_TEXT:
            if not isinstance(self.text, str) or not self.text.strip():
                raise TemplateClonerAnalyzerError(
                    "invalid_analyzer_evidence", "native document evidence requires extracted text"
                )
            if len(self.text) > MAX_ANALYZER_EVIDENCE_TEXT_CHARS:
                raise TemplateClonerAnalyzerError(
                    "analyzer_evidence_budget_exceeded", "native document evidence is too large"
                )
            if self.media_bytes is not None:
                raise TemplateClonerAnalyzerError(
                    "invalid_analyzer_evidence", "native document evidence must not carry a media size"
                )
        else:
            if self.text is not None:
                raise TemplateClonerAnalyzerError(
                    "invalid_analyzer_evidence", "vision evidence must not carry document text"
                )
            if isinstance(self.media_bytes, bool) or not isinstance(self.media_bytes, int) or self.media_bytes < 1:
                raise TemplateClonerAnalyzerError(
                    "invalid_analyzer_evidence", "vision evidence requires a bounded media size"
                )
            if self.media_bytes > MAX_B14_IMAGE_BYTES:
                raise TemplateClonerAnalyzerError(
                    "analyzer_evidence_budget_exceeded",
                    "vision evidence exceeds the multimodal image bound",
                )

    @property
    def is_native(self) -> bool:
        return self.kind is TemplateClonerEvidenceKind.NATIVE_DOCUMENT_TEXT


@dataclass(frozen=True, slots=True)
class TemplateClonerAnalyzerRequest:
    request_id: str
    evidence: tuple[TemplateClonerEvidence, ...]
    source_provenance: DocumentTemplateSourceProvenance
    analysis_intent: str
    evidence_refs: tuple[str, ...] = ()
    trace_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not _ID_RE.fullmatch(self.request_id):
            raise TemplateClonerAnalyzerError("invalid_analyzer_request", "request id is invalid")
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise TemplateClonerAnalyzerError("invalid_analyzer_request", "at least one evidence item is required")
        if len(self.evidence) > MAX_ANALYZER_EVIDENCE_ITEMS:
            raise TemplateClonerAnalyzerError("analyzer_evidence_budget_exceeded", "too many evidence items")
        if any(not isinstance(item, TemplateClonerEvidence) for item in self.evidence):
            raise TemplateClonerAnalyzerError("invalid_analyzer_request", "evidence items are invalid")
        if not isinstance(self.source_provenance, DocumentTemplateSourceProvenance):
            raise TemplateClonerAnalyzerError("invalid_analyzer_request", "source provenance is invalid")
        if not isinstance(self.analysis_intent, str) or not self.analysis_intent.strip():
            raise TemplateClonerAnalyzerError("invalid_analyzer_request", "analysis intent is required")
        if len(self.analysis_intent) > MAX_ANALYZER_INTENT_CHARS:
            raise TemplateClonerAnalyzerError("invalid_analyzer_request", "analysis intent is too large")
        if not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > MAX_ANALYZER_EVIDENCE_REFS:
            raise TemplateClonerAnalyzerError("invalid_analyzer_request", "evidence references are invalid")
        if any(not isinstance(ref, str) or not _REF_RE.fullmatch(ref) for ref in self.evidence_refs):
            raise TemplateClonerAnalyzerError("invalid_analyzer_request", "evidence references are invalid")
        if self.trace_id is not None:
            if not isinstance(self.trace_id, str) or not _ID_RE.fullmatch(self.trace_id):
                raise TemplateClonerAnalyzerError("invalid_analyzer_request", "trace id is invalid")

    @property
    def evidence_kinds(self) -> tuple[str, ...]:
        return tuple(sorted({item.kind.value for item in self.evidence}))

    @property
    def has_native_evidence(self) -> bool:
        return any(item.is_native for item in self.evidence)

    @property
    def has_vision_evidence(self) -> bool:
        return any(not item.is_native for item in self.evidence)


@dataclass(frozen=True, slots=True)
class TemplateClonerAnalyzerResult:
    """Bounded result returned by an analyzer executor."""

    status: str
    raw_payload: Mapping[str, Any] | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or not self.status:
            raise TemplateClonerAnalyzerError("invalid_analyzer_result", "analyzer status is required")
        if self.raw_payload is not None and not isinstance(self.raw_payload, Mapping):
            raise TemplateClonerAnalyzerError("invalid_analyzer_result", "analyzer payload must be a mapping")
        if self.failure_code is not None and (
            not isinstance(self.failure_code, str) or not _CODE_RE.fullmatch(self.failure_code)
        ):
            raise TemplateClonerAnalyzerError("invalid_analyzer_result", "analyzer failure code is invalid")


class TemplateClonerAnalyzerExecutor(Protocol):
    """Injected analyzer boundary.

    Phase A uses in-memory/test-double executors only. A live route stays an
    owner decision (#3143) and must not be selected from template content.
    """

    def execute(self, request: TemplateClonerAnalyzerRequest) -> TemplateClonerAnalyzerResult: ...


def _text(value: Any, name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TemplateClonerAnalyzerError("malformed_analyzer_output", f"{name} must be a non-empty string")
    text = value.strip()
    if len(text) > maximum:
        raise TemplateClonerAnalyzerError("analyzer_output_budget_exceeded", f"{name} is too large")
    return text


def _codes(value: Any, name: str, *, maximum: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TemplateClonerAnalyzerError("malformed_analyzer_output", f"{name} must be a sequence of codes")
    if len(value) > maximum:
        raise TemplateClonerAnalyzerError("analyzer_output_budget_exceeded", f"{name} exceeds its bound")
    codes: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _CODE_RE.fullmatch(item):
            raise TemplateClonerAnalyzerError("malformed_analyzer_output", f"{name} contains an invalid code")
        if item not in codes:
            codes.append(item)
    return tuple(codes)


def _evidence_report(value: Any) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TemplateClonerAnalyzerError("malformed_analyzer_output", "evidence must be a sequence")
    if len(value) > MAX_ANALYZER_REPORT_ITEMS:
        raise TemplateClonerAnalyzerError("analyzer_output_budget_exceeded", "evidence exceeds its bound")
    report: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TemplateClonerAnalyzerError("malformed_analyzer_output", "evidence items must be mappings")
        extra = set(item.keys()) - {"label", "value"}
        if extra:
            raise TemplateClonerAnalyzerError(
                "unsupported_analyzer_output_field", "evidence items carry unsupported fields"
            )
        label = _text(item.get("label"), "evidence label", maximum=MAX_ANALYZER_EVIDENCE_LABEL_CHARS)
        raw_value = item.get("value")
        if raw_value is None:
            raw_value = ""
        if not isinstance(raw_value, str):
            raise TemplateClonerAnalyzerError("malformed_analyzer_output", "evidence value must be a string")
        report.append((label, raw_value[:MAX_ANALYZER_EVIDENCE_VALUE_CHARS]))
    return tuple(report)


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TemplateClonerAnalyzerError("malformed_analyzer_output", "confidence must be a number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")) or number < 0.0 or number > 1.0:
        raise TemplateClonerAnalyzerError("malformed_analyzer_output", "confidence must be between 0 and 1")
    return number


def _is_empty_profile(value: Any) -> bool:
    """True when the analyzer reported no recognised facts for a profile."""
    if value is None:
        return True
    if isinstance(value, Mapping):
        return len(value) == 0
    if isinstance(value, (str, bytes)):
        return False
    if isinstance(value, Sequence):
        return len(value) == 0
    return False


_IMAGE_URL_RE = re.compile(
    r"^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)$"
)

#: Trusted allowlist for template *text* in ``fixed_content``. A key outside this
#: set is refused, so a faulty analyzer cannot promote source business values
#: (customer name, amount, date, quote number) into a frozen template field.
_ALLOWED_FIXED_CONTENT_KEYS = frozenset(
    {
        "title",
        "header",
        "footer",
        "mark",
        "memo_label",
        "empty_item_text",
        "supply_label",
        "vat_label",
        "grand_label",
        "sender_heading",
        "recipient_heading",
    }
)

#: Value shapes that are business data, never template text.
_MONEY_VALUE_RE = re.compile(r"(?:\d[\d,\s]{3,}|[₩$€]\s?\d|\d+\s?(?:원|만원|억))")
_DATE_VALUE_RE = re.compile(r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{4}\s?년)")


def _assert_fixed_content_is_template_text(value: Any) -> None:
    """Fail closed unless ``fixed_content`` is bounded template text."""
    if not isinstance(value, Mapping):
        return
    for key, item in value.items():
        if not isinstance(key, str) or key.strip() not in _ALLOWED_FIXED_CONTENT_KEYS:
            raise TemplateClonerAnalyzerError(
                "unsupported_fixed_content_key",
                "fixed content carries a key outside the template-text allowlist",
            )
        if isinstance(item, str) and (_MONEY_VALUE_RE.search(item) or _DATE_VALUE_RE.search(item)):
            raise TemplateClonerAnalyzerError(
                "business_value_in_fixed_content",
                "fixed content carries a source business value instead of template text",
            )


def _candidate_id(request: TemplateClonerAnalyzerRequest) -> str:
    digest = hashlib.sha256()
    digest.update(request.request_id.encode("utf-8"))
    digest.update(b"|")
    digest.update(request.source_provenance.source_ref.encode("utf-8"))
    digest.update(b"|")
    digest.update("|".join(request.evidence_kinds).encode("utf-8"))
    return "candidate-" + digest.hexdigest()[:24]


def analyze_template_candidate(
    request: TemplateClonerAnalyzerRequest,
    executor: TemplateClonerAnalyzerExecutor,
) -> DocumentTemplateCandidate:
    """Run the analyzer boundary and return a validated candidate.

    Any timeout, transport failure, unavailable status or malformed payload
    fails closed: no candidate is produced and nothing is written anywhere.
    """
    if not isinstance(request, TemplateClonerAnalyzerRequest):
        raise TemplateClonerAnalyzerError("invalid_analyzer_request", "request is invalid")
    if executor is None or not hasattr(executor, "execute"):
        raise TemplateClonerAnalyzerError("invalid_analyzer_executor", "analyzer executor is missing")

    try:
        result = executor.execute(request)
    except TemplateClonerAnalyzerError:
        raise
    except Exception as exc:  # noqa: BLE001 - transport failures must fail closed
        raise TemplateClonerAnalyzerError(
            "analyzer_transport_error", "analyzer boundary failed before returning a result"
        ) from exc

    if not isinstance(result, TemplateClonerAnalyzerResult):
        raise TemplateClonerAnalyzerError("malformed_analyzer_result", "analyzer returned an unexpected result")

    if result.status == ANALYZER_STATUS_TIMEOUT:
        raise TemplateClonerAnalyzerError("analyzer_timeout", "analyzer boundary timed out")
    if result.status == ANALYZER_STATUS_TRANSPORT_ERROR:
        raise TemplateClonerAnalyzerError("analyzer_transport_error", "analyzer boundary transport failed")
    if result.status != ANALYZER_STATUS_COMPLETED:
        raise TemplateClonerAnalyzerError("analyzer_unavailable", "analyzer boundary is unavailable")

    payload = result.raw_payload
    if not isinstance(payload, Mapping):
        raise TemplateClonerAnalyzerError("malformed_analyzer_output", "analyzer produced no payload")

    keys = set(payload.keys())
    forbidden = keys & _FORBIDDEN_OUTPUT_KEYS
    if forbidden:
        raise TemplateClonerAnalyzerError(
            "forbidden_analyzer_output_field",
            "analyzer output carries an authority or credential field",
        )
    unsupported = keys - _ALLOWED_OUTPUT_KEYS
    if unsupported:
        raise TemplateClonerAnalyzerError(
            "unsupported_analyzer_output_field", "analyzer output carries an unsupported field"
        )

    name = _text(payload.get("name"), "name", maximum=160)
    template_kind = payload.get("template_kind") or TEMPLATE_CLONER_TEMPLATE_KIND
    if not isinstance(template_kind, str) or not _ID_RE.fullmatch(template_kind):
        raise TemplateClonerAnalyzerError("malformed_analyzer_output", "template kind is invalid")

    warnings = _codes(payload.get("warnings"), "warnings", maximum=MAX_ANALYZER_WARNINGS)
    unknowns = list(_codes(payload.get("unknowns"), "unknowns", maximum=MAX_ANALYZER_UNKNOWNS))
    confidence = _confidence(payload.get("confidence"))
    evidence = _evidence_report(payload.get("evidence"))

    renderer_ref = payload.get("renderer_contract_ref") or TEMPLATE_CLONER_RENDERER_CONTRACT_REF
    if not isinstance(renderer_ref, str) or not _REF_RE.fullmatch(renderer_ref):
        raise TemplateClonerAnalyzerError("malformed_analyzer_output", "renderer contract reference is invalid")

    profiles: dict[str, Any] = {}
    for field in _PROFILE_FIELDS:
        value = payload.get(field)
        if value is None:
            value = [] if field == "variable_slots" else {}
        # Nothing recognised is not a fact: record it as unknown instead of
        # inventing a layout, and never fabricate a missing field.
        if _is_empty_profile(value):
            marker = f"unknown.{field}"
            if marker not in unknowns:
                unknowns.append(marker)
        profiles[field] = value

    if len(unknowns) > MAX_ANALYZER_UNKNOWNS:
        raise TemplateClonerAnalyzerError("analyzer_output_budget_exceeded", "unknowns exceed their bound")

    structure_profile = dict(profiles["structure_profile"])
    structure_profile["analyzer"] = {
        "kind": TEMPLATE_CLONER_ANALYZER_KIND,
        "schema_version": TEMPLATE_CLONER_ANALYZER_SCHEMA_VERSION,
        "unknowns": list(unknowns),
        "confidence": confidence,
        "evidence": [{"label": label, "value": value} for label, value in evidence],
        "evidence_refs": list(request.evidence_refs),
        "evidence_kinds": list(request.evidence_kinds),
        "source_media_types": sorted({item.media_type for item in request.evidence}),
    }

    try:
        _assert_fixed_content_is_template_text(profiles["fixed_content"])

        return DocumentTemplateCandidate(
            candidate_id=_candidate_id(request),
            schema_version=DOCUMENT_TEMPLATE_SCHEMA_VERSION,
            template_kind=template_kind,
            name=name,
            source_provenance=request.source_provenance,
            structure_profile=structure_profile,
            style_profile=profiles["style_profile"],
            fixed_content=profiles["fixed_content"],
            variable_slots=profiles["variable_slots"],
            renderer_contract_ref=renderer_ref,
            warnings=warnings,
        )
    except DocumentTemplateError as exc:
        raise TemplateClonerAnalyzerError(exc.code, exc.safe_message) from exc


def extract_native_document(*, name: Any, media_type: Any, payload: Any) -> NormalizedDocument:
    """Extract one binary document through the shared Core parser authority.

    This is the only binary entry point used here: no second parser is added.
    """
    return parse_binary_document_via_authority(name=name, media_type=media_type, payload=payload)


def multimodal_image_descriptor(request: MultimodalExecutionRequest) -> tuple[str, int]:
    """Read the validated image descriptor out of a canonical multimodal request.

    ``MultimodalExecutionRequest`` already validated the message parts through
    the existing B14 multimodal contract, so this only reads media type and
    decoded size back out; it never reaches into raw bytes itself.
    """
    if not isinstance(request, MultimodalExecutionRequest):
        raise TemplateClonerAnalyzerError(
            "invalid_analyzer_evidence", "a canonical multimodal request is required"
        )
    found: list[tuple[str, int]] = []
    for message in request.messages:
        content = message.get("content")
        if isinstance(content, (str, bytes)) or not isinstance(content, Sequence):
            continue
        for part in content:
            if not isinstance(part, Mapping) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if not isinstance(image_url, Mapping):
                continue
            url = image_url.get("url")
            if not isinstance(url, str):
                continue
            match = _IMAGE_URL_RE.fullmatch(url)
            if match is None:
                raise TemplateClonerAnalyzerError(
                    "invalid_analyzer_evidence", "multimodal image part is not a supported data URL"
                )
            padding = match.group(2)[-2:].count("=")
            decoded = (len(match.group(2)) // 4) * 3 - padding
            found.append((match.group(1), decoded))
    if len(found) != 1:
        raise TemplateClonerAnalyzerError(
            "invalid_analyzer_evidence", "exactly one image part is required for the vision branch"
        )
    media_type, media_bytes = found[0]
    if media_bytes < 1 or media_bytes > MAX_B14_IMAGE_BYTES:
        raise TemplateClonerAnalyzerError(
            "analyzer_evidence_budget_exceeded", "vision evidence exceeds the multimodal image bound"
        )
    return media_type, media_bytes


def build_native_document_request(
    *,
    request_id: str,
    document: NormalizedDocument,
    source_provenance: DocumentTemplateSourceProvenance,
    analysis_intent: str,
    content_sha256: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    trace_id: str | None = None,
) -> TemplateClonerAnalyzerRequest:
    """Build a native-branch request from the canonical Core normalized document.

    Arbitrary text can never enter this seam: only a ``NormalizedDocument``
    produced by the existing normalization/parser authority is accepted, and it
    must be a complete extraction.
    """
    if not isinstance(document, NormalizedDocument):
        raise TemplateClonerAnalyzerError(
            "invalid_analyzer_evidence", "native evidence requires a NormalizedDocument"
        )
    if document.status is not ExtractionStatus.COMPLETE:
        raise TemplateClonerAnalyzerError(
            "document_not_complete", "native evidence requires a complete extraction"
        )
    if source_provenance is not None and source_provenance.media_type is None:
        source_provenance = DocumentTemplateSourceProvenance(
            source_type=source_provenance.source_type,
            source_ref=source_provenance.source_ref,
            media_type=document.media_type,
            content_sha256=source_provenance.content_sha256 or content_sha256,
            trace_id=source_provenance.trace_id,
        )

    evidence = TemplateClonerEvidence(
        kind=TemplateClonerEvidenceKind.NATIVE_DOCUMENT_TEXT,
        media_type=document.media_type,
        text=document.text,
        page_count=len(document.segments) or None,
        content_sha256=content_sha256,
    )
    return TemplateClonerAnalyzerRequest(
        request_id=request_id,
        evidence=(evidence,),
        source_provenance=source_provenance,
        analysis_intent=analysis_intent,
        evidence_refs=evidence_refs,
        trace_id=trace_id,
    )


def build_vision_request(
    *,
    request_id: str,
    multimodal_request: MultimodalExecutionRequest,
    source_provenance: DocumentTemplateSourceProvenance,
    analysis_intent: str,
    content_sha256: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    trace_id: str | None = None,
) -> TemplateClonerAnalyzerRequest:
    """Build a vision-branch request on the canonical multimodal contract.

    The image descriptor is read out of an existing ``MultimodalExecutionRequest``
    (already validated by the B14 multimodal boundary). Only the descriptor
    travels into the candidate: media type, bounded size and a hash. No provider
    or model is selected here, and no live execution happens in phase A.
    """
    media_type, media_bytes = multimodal_image_descriptor(multimodal_request)
    evidence = TemplateClonerEvidence(
        kind=TemplateClonerEvidenceKind.VISION_IMAGE,
        media_type=media_type,
        media_bytes=media_bytes,
        content_sha256=content_sha256,
    )
    return TemplateClonerAnalyzerRequest(
        request_id=request_id,
        evidence=(evidence,),
        source_provenance=source_provenance,
        analysis_intent=analysis_intent,
        evidence_refs=evidence_refs,
        trace_id=trace_id or multimodal_request.trace_id,
    )


__all__ = [
    "ANALYZER_STATUS_COMPLETED",
    "ANALYZER_STATUS_TIMEOUT",
    "ANALYZER_STATUS_TRANSPORT_ERROR",
    "ANALYZER_STATUS_UNAVAILABLE",
    "MAX_ANALYZER_EVIDENCE_ITEMS",
    "MAX_ANALYZER_EVIDENCE_TEXT_CHARS",
    "MAX_ANALYZER_INTENT_CHARS",
    "MAX_ANALYZER_EVIDENCE_REFS",
    "MAX_ANALYZER_UNKNOWNS",
    "MAX_ANALYZER_WARNINGS",
    "TEMPLATE_CLONER_ANALYZER_SCHEMA_VERSION",
    "TemplateClonerAnalyzerError",
    "TemplateClonerAnalyzerExecutor",
    "TemplateClonerAnalyzerRequest",
    "TemplateClonerAnalyzerResult",
    "TemplateClonerEvidence",
    "TemplateClonerEvidenceKind",
    "analyze_template_candidate",
    "build_native_document_request",
    "build_vision_request",
    "extract_native_document",
    "multimodal_image_descriptor",
]
