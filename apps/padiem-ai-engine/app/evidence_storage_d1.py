"""Durable D1-backed evidence storage port for Engine E5B-S4b (#1750).

This is the durable counterpart of ``InMemoryEvidenceStoragePort``: it retains
the full ``EvidenceStorageProjection`` behind the engine-minted evidence id in
a trusted D1-like binding, mirroring the ``app/continuation_d1.py`` adapter
pattern (constructor takes the binding, async SQL via the binding, fail-closed
when the binding is missing).

Retention semantics match the in-memory port exactly: ``store`` rejects a
duplicate evidence id with ``ValueError`` and ``retrieve`` raises ``KeyError``
for an unknown id. Document bodies live only inside the serialized record
columns: reprs, diagnostics and error messages never render plaintext body,
internal ``att_*`` references or storage locators.

Source-only in S4b: nothing in the composition root or worker code imports
this module yet; production activation is a later, explicit gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import inspect
import json
from typing import Any

from padiem_ai_core.document_normalization import NormalizedDocument
from padiem_ai_core.document_semantics import (
    DocumentLocator,
    DocumentSegment,
    ExtractionStatus,
    LocatorKind,
    LocatorPrecision,
)

from app.document_evidence_projection import (
    MAX_EVIDENCE_LOCATOR_CHARS,
    EvidenceStorageProjection,
)
from app.trusted_document_resolver import require_document_reference

_TABLE_NAME = "padiem_engine_evidence"
MAX_EVIDENCE_ID_CHARS = 64
MIN_EVIDENCE_ID_CHARS = 16
MAX_EVIDENCE_RECORD_CHARS = 2_000_000

_INVALID_RECORD = "evidence storage returned an invalid record"


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _locator_to_json(locator: DocumentLocator) -> dict[str, str]:
    if not isinstance(locator, DocumentLocator):
        raise ValueError("evidence document locator is invalid")
    return {"kind": locator.kind.value, "value": locator.value, "precision": locator.precision.value}


def _locator_from_json(raw: Any) -> DocumentLocator:
    if not isinstance(raw, Mapping):
        raise ValueError("evidence document locator is invalid")
    return DocumentLocator(
        kind=LocatorKind(raw["kind"]),
        value=raw["value"],
        precision=LocatorPrecision(raw["precision"]),
    )


def _document_to_json(document: NormalizedDocument) -> str:
    segments = []
    for segment in document.segments:
        segments.append(
            {
                "text": segment.text,
                "order": segment.order,
                "locator": _locator_to_json(segment.locator) if segment.locator is not None else None,
            }
        )
    return json.dumps(
        {
            "name": document.name,
            "media_type": document.media_type,
            "text": document.text,
            "byte_size": document.byte_size,
            "source_kind": document.source_kind,
            "status": document.status.value,
            "segments": segments,
            "warnings": list(document.warnings),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _document_from_json(value: Any) -> NormalizedDocument:
    data = json.loads(str(value))
    if not isinstance(data, Mapping):
        raise ValueError("evidence document record is invalid")
    raw_segments = data["segments"]
    if not isinstance(raw_segments, list):
        raise ValueError("evidence document record is invalid")
    segments: list[DocumentSegment] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, Mapping):
            raise ValueError("evidence document record is invalid")
        raw_locator = raw_segment.get("locator")
        segments.append(
            DocumentSegment(
                text=raw_segment["text"],
                order=raw_segment["order"],
                locator=_locator_from_json(raw_locator) if raw_locator is not None else None,
            )
        )
    raw_warnings = data.get("warnings", [])
    if not isinstance(raw_warnings, list) or not all(isinstance(w, str) for w in raw_warnings):
        raise ValueError("evidence document record is invalid")
    return NormalizedDocument(
        name=data["name"],
        media_type=data["media_type"],
        text=data["text"],
        byte_size=data["byte_size"],
        source_kind=data["source_kind"],
        status=ExtractionStatus(data["status"]),
        segments=tuple(segments),
        warnings=tuple(raw_warnings),
    )


class CloudflareD1EvidenceStoragePort:
    """Durable evidence retention backed by a trusted D1-like binding."""

    def __init__(self, binding: Any) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise ValueError("evidence storage binding must provide prepare(sql)")
        self._binding = binding

    def __repr__(self) -> str:
        return "CloudflareD1EvidenceStoragePort(configured)"

    async def _first(self, sql: str, *params: Any) -> Mapping[str, Any] | None:
        row = await _maybe_await(self._binding.prepare(sql).bind(*params).first())
        return dict(row) if isinstance(row, Mapping) else None

    async def _run(self, sql: str, *params: Any) -> Any:
        return await _maybe_await(self._binding.prepare(sql).bind(*params).run())

    @staticmethod
    def _projection(row: Mapping[str, Any]) -> EvidenceStorageProjection:
        try:
            retention = json.loads(str(row["retention_json"]))
            if not isinstance(retention, Mapping):
                raise ValueError("evidence retention record is invalid")
            att_ref = require_document_reference(retention["att_ref"])
            storage_locator = retention["storage_locator"]
            if (
                not isinstance(storage_locator, str)
                or not storage_locator
                or len(storage_locator) > MAX_EVIDENCE_LOCATOR_CHARS
            ):
                raise ValueError("evidence storage locator is invalid")
            return EvidenceStorageProjection(
                evidence_id=str(row["evidence_id"]),
                att_ref=att_ref,
                normalized_document=_document_from_json(row["document_json"]),
                document_locator=_locator_from_json(retention["document_locator"]),
                storage_locator=storage_locator,
                created_at=_parse_time(retention["created_at"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ValueError(_INVALID_RECORD) from None

    async def store(self, projection: EvidenceStorageProjection) -> str:
        """Retain one evidence projection; reject duplicate ids fail-closed."""

        if not isinstance(projection, EvidenceStorageProjection):
            raise ValueError("evidence storage accepts EvidenceStorageProjection only")
        evidence_id = projection.evidence_id
        if (
            not isinstance(evidence_id, str)
            or len(evidence_id) < MIN_EVIDENCE_ID_CHARS
            or len(evidence_id) > MAX_EVIDENCE_ID_CHARS
        ):
            raise ValueError("evidence id must be a bounded server token")
        if not isinstance(projection.normalized_document.text, str) or not projection.normalized_document.text:
            raise ValueError("evidence document payload must be non-empty")
        document_json = _document_to_json(projection.normalized_document)
        retention_json = json.dumps(
            {
                "att_ref": projection.att_ref,
                "storage_locator": projection.storage_locator,
                "document_locator": _locator_to_json(projection.document_locator),
                "created_at": projection.created_at.isoformat(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(document_json) > MAX_EVIDENCE_RECORD_CHARS or len(retention_json) > MAX_EVIDENCE_RECORD_CHARS:
            raise ValueError("evidence record exceeds the durable storage bound")
        existing = await self._first(
            f"SELECT evidence_id FROM {_TABLE_NAME} WHERE evidence_id=? LIMIT 1",
            evidence_id,
        )
        if existing is not None:
            raise ValueError("evidence id already exists in this store")
        await self._run(
            f"INSERT INTO {_TABLE_NAME} (evidence_id,document_json,retention_json,created_at) "
            "VALUES (?,?,?,?)",
            evidence_id,
            document_json,
            retention_json,
            projection.created_at.isoformat(),
        )
        return evidence_id

    async def retrieve(self, evidence_id: str) -> EvidenceStorageProjection:
        """Return the retained projection; unknown ids raise KeyError."""

        if not isinstance(evidence_id, str) or not evidence_id:
            raise KeyError("evidence id is unknown")
        row = await self._first(
            f"SELECT evidence_id,document_json,retention_json,created_at FROM {_TABLE_NAME} "
            "WHERE evidence_id=? LIMIT 1",
            evidence_id,
        )
        if row is None:
            raise KeyError("evidence id is unknown")
        return self._projection(row)
