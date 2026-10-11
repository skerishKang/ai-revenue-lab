"""Product-neutral reusable document-template contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import re
from typing import TypeAlias

DOCUMENT_TEMPLATE_SCHEMA_VERSION = 1
MAX_TEMPLATE_NAME_CHARS = 160
MAX_TEMPLATE_SOURCE_REF_CHARS = 512
MAX_TEMPLATE_STRING_CHARS = 8192
MAX_TEMPLATE_COLLECTION_ITEMS = 256
MAX_TEMPLATE_NESTING_DEPTH = 8
MAX_TEMPLATE_NODES = 4096
MAX_TEMPLATE_DATA_BYTES = 128 * 1024
MAX_TEMPLATE_WARNINGS = 32
MAX_TEMPLATE_INTEGER_ABS = 2**63 - 1

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_WARNING = re.compile(r"^[a-z][a-z0-9._:-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MEDIA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,63}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
#: Keys that carry runtime authority, approval state, routing identity or
#: template identity. They are refused at *every* depth of template data, not
#: only at the top level: a nested object is exactly as capable of smuggling an
#: approval flag, a provider/model selector or a template identity as a top-level
#: one, so one recursive policy covers structure_profile, style_profile,
#: fixed_content and variable_slots alike. Compound names such as
#: ``approval_box`` are not exact matches and stay legal.
_FORBIDDEN_KEYS = frozenset({
    "authority", "authorization", "permission", "permissions",
    "permission_grant", "permission_grants", "tool_grant", "tool_grants",
    "allowed_tool_ids", "connector_grant", "connector_grants",
    "connector_requirement_ids", "entitlement", "entitlements",
    "entitlement_ref", "access_token", "refresh_token", "auth_token",
    "bearer_token", "api_key", "credential", "credentials", "secret",
    "secrets", "password", "private_key", "client_secret", "provider_id",
    "model_id", "model_policy_ref",
    # Approval state: a template candidate is unapproved by construction and no
    # profile may assert otherwise (#3185 B2).
    "approve", "approved", "approval", "approved_by", "approved_by_ref",
    # Routing identity: provider/model selection is owned outside template data.
    "provider", "model",
    # Tool and connector grants in their bare forms.
    "tool", "tools", "connector", "connectors",
    # Template identity: assigned by the product authority, never by content.
    "template_id", "fingerprint",
})
_SENSITIVE_KEY_PARTS = frozenset({
    "secret", "secrets", "password", "credential", "credentials", "token", "tokens",
})


class DocumentTemplateError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _ID.fullmatch(code):
            raise ValueError("document template error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True, slots=True)
class FrozenTemplateObject:
    items: tuple[tuple[str, "FrozenTemplateValue"], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple) or len(self.items) > MAX_TEMPLATE_COLLECTION_ITEMS:
            raise DocumentTemplateError(
                "invalid_document_template_data",
                "Frozen template object entries must be a bounded tuple.",
            )
        keys: list[str] = []
        for item in self.items:
            if not isinstance(item, tuple) or len(item) != 2:
                raise DocumentTemplateError(
                    "invalid_document_template_data",
                    "Frozen template object entries must be key/value pairs.",
                )
            key = item[0]
            if not isinstance(key, str) or not _KEY.fullmatch(key):
                raise DocumentTemplateError(
                    "invalid_document_template_data",
                    "Frozen template object keys must be bounded safe identifiers.",
                )
            keys.append(key)
        if len(keys) != len(set(keys)):
            raise DocumentTemplateError(
                "invalid_document_template_data",
                "Frozen template object keys must not contain duplicates.",
            )

    def to_python(self) -> dict[str, object]:
        return {key: _thaw(value) for key, value in self.items}


@dataclass(frozen=True, slots=True)
class FrozenTemplateArray:
    items: tuple["FrozenTemplateValue", ...]

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple) or len(self.items) > MAX_TEMPLATE_COLLECTION_ITEMS:
            raise DocumentTemplateError(
                "invalid_document_template_data",
                "Frozen template array items must be a bounded tuple.",
            )

    def to_python(self) -> list[object]:
        return [_thaw(value) for value in self.items]


FrozenTemplateScalar: TypeAlias = None | bool | int | float | str
FrozenTemplateValue: TypeAlias = FrozenTemplateScalar | FrozenTemplateObject | FrozenTemplateArray


def _fail(code: str, message: str) -> None:
    raise DocumentTemplateError(code, message)


def _identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail("invalid_document_template", f"{name} must be a bounded safe identifier.")
    return value


def _safe_ref(name: str, value: object) -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        _fail("invalid_document_template", f"{name} must be a bounded safe reference.")
    return value


def _schema(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("invalid_document_template_schema", "schema_version must be an integer.")
    if value != DOCUMENT_TEMPLATE_SCHEMA_VERSION:
        _fail("unsupported_document_template_schema", "Document template schema version is unsupported.")
    return value


def _timestamp(name: str, value: object) -> str:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        _fail("invalid_document_template", f"{name} must be an RFC3339 UTC timestamp.")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail("invalid_document_template", f"{name} must be an RFC3339 UTC timestamp.")
    return value


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _key_is_forbidden(value: str) -> bool:
    normalized = _normalize_key(value)
    if normalized in _FORBIDDEN_KEYS:
        return True
    parts = frozenset(part for part in normalized.split("_") if part)
    return bool(parts & _SENSITIVE_KEY_PARTS)


def _freeze(value: object, *, depth: int = 0, counter: list[int] | None = None) -> FrozenTemplateValue:
    counter = [0] if counter is None else counter
    counter[0] += 1
    if counter[0] > MAX_TEMPLATE_NODES or depth > MAX_TEMPLATE_NESTING_DEPTH:
        _fail("template_data_budget_exceeded", "Template data exceeds bounded complexity.")

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > MAX_TEMPLATE_INTEGER_ABS:
            _fail("template_data_budget_exceeded", "Template integer is outside the bounded range.")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("invalid_document_template_data", "Template numbers must be finite.")
        return value
    if isinstance(value, str):
        if len(value) > MAX_TEMPLATE_STRING_CHARS:
            _fail("template_data_budget_exceeded", "Template string is too large.")
        return value
    if isinstance(value, Mapping):
        if len(value) > MAX_TEMPLATE_COLLECTION_ITEMS:
            _fail("template_data_budget_exceeded", "Template object has too many entries.")
        keys = tuple(value.keys())
        if any(not isinstance(key, str) or not _KEY.fullmatch(key) for key in keys):
            _fail("invalid_document_template_data", "Template keys must be bounded safe identifiers.")
        items: list[tuple[str, FrozenTemplateValue]] = []
        for key in sorted(keys):
            if _key_is_forbidden(key):
                _fail(
                    "template_authority_surface_forbidden",
                    "Template data cannot carry runtime authority, approval state, routing identity or template identity.",
                )
            items.append((key, _freeze(value[key], depth=depth + 1, counter=counter)))
        return FrozenTemplateObject(tuple(items))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_TEMPLATE_COLLECTION_ITEMS:
            _fail("template_data_budget_exceeded", "Template array has too many entries.")
        return FrozenTemplateArray(tuple(_freeze(item, depth=depth + 1, counter=counter) for item in value))
    _fail("invalid_document_template_data", "Template data must be JSON-compatible.")
    raise AssertionError("unreachable")


def _thaw(value: FrozenTemplateValue) -> object:
    if isinstance(value, FrozenTemplateObject):
        return value.to_python()
    if isinstance(value, FrozenTemplateArray):
        return value.to_python()
    return value


def _encoded(value: FrozenTemplateValue | dict[str, object]) -> bytes:
    source = _thaw(value) if isinstance(value, (FrozenTemplateObject, FrozenTemplateArray)) else value
    return json.dumps(source, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _object(name: str, value: object) -> FrozenTemplateObject:
    source = value.to_python() if isinstance(value, FrozenTemplateObject) else value
    if not isinstance(source, Mapping):
        _fail("invalid_document_template_data", f"{name} must be an object.")
    frozen = _freeze(source)
    if not isinstance(frozen, FrozenTemplateObject):
        _fail("invalid_document_template_data", f"{name} must be an object.")
    if len(_encoded(frozen)) > MAX_TEMPLATE_DATA_BYTES:
        _fail("template_data_budget_exceeded", f"{name} is too large.")
    return frozen


def _array(name: str, value: object) -> FrozenTemplateArray:
    source = value.to_python() if isinstance(value, FrozenTemplateArray) else value
    if not isinstance(source, Sequence) or isinstance(source, (str, bytes, bytearray)):
        _fail("invalid_document_template_data", f"{name} must be an array.")
    frozen = _freeze(source)
    if not isinstance(frozen, FrozenTemplateArray):
        _fail("invalid_document_template_data", f"{name} must be an array.")
    if len(_encoded(frozen)) > MAX_TEMPLATE_DATA_BYTES:
        _fail("template_data_budget_exceeded", f"{name} is too large.")
    return frozen


def _warnings(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        _fail("invalid_document_template", "warnings must be a sequence.")
    try:
        result = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        _fail("invalid_document_template", "warnings must be a sequence.")
    if len(result) > MAX_TEMPLATE_WARNINGS:
        _fail("template_data_budget_exceeded", "warnings are oversized.")
    if any(not isinstance(item, str) or not _WARNING.fullmatch(item) for item in result):
        _fail("invalid_document_template", "warnings must be bounded machine identifiers.")
    if len(result) != len(set(result)):
        _fail("invalid_document_template", "warnings must not contain duplicates.")
    return result


@dataclass(frozen=True, slots=True)
class DocumentTemplateSourceProvenance:
    source_type: str
    source_ref: str
    media_type: str | None = None
    content_sha256: str | None = None
    trace_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", _identifier("source_type", self.source_type))
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            _fail("invalid_document_template", "source_ref must be non-empty.")
        source_ref = self.source_ref.strip()
        if len(source_ref) > MAX_TEMPLATE_SOURCE_REF_CHARS:
            _fail("template_data_budget_exceeded", "source_ref is too large.")
        object.__setattr__(self, "source_ref", source_ref)
        if self.media_type is not None and (not isinstance(self.media_type, str) or not _MEDIA.fullmatch(self.media_type)):
            _fail("invalid_document_template", "media_type is invalid.")
        if self.content_sha256 is not None and (not isinstance(self.content_sha256, str) or not _SHA256.fullmatch(self.content_sha256)):
            _fail("invalid_document_template", "content_sha256 is invalid.")
        if self.trace_id is not None:
            object.__setattr__(self, "trace_id", _identifier("trace_id", self.trace_id))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "source_type": self.source_type,
            "media_type": self.media_type,
            "content_sha256": self.content_sha256,
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class DocumentTemplateCandidate:
    candidate_id: str
    schema_version: int
    template_kind: str
    name: str
    source_provenance: DocumentTemplateSourceProvenance
    structure_profile: FrozenTemplateObject | Mapping[str, object]
    style_profile: FrozenTemplateObject | Mapping[str, object]
    fixed_content: FrozenTemplateObject | Mapping[str, object]
    variable_slots: FrozenTemplateArray | Sequence[object]
    renderer_contract_ref: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _identifier("candidate_id", self.candidate_id))
        object.__setattr__(self, "schema_version", _schema(self.schema_version))
        object.__setattr__(self, "template_kind", _identifier("template_kind", self.template_kind))
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name.strip()) > MAX_TEMPLATE_NAME_CHARS:
            _fail("invalid_document_template", "name is invalid or oversized.")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.source_provenance, DocumentTemplateSourceProvenance):
            _fail("invalid_document_template", "source_provenance is invalid.")
        values = (
            _object("structure_profile", self.structure_profile),
            _object("style_profile", self.style_profile),
            _object("fixed_content", self.fixed_content),
            _array("variable_slots", self.variable_slots),
        )
        if sum(len(_encoded(value)) for value in values) > MAX_TEMPLATE_DATA_BYTES:
            _fail("template_data_budget_exceeded", "Combined template data is too large.")
        for field_name, value in zip(("structure_profile", "style_profile", "fixed_content", "variable_slots"), values):
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "renderer_contract_ref", _safe_ref("renderer_contract_ref", self.renderer_contract_ref))
        object.__setattr__(self, "warnings", _warnings(self.warnings))

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "type": "document_template_candidate",
            "candidate_id": self.candidate_id,
            "schema_version": self.schema_version,
            "template_kind": self.template_kind,
            "name": self.name,
            "source_provenance": self.source_provenance.to_public_dict(),
            "structure_profile": self.structure_profile.to_python(),
            "style_profile": self.style_profile.to_python(),
            "fixed_content": self.fixed_content.to_python(),
            "variable_slots": self.variable_slots.to_python(),
            "renderer_contract_ref": self.renderer_contract_ref,
            "warnings": list(self.warnings),
            "fingerprint": self.fingerprint,
            "approved": False,
        }


@dataclass(frozen=True, slots=True)
class DocumentTemplateApproval:
    candidate_id: str
    candidate_fingerprint: str
    approved_by_ref: str
    approved_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _identifier("candidate_id", self.candidate_id))
        if not isinstance(self.candidate_fingerprint, str) or not _SHA256.fullmatch(self.candidate_fingerprint):
            _fail("invalid_document_template", "candidate_fingerprint is invalid.")
        object.__setattr__(self, "approved_by_ref", _safe_ref("approved_by_ref", self.approved_by_ref))
        object.__setattr__(self, "approved_at", _timestamp("approved_at", self.approved_at))


@dataclass(frozen=True, slots=True)
class DocumentTemplateProfile:
    template_id: str
    schema_version: int
    template_kind: str
    name: str
    source_provenance: DocumentTemplateSourceProvenance
    structure_profile: FrozenTemplateObject | Mapping[str, object]
    style_profile: FrozenTemplateObject | Mapping[str, object]
    fixed_content: FrozenTemplateObject | Mapping[str, object]
    variable_slots: FrozenTemplateArray | Sequence[object]
    renderer_contract_ref: str
    fingerprint: str
    approval: DocumentTemplateApproval
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "template_id", _identifier("template_id", self.template_id))
        shadow = DocumentTemplateCandidate(
            candidate_id=self.approval.candidate_id if isinstance(self.approval, DocumentTemplateApproval) else "invalid",
            schema_version=self.schema_version,
            template_kind=self.template_kind,
            name=self.name,
            source_provenance=self.source_provenance,
            structure_profile=self.structure_profile,
            style_profile=self.style_profile,
            fixed_content=self.fixed_content,
            variable_slots=self.variable_slots,
            renderer_contract_ref=self.renderer_contract_ref,
        )
        for field_name in ("schema_version", "template_kind", "name", "source_provenance", "structure_profile", "style_profile", "fixed_content", "variable_slots", "renderer_contract_ref"):
            object.__setattr__(self, field_name, getattr(shadow, field_name))
        if not isinstance(self.approval, DocumentTemplateApproval):
            _fail("document_template_approval_required", "Explicit approval evidence is required.")
        object.__setattr__(self, "created_at", _timestamp("created_at", self.created_at))
        object.__setattr__(self, "updated_at", _timestamp("updated_at", self.updated_at))
        if datetime.fromisoformat(self.updated_at[:-1] + "+00:00") < datetime.fromisoformat(self.created_at[:-1] + "+00:00"):
            _fail("invalid_document_template", "updated_at must not precede created_at.")
        expected = _fingerprint(self)
        if not isinstance(self.fingerprint, str) or self.fingerprint != expected:
            _fail("document_template_fingerprint_mismatch", "fingerprint does not match canonical content.")
        if self.approval.candidate_fingerprint != self.fingerprint:
            _fail("document_template_approval_mismatch", "approval does not match canonical content.")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "type": "document_template_profile",
            "template_id": self.template_id,
            "schema_version": self.schema_version,
            "template_kind": self.template_kind,
            "name": self.name,
            "source_provenance": self.source_provenance.to_public_dict(),
            "structure_profile": self.structure_profile.to_python(),
            "style_profile": self.style_profile.to_python(),
            "fixed_content": self.fixed_content.to_python(),
            "variable_slots": self.variable_slots.to_python(),
            "renderer_contract_ref": self.renderer_contract_ref,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "approved": True,
        }


def _fingerprint(template: DocumentTemplateCandidate | DocumentTemplateProfile) -> str:
    payload = {
        "schema_version": template.schema_version,
        "template_kind": template.template_kind,
        "structure_profile": template.structure_profile.to_python(),
        "style_profile": template.style_profile.to_python(),
        "fixed_content": template.fixed_content.to_python(),
        "variable_slots": template.variable_slots.to_python(),
        "renderer_contract_ref": template.renderer_contract_ref,
    }
    return hashlib.sha256(_encoded(payload)).hexdigest()


def approve_document_template_candidate(
    candidate: DocumentTemplateCandidate,
    *,
    template_id: str,
    approved_by_ref: str,
    approved_at: str,
) -> DocumentTemplateProfile:
    if not isinstance(candidate, DocumentTemplateCandidate):
        _fail("invalid_document_template", "candidate must be DocumentTemplateCandidate.")
    approval = DocumentTemplateApproval(
        candidate_id=candidate.candidate_id,
        candidate_fingerprint=candidate.fingerprint,
        approved_by_ref=approved_by_ref,
        approved_at=approved_at,
    )
    return DocumentTemplateProfile(
        template_id=template_id,
        schema_version=candidate.schema_version,
        template_kind=candidate.template_kind,
        name=candidate.name,
        source_provenance=candidate.source_provenance,
        structure_profile=candidate.structure_profile,
        style_profile=candidate.style_profile,
        fixed_content=candidate.fixed_content,
        variable_slots=candidate.variable_slots,
        renderer_contract_ref=candidate.renderer_contract_ref,
        fingerprint=candidate.fingerprint,
        approval=approval,
        created_at=approved_at,
        updated_at=approved_at,
    )


__all__ = [
    "DOCUMENT_TEMPLATE_SCHEMA_VERSION",
    "MAX_TEMPLATE_COLLECTION_ITEMS",
    "MAX_TEMPLATE_DATA_BYTES",
    "MAX_TEMPLATE_NESTING_DEPTH",
    "MAX_TEMPLATE_NODES",
    "MAX_TEMPLATE_STRING_CHARS",
    "MAX_TEMPLATE_INTEGER_ABS",
    "DocumentTemplateApproval",
    "DocumentTemplateCandidate",
    "DocumentTemplateError",
    "DocumentTemplateProfile",
    "DocumentTemplateSourceProvenance",
    "FrozenTemplateArray",
    "FrozenTemplateObject",
    "approve_document_template_candidate",
]
