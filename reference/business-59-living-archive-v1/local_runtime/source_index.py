"""Deterministic, local-only source import and exact search for B59.

This is deliberately smaller than the future Living Archive runtime. It accepts
bytes supplied by a caller, keeps the original bytes in an in-memory store, and
builds only deterministic text/page/section indexes. It does not perform model
execution, OCR, semantic search, persistence, authentication, or network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import mimetypes
import re
from typing import Callable, Iterable


MODEL_EXECUTION = "OFF"
NETWORK_CALLS = 0
SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf"}
SUPPORTED_MIME_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".pdf": "application/pdf",
}


class ImportStatus(StrEnum):
    READY = "READY"
    FAILED = "FAILED"


class ImportFailure(ValueError):
    """A visible, bounded import failure that never discards the source."""


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    source_version: int
    checksum: str
    filename: str
    extension: str
    mime_type: str
    byte_size: int
    imported_at: str
    extraction_status: ImportStatus
    error_code: str | None
    page_or_section_count: int


@dataclass(frozen=True, slots=True)
class SourceAnchor:
    source_id: str
    source_version: int
    page_or_section: str
    text: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    source_id: str
    source_version: int
    page_or_section: str
    title: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    record: SourceRecord
    duplicate: bool
    error_code: str | None


@dataclass(frozen=True, slots=True)
class _ExtractedDocument:
    anchors: tuple[tuple[str, str], ...]


@dataclass(slots=True)
class _StoredVersion:
    record: SourceRecord
    original: bytes
    anchors: tuple[SourceAnchor, ...]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat()


def _normalize_filename(filename: str) -> tuple[str, str]:
    if not isinstance(filename, str) or not filename.strip():
        raise ImportFailure("INVALID_FILENAME")
    name = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]
    if name in {"", ".", ".."} or "\x00" in name:
        raise ImportFailure("INVALID_FILENAME")
    extension = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return name, extension


def _mime_for(filename: str, extension: str, supplied: str | None) -> str:
    if supplied is None:
        return SUPPORTED_MIME_TYPES[extension]
    if not isinstance(supplied, str) or supplied.strip() != SUPPORTED_MIME_TYPES[extension]:
        raise ImportFailure("MIME_TYPE_MISMATCH")
    return supplied.strip()


def _decode_pdf_literal(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            result.append(char)
            index += 1
            continue
        index += 1
        if index >= len(value):
            raise ImportFailure("MALFORMED_PDF")
        escaped = value[index]
        replacements = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
        result.append(replacements.get(escaped, escaped))
        index += 1
    return "".join(result)


def _extract_pdf(data: bytes) -> _ExtractedDocument:
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data:
        raise ImportFailure("MALFORMED_PDF")
    text = data.decode("latin-1", errors="strict")
    page_parts = re.split(r"%%PAGE:(\d+)", text)
    if len(page_parts) == 1:
        page_parts = ["", "1", text]
    anchors: list[tuple[str, str]] = []
    for index in range(1, len(page_parts), 2):
        page_number = page_parts[index]
        page_body = page_parts[index + 1]
        strings = re.findall(r"\(((?:\\.|[^\\)])*)\)\s*Tj", page_body)
        extracted = " ".join(_decode_pdf_literal(item) for item in strings).strip()
        if extracted:
            anchors.append((f"page:{page_number}", extracted))
    if not anchors:
        raise ImportFailure("MALFORMED_PDF")
    return _ExtractedDocument(tuple(anchors))


def _extract_text(data: bytes, extension: str) -> _ExtractedDocument:
    if extension == ".pdf":
        return _extract_pdf(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ImportFailure("INVALID_UTF8") from exc
    if not text.strip():
        raise ImportFailure("EMPTY_TEXT")

    if extension in {".md", ".markdown"}:
        headings = list(re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", text))
        if headings:
            anchors: list[tuple[str, str]] = []
            for number, heading in enumerate(headings, start=1):
                start = heading.start()
                end = headings[number].start() if number < len(headings) else len(text)
                body = text[start:end].strip()
                anchors.append((f"section:{number}", body))
            return _ExtractedDocument(tuple(anchors))

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        raise ImportFailure("EMPTY_TEXT")
    return _ExtractedDocument(
        tuple((f"section:{number}", paragraph) for number, paragraph in enumerate(paragraphs, start=1))
    )


class LocalSourceIndex:
    """In-memory source registry and exact text index for synthetic local data."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _default_clock
        self._versions: dict[tuple[str, int], _StoredVersion] = {}
        self._latest_by_source: dict[str, int] = {}
        self._by_checksum: dict[str, tuple[str, int]] = {}
        self._records_by_id: dict[str, list[SourceRecord]] = {}

    def import_bytes(
        self,
        filename: str,
        data: bytes,
        *,
        mime_type: str | None = None,
    ) -> ImportResult:
        """Import bytes without reading paths, opening sockets, or calling models."""
        if not isinstance(data, bytes):
            raise ImportFailure("BYTES_REQUIRED")
        name, extension = _normalize_filename(filename)
        supported = extension in SUPPORTED_EXTENSIONS
        normalized_mime = (
            _mime_for(name, extension, mime_type)
            if supported
            else (mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream")
        )
        checksum = hashlib.sha256(data).hexdigest()
        duplicate_key = self._by_checksum.get(checksum)
        if duplicate_key is not None:
            existing = self._versions[duplicate_key].record
            return ImportResult(existing, duplicate=True, error_code=existing.error_code)

        source_id = "src_" + hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:24]
        version = self._latest_by_source.get(source_id, 0) + 1
        imported_at = _iso_timestamp(self._clock())
        try:
            if not supported:
                raise ImportFailure("UNSUPPORTED_FORMAT")
            extracted = _extract_text(data, extension)
            status = ImportStatus.READY
            error_code = None
            anchors = tuple(
                SourceAnchor(source_id, version, location, text)
                for location, text in extracted.anchors
            )
        except ImportFailure as exc:
            status = ImportStatus.FAILED
            error_code = str(exc)
            anchors = ()

        record = SourceRecord(
            source_id=source_id,
            source_version=version,
            checksum=checksum,
            filename=name,
            extension=extension,
            mime_type=normalized_mime,
            byte_size=len(data),
            imported_at=imported_at,
            extraction_status=status,
            error_code=error_code,
            page_or_section_count=len(anchors),
        )
        stored = _StoredVersion(record=record, original=data, anchors=anchors)
        self._versions[(source_id, version)] = stored
        self._latest_by_source[source_id] = version
        self._records_by_id.setdefault(source_id, []).append(record)
        self._by_checksum[checksum] = (source_id, version)
        return ImportResult(record, duplicate=False, error_code=error_code)

    def get_record(self, source_id: str, source_version: int | None = None) -> SourceRecord:
        version = source_version or self._latest_by_source[source_id]
        return self._versions[(source_id, version)].record

    def get_original(self, source_id: str, source_version: int | None = None) -> bytes:
        version = source_version or self._latest_by_source[source_id]
        return self._versions[(source_id, version)].original

    def resolve(self, source_id: str, source_version: int, page_or_section: str) -> SourceAnchor:
        stored = self._versions[(source_id, source_version)]
        for anchor in stored.anchors:
            if anchor.page_or_section == page_or_section:
                return anchor
        raise KeyError((source_id, source_version, page_or_section))

    def records(self, source_id: str | None = None) -> tuple[SourceRecord, ...]:
        if source_id is None:
            return tuple(item.record for item in self._versions.values())
        return tuple(self._records_by_id.get(source_id, ()))

    def search(self, query: str) -> tuple[SearchResult, ...]:
        if not isinstance(query, str) or not query.strip():
            return ()
        needle = query.casefold()
        results: list[SearchResult] = []
        for stored in self._versions.values():
            if stored.record.extraction_status is not ImportStatus.READY:
                continue
            for anchor in stored.anchors:
                title_match = needle in stored.record.filename.casefold()
                text_match = needle in anchor.text.casefold()
                if title_match or text_match:
                    excerpt = anchor.text.strip().replace("\n", " ")
                    results.append(
                        SearchResult(
                            source_id=anchor.source_id,
                            source_version=anchor.source_version,
                            page_or_section=anchor.page_or_section,
                            title=stored.record.filename,
                            excerpt=excerpt,
                        )
                    )
        return tuple(
            sorted(
                results,
                key=lambda item: (item.source_id, item.source_version, item.page_or_section),
            )
        )


def synthetic_fixture_pdf() -> bytes:
    """Return a tiny extractable-text PDF fixture without external dependencies."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Count 2 >>endobj\n"
        b"3 0 obj<< /Length 88 >>stream\n"
        b"%%PAGE:1\nBT (Living Archive report introduction) Tj ET\n"
        b"%%PAGE:2\nBT (Exact source mapping remains local) Tj ET\n"
        b"endstream endobj\n%%EOF\n"
    )


__all__ = [
    "ImportFailure",
    "ImportResult",
    "ImportStatus",
    "LocalSourceIndex",
    "MODEL_EXECUTION",
    "NETWORK_CALLS",
    "SearchResult",
    "SourceAnchor",
    "SourceRecord",
    "synthetic_fixture_pdf",
]
