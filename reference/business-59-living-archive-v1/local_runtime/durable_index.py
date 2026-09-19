"""Durable local runtime foundation for Business 59 (Living Archive).

This module is additive: it extends the in-memory ``LocalSourceIndex`` slice in
``source_index.py`` into a store that survives process restart, while leaving
that module byte-identical and its API unchanged. Extraction, filename
normalisation, MIME resolution and the timestamp format are reused from the
slice so behaviour cannot drift between the prototype and the durable runtime.

Layer separation (see ``PRODUCT_CONTRACT.md``):

* **original source** — immutable ``sources`` row + byte-for-byte blob written
  once per ``(source_id, source_version)``. Re-indexing never rewrites it and
  database triggers reject ``UPDATE``/``DELETE`` on the table.
* **derived / index data** — ``derived_artifacts`` + ``derived_anchors`` rows.
  Regenerable, and deletable via :meth:`DurableSourceIndex.delete_derived`
  without touching the other two layers.
* **user records** — ``user_titles``, ``user_tags``, ``user_annotations``,
  ``user_bookmarks``, ``user_reading_positions``. Anchored by source-relative
  identity (``source_id``, ``source_version``, ``page_or_section`` + span), never
  by a rendered coordinate, so they resolve again after a re-index or restart.

Guarantees kept deliberately narrow and truthful:

* exact substring search only — no embeddings, vectors, FTS ranking or model;
* ``MODEL_EXECUTION = "OFF"``, zero network calls: the runtime imports no
  network client and performs no I/O beyond the local store root;
* a stage this slice does not implement (``PREVIEW_RENDERED``) is persisted as
  ``DEFERRED`` and produces no output, never a fabricated pass.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import Path
import sqlite3

from .lifecycle import (
    ArtifactStatus,
    ArtifactType,
    IMPORT_IMPLEMENTATION_VERSION,
    ImportRun,
    ImportStage,
    PREVIEW_DEFERRED_DETAIL,
    RunKind,
    RunStatus,
    StageEvent,
    StageRecorder,
    StageStatus,
    load_run,
    persist_run,
    runs_for,
    terminal_stage_for,
    terminal_stage_status_for,
    terminal_status_for,
    unique_run_id,
)
from .persistence import (
    DEFAULT_DB_FILENAME,
    ORIGINALS_DIRNAME,
    ArchiveError,
    OriginalIntegrityError,
    StorageFailure,
    apply_migrations,
    blob_relative_path,
    error_code,
    get_connection,
    is_retryable,
    read_blob,
    remove_blob,
    transaction,
    validate_source_filename,
    write_blob,
)
# ``_default_clock``/``_iso_timestamp``/``_extract_text``/``_mime_for`` are the
# existing slice's deterministic helpers; reusing them keeps the durable runtime
# and the prototype in lockstep. ``source_index.py`` itself is not modified.
from .source_index import (
    MODEL_EXECUTION,
    NETWORK_CALLS,
    ImportFailure,
    ImportStatus,
    SearchResult,
    SourceAnchor,
    SourceRecord,
    SUPPORTED_EXTENSIONS,
    _default_clock,
    _extract_text,
    _iso_timestamp,
    _mime_for,
)


# Safe, non-secret reason codes for resolutions that did not resolve.
DERIVED_INDEX_MISSING = "DERIVED_INDEX_MISSING"
DERIVED_ANCHOR_MISSING = "DERIVED_ANCHOR_MISSING"
ANCHOR_TEXT_DRIFT = "ANCHOR_TEXT_DRIFT"

DEFAULT_IMPLEMENTATION_VERSION = IMPORT_IMPLEMENTATION_VERSION


@dataclass(frozen=True, slots=True)
class Annotation:
    """A user note anchored to a source-relative span."""

    annotation_id: str
    source_id: str
    source_version: int
    page_or_section: str
    anchor_start: int
    anchor_end: int
    anchor_text: str
    note: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Bookmark:
    bookmark_id: str
    source_id: str
    source_version: int
    page_or_section: str
    anchor_start: int
    anchor_end: int
    label: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ReadingPosition:
    source_id: str
    source_version: int
    page_or_section: str
    char_offset: int
    updated_at: str


@dataclass(frozen=True, slots=True)
class AnchorResolution:
    """Result of resolving an annotation back to its source-relative anchor.

    ``resolved`` is ``True`` only when the stored span still matches the
    currently derived text for that anchor. When the derived index is missing
    or the extracted text drifted, the *user record is still intact* and the
    reason code says exactly what could not be resolved.
    """

    annotation: Annotation
    resolved: bool
    reason: str | None
    resolved_text: str | None


@dataclass(frozen=True, slots=True)
class DurableImportResult:
    """Outcome of one durable import.

    ``record`` is ``None`` only when the original could not be stored at all
    (terminal ``FAILED``); ``run`` is ``None`` only for a deterministic
    duplicate, where nothing was written and nothing was regenerated.
    """

    record: SourceRecord | None
    duplicate: bool
    error_code: str | None
    run: ImportRun | None


def _resolve_mime_type(
    name: str,
    extension: str,
    supplied: str | None,
    *,
    supported: bool,
) -> str:
    if supported:
        return _mime_for(name, extension, supplied)
    if supplied is not None:
        if not isinstance(supplied, str) or not supplied.strip():
            raise ImportFailure("MIME_TYPE_MISMATCH")
        return supplied.strip()
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _source_id_for(name: str) -> str:
    """Deterministic source id, identical to the in-memory slice's derivation."""
    return "src_" + hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:24]


def _hash_id(prefix: str, *parts: str) -> str:
    payload = "|".join(parts)
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _artifact_id(
    source_id: str, source_version: int, artifact_type: ArtifactType, implementation_version: str
) -> str:
    return _hash_id(
        "art_",
        source_id,
        str(source_version),
        artifact_type.value,
        implementation_version,
    )


def _anchor_id(artifact_id: str, ordinal: int, page_or_section: str, text_checksum: str) -> str:
    return _hash_id("anc_", artifact_id, str(ordinal), page_or_section, text_checksum)


def _validate_span(text: str, anchor_start: int, anchor_end: int) -> tuple[int, int]:
    if not isinstance(anchor_start, int) or not isinstance(anchor_end, int):
        raise ImportFailure("ANCHOR_RANGE_INVALID")
    if isinstance(anchor_start, bool) or isinstance(anchor_end, bool):
        raise ImportFailure("ANCHOR_RANGE_INVALID")
    if anchor_start < 0 or anchor_end <= anchor_start or anchor_end > len(text):
        raise ImportFailure("ANCHOR_RANGE_INVALID")
    return anchor_start, anchor_end


class DurableSourceIndex:
    """SQLite-backed, restart-safe source archive with exact search.

    ``root`` is a local directory that owns everything: the SQLite database
    (``living_archive.sqlite3``) and the immutable original blobs
    (``originals/<source_id>/v<version>.<ext>``). Opening a second instance on
    the same root is the restart path exercised by the tests.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        clock=None,
        implementation_version: str = DEFAULT_IMPLEMENTATION_VERSION,
    ) -> None:
        self._root = Path(root).expanduser()
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / DEFAULT_DB_FILENAME
        self._connection = get_connection(self._db_path)
        apply_migrations(self._connection)
        self._clock = clock or _default_clock
        self._implementation_version = implementation_version
        self._closed = False

    # ------------------------------------------------------------------ #
    # Layout / lifecycle
    # ------------------------------------------------------------------ #
    @property
    def root(self) -> Path:
        return self._root

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def original_directory(self) -> Path:
        return self._root / ORIGINALS_DIRNAME

    @property
    def implementation_version(self) -> str:
        return self._implementation_version

    @property
    def connection(self) -> sqlite3.Connection:
        """Raw connection, exposed for integrity inspection.

        The original layer is protected by database triggers, so inspection
        cannot accidentally rewrite a source row.
        """
        self._require_open()
        return self._connection

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> "DurableSourceIndex":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("DurableSourceIndex is closed")

    # ------------------------------------------------------------------ #
    # Import
    # ------------------------------------------------------------------ #
    def import_bytes(
        self,
        filename: str,
        data: bytes,
        *,
        mime_type: str | None = None,
    ) -> DurableImportResult:
        """Import bytes into the durable store.

        Unsafe filenames, non-bytes payloads and MIME mismatches fail closed
        *before* anything is persisted, so a rejected import cannot consume a
        source version or leave a half-written run behind. An extraction
        failure is not a rejected import: the original is stored first and the
        run finishes as ``PARTIAL`` with a safe error code.
        """
        self._require_open()
        if not isinstance(data, bytes):
            raise ImportFailure("BYTES_REQUIRED")
        name, extension = validate_source_filename(filename)
        supported = extension in SUPPORTED_EXTENSIONS
        normalized_mime = _resolve_mime_type(name, extension, mime_type, supported=supported)
        checksum = hashlib.sha256(data).hexdigest()

        duplicate = self._record_by_checksum(checksum)
        if duplicate is not None:
            # Deterministic duplicate detection: nothing is written, nothing is
            # regenerated, so no import run is recorded.
            return DurableImportResult(
                record=duplicate, duplicate=True, error_code=duplicate.error_code, run=None
            )

        started_at = _iso_timestamp(self._clock())
        source_id = _source_id_for(name)
        source_version = self._next_version(source_id)
        implementation_version = self._implementation_version
        recorder = StageRecorder(clock=self._clock)
        recorder.record(
            ImportStage.RECEIVED,
            StageStatus.PASSED,
            started_at=started_at,
            detail="bytes accepted for local import; no network or model execution",
        )
        recorder.record(
            ImportStage.VALIDATED,
            StageStatus.PASSED,
            started_at=recorder.now(),
            detail=(
                "supported extraction format and MIME metadata validated"
                if supported
                else f"unsupported extension {extension}: original is stored for "
                "preservation, extraction is not attempted"
            ),
        )

        original_reference = blob_relative_path(source_id, source_version, extension)
        stored_started = recorder.now()
        created_blob = False
        try:
            created_blob = write_blob(self._root, original_reference, data)
        except ArchiveError as exc:
            return self._store_failure_result(
                recorder=recorder,
                run_kind=RunKind.IMPORT,
                source_id=source_id,
                source_version=source_version,
                implementation_version=implementation_version,
                started_at=started_at,
                error=exc,
            )
        recorder.record(
            ImportStage.STORED,
            StageStatus.PASSED,
            started_at=stored_started,
            outputs=("ORIGINAL_SOURCE",),
            detail=(
                "immutable original written once"
                if created_blob
                else "identical original already present; not rewritten"
            ),
        )

        extraction_status, extraction_error, anchors = self._extract(
            recorder, source_id, source_version, data, extension, supported=supported
        )
        recorder.record(
            ImportStage.PREVIEW_RENDERED,
            StageStatus.DEFERRED,
            started_at=recorder.now(),
            detail=PREVIEW_DEFERRED_DETAIL,
        )
        indexed_at = recorder.now()
        if anchors:
            recorder.record(
                ImportStage.INDEXED,
                StageStatus.PASSED,
                started_at=indexed_at,
                outputs=("EXACT_ANCHOR_INDEX",),
                detail=f"{len(anchors)} source-relative anchors persisted",
            )
        else:
            recorder.record(
                ImportStage.INDEXED,
                StageStatus.FAILED,
                started_at=indexed_at,
                detail="no derived index produced; exact search has nothing for this source",
            )
        terminal = terminal_status_for(extraction_status is ImportStatus.READY, True)
        recorder.record(
            terminal_stage_for(terminal),
            terminal_stage_status_for(terminal),
            started_at=recorder.now(),
            detail=(
                "original stored and derived index available"
                if terminal is RunStatus.READY
                else "original stored and readable; derived index incomplete"
            ),
        )

        try:
            with transaction(self._connection):
                self._insert_source(
                    source_id=source_id,
                    source_version=source_version,
                    checksum=checksum,
                    name=name,
                    extension=extension,
                    mime_type=normalized_mime,
                    byte_size=len(data),
                    imported_at=started_at,
                    original_reference=original_reference,
                )
                self._insert_derived(
                    source_id=source_id,
                    source_version=source_version,
                    implementation_version=implementation_version,
                    created_at=started_at,
                    anchors=anchors,
                    extraction_status=extraction_status,
                    extraction_error=extraction_error,
                )
                run = self._persist_run(
                    recorder,
                    run_kind=RunKind.IMPORT,
                    source_id=source_id,
                    source_version=source_version,
                    implementation_version=implementation_version,
                    status=terminal,
                    error_code=extraction_error,
                    retryable=False,
                    original_readable=True,
                    started_at=started_at,
                )
        except sqlite3.Error as exc:
            if created_blob:
                remove_blob(self._root, original_reference)
            self._best_effort_failed_run(
                recorder,
                run_kind=RunKind.IMPORT,
                source_id=source_id,
                source_version=source_version,
                implementation_version=implementation_version,
                started_at=started_at,
                code="STORAGE_METADATA_FAILED",
                original_readable=False,
            )
            raise StorageFailure("STORAGE_METADATA_FAILED", retryable=True) from exc

        return DurableImportResult(
            record=self._read_record(source_id, source_version),
            duplicate=False,
            error_code=extraction_error,
            run=run,
        )

    def _extract(
        self,
        recorder: StageRecorder,
        source_id: str,
        source_version: int,
        data: bytes,
        extension: str,
        *,
        supported: bool,
    ) -> tuple[ImportStatus, str | None, tuple[SourceAnchor, ...]]:
        """Run the ``TEXT_EXTRACTED`` stage, returning anchors or a safe code."""
        started_at = recorder.now()
        if not supported:
            code = "UNSUPPORTED_FORMAT"
            recorder.record(
                ImportStage.TEXT_EXTRACTED,
                StageStatus.FAILED,
                started_at=started_at,
                detail=f"{code}: no extractor for this extension in this slice",
            )
            return ImportStatus.FAILED, code, ()
        try:
            extracted = _extract_text(data, extension)
        except ImportFailure as exc:
            code = error_code(exc)
            recorder.record(
                ImportStage.TEXT_EXTRACTED,
                StageStatus.FAILED,
                started_at=started_at,
                detail=f"{code}: extraction failed; original remains stored and readable",
            )
            return ImportStatus.FAILED, code, ()
        anchors = tuple(
            SourceAnchor(source_id, source_version, location, text)
            for location, text in extracted.anchors
        )
        recorder.record(
            ImportStage.TEXT_EXTRACTED,
            StageStatus.PASSED,
            started_at=started_at,
            outputs=("EXTRACTED_TEXT",),
            detail=f"{len(anchors)} source-relative anchors extracted",
        )
        return ImportStatus.READY, None, anchors

    # ------------------------------------------------------------------ #
    # Re-index
    # ------------------------------------------------------------------ #
    def reindex(
        self,
        source_id: str,
        source_version: int | None = None,
        *,
        implementation_version: str | None = None,
    ) -> ImportRun:
        """Regenerate derived data for a stored version, leaving user state alone.

        The original blob is read (and checksum-verified) but never rewritten,
        and every ``user_*`` row is untouched: titles, tags, annotations,
        bookmarks and reading position survive by construction. When a
        re-index fails to extract, the previously stored derived index is kept
        rather than destroyed, and the failed attempt is recorded as a run.
        """
        self._require_open()
        version = self._resolve_version(source_id, source_version)
        source_row = self._source_row(source_id, version)
        implementation = implementation_version or self._implementation_version
        started_at = _iso_timestamp(self._clock())
        recorder = StageRecorder(clock=self._clock)
        recorder.record(
            ImportStage.RECEIVED,
            StageStatus.PASSED,
            started_at=started_at,
            detail="re-index requested for an already stored source version",
        )

        try:
            data = read_blob(self._root, source_row["original_reference"])
        except ArchiveError as exc:
            return self._reindex_failure(
                recorder,
                source_id,
                version,
                implementation,
                started_at,
                error=exc,
                original_readable=False,
            )
        if hashlib.sha256(data).hexdigest() != source_row["checksum"]:
            return self._reindex_failure(
                recorder,
                source_id,
                version,
                implementation,
                started_at,
                error=OriginalIntegrityError("ORIGINAL_INTEGRITY_MISMATCH"),
                original_readable=False,
            )
        recorder.record(
            ImportStage.VALIDATED,
            StageStatus.PASSED,
            started_at=recorder.now(),
            detail="stored original re-read and checksum verified",
        )
        recorder.record(
            ImportStage.STORED,
            StageStatus.PASSED,
            started_at=recorder.now(),
            detail="original source reused unchanged; not rewritten",
        )

        extension = source_row["extension"]
        supported = extension in SUPPORTED_EXTENSIONS
        extraction_status, extraction_error, anchors = self._extract(
            recorder, source_id, version, data, extension, supported=supported
        )
        recorder.record(
            ImportStage.PREVIEW_RENDERED,
            StageStatus.DEFERRED,
            started_at=recorder.now(),
            detail=PREVIEW_DEFERRED_DETAIL,
        )
        indexed_at = recorder.now()
        if anchors:
            recorder.record(
                ImportStage.INDEXED,
                StageStatus.PASSED,
                started_at=indexed_at,
                outputs=("EXACT_ANCHOR_INDEX",),
                detail=f"{len(anchors)} source-relative anchors regenerated",
            )
        else:
            recorder.record(
                ImportStage.INDEXED,
                StageStatus.FAILED,
                started_at=indexed_at,
                detail="re-index produced no anchors; previous derived index retained",
            )
        terminal = terminal_status_for(extraction_status is ImportStatus.READY, True)
        recorder.record(
            terminal_stage_for(terminal),
            terminal_stage_status_for(terminal),
            started_at=recorder.now(),
            detail=(
                "derived data regenerated; user records left untouched"
                if terminal is RunStatus.READY
                else "derived data not regenerated; user records left untouched"
            ),
        )

        with transaction(self._connection):
            if anchors:
                self._delete_derived_rows(source_id, version)
                self._insert_derived(
                    source_id=source_id,
                    source_version=version,
                    implementation_version=implementation,
                    created_at=started_at,
                    anchors=anchors,
                    extraction_status=extraction_status,
                    extraction_error=extraction_error,
                )
            return self._persist_run(
                recorder,
                run_kind=RunKind.REINDEX,
                source_id=source_id,
                source_version=version,
                implementation_version=implementation,
                status=terminal,
                error_code=extraction_error,
                retryable=False,
                original_readable=True,
                started_at=started_at,
            )

    def _reindex_failure(
        self,
        recorder: StageRecorder,
        source_id: str,
        source_version: int,
        implementation_version: str,
        started_at: str,
        *,
        error: ArchiveError,
        original_readable: bool,
    ) -> ImportRun:
        code = error_code(error)
        if recorder.events and recorder.events[-1].stage == ImportStage.RECEIVED.value:
            recorder.record(
                ImportStage.VALIDATED,
                StageStatus.FAILED,
                started_at=recorder.now(),
                detail=f"{code}: re-index aborted before regeneration",
            )
        recorder.record(
            ImportStage.FAILED,
            StageStatus.FAILED,
            started_at=recorder.now(),
            detail=f"{code}: previous derived index and user records left untouched",
        )
        with transaction(self._connection):
            return self._persist_run(
            recorder,
            run_kind=RunKind.REINDEX,
            source_id=source_id,
            source_version=source_version,
            implementation_version=implementation_version,
            status=RunStatus.FAILED,
            error_code=code,
            retryable=is_retryable(error),
            original_readable=original_readable,
            started_at=started_at,
        )

    # ------------------------------------------------------------------ #
    # Derived-layer management
    # ------------------------------------------------------------------ #
    def delete_derived(self, source_id: str | None = None, source_version: int | None = None) -> int:
        """Delete derived artifacts (anchors cascade); returns artifacts removed.

        Only the derived layer is touched: originals, and every user record
        (title, tags, annotations, bookmarks, reading position), are preserved.
        """
        self._require_open()
        with transaction(self._connection):
            return self._delete_derived_rows(source_id, source_version)

    def _delete_derived_rows(self, source_id: str | None, source_version: int | None) -> int:
        clauses: list[str] = []
        parameters: list[object] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            parameters.append(source_id)
        if source_version is not None:
            clauses.append("source_version = ?")
            parameters.append(int(source_version))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = self._connection.execute(
            f"DELETE FROM derived_artifacts {where}", parameters
        )
        return cursor.rowcount

    def _insert_derived(
        self,
        *,
        source_id: str,
        source_version: int,
        implementation_version: str,
        created_at: str,
        anchors: tuple[SourceAnchor, ...],
        extraction_status: ImportStatus,
        extraction_error: str | None,
    ) -> None:
        """Insert the derived artifacts/anchors produced by one extraction."""
        extraction_artifact = _artifact_id(
            source_id, source_version, ArtifactType.TEXT_EXTRACTION, implementation_version
        )
        self._connection.execute(
            """
            INSERT INTO derived_artifacts (
                artifact_id, source_id, source_version, artifact_type,
                implementation_version, status, error_code, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                extraction_artifact,
                source_id,
                source_version,
                ArtifactType.TEXT_EXTRACTION.value,
                implementation_version,
                ArtifactStatus.READY.value
                if extraction_status is ImportStatus.READY
                else ArtifactStatus.FAILED.value,
                extraction_error,
                "deterministic local text extraction",
                created_at,
            ),
        )
        preview_artifact = _artifact_id(
            source_id, source_version, ArtifactType.PREVIEW_RENDER, implementation_version
        )
        self._connection.execute(
            """
            INSERT INTO derived_artifacts (
                artifact_id, source_id, source_version, artifact_type,
                implementation_version, status, error_code, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preview_artifact,
                source_id,
                source_version,
                ArtifactType.PREVIEW_RENDER.value,
                implementation_version,
                ArtifactStatus.DEFERRED.value,
                None,
                PREVIEW_DEFERRED_DETAIL,
                created_at,
            ),
        )
        if not anchors:
            return
        index_artifact = _artifact_id(
            source_id, source_version, ArtifactType.EXACT_ANCHOR_INDEX, implementation_version
        )
        self._connection.execute(
            """
            INSERT INTO derived_artifacts (
                artifact_id, source_id, source_version, artifact_type,
                implementation_version, status, error_code, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                index_artifact,
                source_id,
                source_version,
                ArtifactType.EXACT_ANCHOR_INDEX.value,
                implementation_version,
                ArtifactStatus.READY.value,
                None,
                f"{len(anchors)} exact anchors",
                created_at,
            ),
        )
        for ordinal, anchor in enumerate(anchors, start=1):
            text_checksum = hashlib.sha256(anchor.text.encode("utf-8")).hexdigest()
            self._connection.execute(
                """
                INSERT INTO derived_anchors (
                    anchor_id, artifact_id, source_id, source_version, ordinal,
                    page_or_section, text, text_checksum
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _anchor_id(index_artifact, ordinal, anchor.page_or_section, text_checksum),
                    index_artifact,
                    source_id,
                    source_version,
                    ordinal,
                    anchor.page_or_section,
                    anchor.text,
                    text_checksum,
                ),
            )

    # ------------------------------------------------------------------ #
    # Reads (parity with the in-memory slice)
    # ------------------------------------------------------------------ #
    def get_record(self, source_id: str, source_version: int | None = None) -> SourceRecord:
        self._require_open()
        return self._read_record(source_id, self._resolve_version(source_id, source_version))

    def get_original(self, source_id: str, source_version: int | None = None) -> bytes:
        """Return the immutable original bytes, verified against the checksum."""
        self._require_open()
        row = self._source_row(source_id, self._resolve_version(source_id, source_version))
        data = read_blob(self._root, row["original_reference"])
        if hashlib.sha256(data).hexdigest() != row["checksum"]:
            raise OriginalIntegrityError("ORIGINAL_INTEGRITY_MISMATCH")
        return data

    def verify_original(self, source_id: str, source_version: int | None = None) -> bool:
        """True when the stored blob still matches the recorded checksum."""
        try:
            self.get_original(source_id, source_version)
        except (ArchiveError, KeyError):
            return False
        return True

    def original_reference(self, source_id: str, source_version: int | None = None) -> str:
        """Store-relative location of the original bytes (stable local reference)."""
        self._require_open()
        row = self._source_row(source_id, self._resolve_version(source_id, source_version))
        return row["original_reference"]

    def latest_version(self, source_id: str) -> int:
        self._require_open()
        return self._resolve_version(source_id, None)

    def resolve(self, source_id: str, source_version: int, page_or_section: str) -> SourceAnchor:
        """Resolve a source-relative anchor to its currently derived text."""
        self._require_open()
        row = self._connection.execute(
            """
            SELECT text FROM derived_anchors
            WHERE source_id = ? AND source_version = ? AND page_or_section = ?
            """,
            (source_id, int(source_version), page_or_section),
        ).fetchone()
        if row is None:
            raise KeyError((source_id, int(source_version), page_or_section))
        return SourceAnchor(source_id, int(source_version), page_or_section, row["text"])

    def records(self, source_id: str | None = None) -> tuple[SourceRecord, ...]:
        self._require_open()
        if source_id is None:
            rows = self._connection.execute(
                "SELECT source_id, source_version FROM sources ORDER BY source_id, source_version"
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT source_id, source_version FROM sources
                WHERE source_id = ? ORDER BY source_version
                """,
                (source_id,),
            ).fetchall()
        return tuple(self._read_record(row["source_id"], row["source_version"]) for row in rows)

    def search(self, query: str) -> tuple[SearchResult, ...]:
        """Persistent exact substring search over filename/title, text and anchor.

        Deliberately exact (case-insensitive substring) and local: no
        embeddings, no vector store, no ranking model, no FTS dependency. The
        match decision is made in Python against the persisted rows using the
        same ``casefold`` semantics as the in-memory slice.
        """
        self._require_open()
        if not isinstance(query, str) or not query.strip():
            return ()
        needle = query.casefold()
        rows = self._connection.execute(
            """
            SELECT a.source_id AS source_id,
                   a.source_version AS source_version,
                   a.page_or_section AS page_or_section,
                   a.text AS text,
                   s.filename AS filename,
                   t.title AS user_title
            FROM derived_anchors AS a
            JOIN derived_artifacts AS art
              ON art.artifact_id = a.artifact_id AND art.status = 'READY'
            JOIN sources AS s
              ON s.source_id = a.source_id AND s.source_version = a.source_version
            LEFT JOIN user_titles AS t
              ON t.source_id = a.source_id AND t.source_version = a.source_version
            ORDER BY a.source_id, a.source_version, a.page_or_section
            """
        ).fetchall()
        results: list[SearchResult] = []
        for row in rows:
            title = row["user_title"] or row["filename"]
            if (
                needle in title.casefold()
                or needle in row["text"].casefold()
                or needle in row["page_or_section"].casefold()
            ):
                results.append(
                    SearchResult(
                        source_id=row["source_id"],
                        source_version=row["source_version"],
                        page_or_section=row["page_or_section"],
                        title=title,
                        excerpt=row["text"].strip().replace("\n", " "),
                    )
                )
        return tuple(
            sorted(
                results,
                key=lambda item: (item.source_id, item.source_version, item.page_or_section),
            )
        )

    # ------------------------------------------------------------------ #
    # Run history
    # ------------------------------------------------------------------ #
    def run(self, run_id: str) -> ImportRun:
        self._require_open()
        return load_run(self._connection, run_id)

    def runs(
        self, source_id: str | None = None, source_version: int | None = None
    ) -> tuple[ImportRun, ...]:
        self._require_open()
        return runs_for(self._connection, source_id, source_version)

    # ------------------------------------------------------------------ #
    # User records (layer 3): never written by the import/re-index paths
    # ------------------------------------------------------------------ #
    def set_title(self, source_id: str, title: str, *, source_version: int | None = None) -> str:
        self._require_open()
        version = self._resolve_version(source_id, source_version)
        self._source_row(source_id, version)
        if not isinstance(title, str) or not title.strip():
            raise ImportFailure("INVALID_TITLE")
        clean = title.strip()
        if any(ord(character) < 32 for character in clean):
            raise ImportFailure("INVALID_TITLE")
        self._connection.execute(
            """
            INSERT INTO user_titles (source_id, source_version, title, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_id, source_version)
            DO UPDATE SET title = excluded.title, updated_at = excluded.updated_at
            """,
            (source_id, version, clean, _iso_timestamp(self._clock())),
        )
        return clean

    def get_title(self, source_id: str, *, source_version: int | None = None) -> str:
        """User title correction when present, otherwise the imported filename."""
        self._require_open()
        version = self._resolve_version(source_id, source_version)
        row = self._source_row(source_id, version)
        override = self._connection.execute(
            "SELECT title FROM user_titles WHERE source_id = ? AND source_version = ?",
            (source_id, version),
        ).fetchone()
        return override["title"] if override is not None else row["filename"]

    def add_tag(self, source_id: str, tag: str, *, source_version: int | None = None) -> str:
        self._require_open()
        version = self._resolve_version(source_id, source_version)
        self._source_row(source_id, version)
        if not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 64:
            raise ImportFailure("INVALID_TAG")
        clean = tag.strip()
        self._connection.execute(
            """
            INSERT OR IGNORE INTO user_tags (source_id, source_version, tag, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (source_id, version, clean, _iso_timestamp(self._clock())),
        )
        return clean

    def remove_tag(self, source_id: str, tag: str, *, source_version: int | None = None) -> bool:
        self._require_open()
        version = self._resolve_version(source_id, source_version)
        cursor = self._connection.execute(
            "DELETE FROM user_tags WHERE source_id = ? AND source_version = ? AND tag = ?",
            (source_id, version, tag),
        )
        return bool(cursor.rowcount)

    def list_tags(self, source_id: str, *, source_version: int | None = None) -> tuple[str, ...]:
        self._require_open()
        version = self._resolve_version(source_id, source_version)
        rows = self._connection.execute(
            """
            SELECT tag FROM user_tags WHERE source_id = ? AND source_version = ?
            ORDER BY tag
            """,
            (source_id, version),
        ).fetchall()
        return tuple(row["tag"] for row in rows)

    def add_annotation(
        self,
        source_id: str,
        page_or_section: str,
        *,
        anchor_start: int,
        anchor_end: int,
        note: str = "",
        source_version: int | None = None,
        annotation_id: str | None = None,
    ) -> Annotation:
        """Anchor a user note to a source-relative span.

        The span is validated against the *source-relative* extracted text for
        ``page_or_section``; no rendered coordinate is ever stored. Identification
        is deterministic, so re-adding the same annotation is idempotent.
        """
        self._require_open()
        version = self._resolve_version(source_id, source_version)
        anchor = self.resolve(source_id, version, page_or_section)
        start, end = _validate_span(anchor.text, anchor_start, anchor_end)
        if not isinstance(note, str):
            raise ImportFailure("INVALID_NOTE")
        created_at = _iso_timestamp(self._clock())
        identifier = annotation_id or _hash_id(
            "ann_",
            source_id,
            str(version),
            page_or_section,
            str(start),
            str(end),
            created_at,
            note,
        )
        self._connection.execute(
            """
            INSERT OR IGNORE INTO user_annotations (
                annotation_id, source_id, source_version, page_or_section,
                anchor_start, anchor_end, anchor_text, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                source_id,
                version,
                page_or_section,
                start,
                end,
                anchor.text[start:end],
                note,
                created_at,
            ),
        )
        return self._annotation_row(identifier)

    def list_annotations(
        self, source_id: str | None = None, *, source_version: int | None = None
    ) -> tuple[Annotation, ...]:
        self._require_open()
        clauses: list[str] = []
        parameters: list[object] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            parameters.append(source_id)
        if source_version is not None:
            clauses.append("source_version = ?")
            parameters.append(int(source_version))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"""
            SELECT * FROM user_annotations {where}
            ORDER BY source_id, source_version, page_or_section, anchor_start, annotation_id
            """,
            parameters,
        ).fetchall()
        return tuple(self._annotation_from_row(row) for row in rows)

    def remove_annotation(self, source_id: str, annotation_id: str) -> bool:
        self._require_open()
        cursor = self._connection.execute(
            "DELETE FROM user_annotations WHERE annotation_id = ? AND source_id = ?",
            (annotation_id, source_id),
        )
        return bool(cursor.rowcount)

    def resolve_annotation(
        self, source_id: str, annotation_id: str
    ) -> AnchorResolution:
        """Resolve an annotation back to its original source-relative anchor."""
        self._require_open()
        row = self._connection.execute(
            "SELECT * FROM user_annotations WHERE annotation_id = ? AND source_id = ?",
            (annotation_id, source_id),
        ).fetchone()
        if row is None:
            raise KeyError((source_id, annotation_id))
        annotation = self._annotation_from_row(row)
        try:
            anchor = self.resolve(
                annotation.source_id, annotation.source_version, annotation.page_or_section
            )
        except KeyError:
            return AnchorResolution(
                annotation=annotation,
                resolved=False,
                reason=DERIVED_ANCHOR_MISSING,
                resolved_text=None,
            )
        span = anchor.text[annotation.anchor_start : annotation.anchor_end]
        if span != annotation.anchor_text:
            return AnchorResolution(
                annotation=annotation,
                resolved=False,
                reason=ANCHOR_TEXT_DRIFT,
                resolved_text=span,
            )
        return AnchorResolution(
            annotation=annotation, resolved=True, reason=None, resolved_text=span
        )

    def add_bookmark(
        self,
        source_id: str,
        page_or_section: str,
        *,
        anchor_start: int = 0,
        anchor_end: int | None = None,
        label: str = "",
        source_version: int | None = None,
        bookmark_id: str | None = None,
    ) -> Bookmark:
        self._require_open()
        version = self._resolve_version(source_id, source_version)
        anchor = self.resolve(source_id, version, page_or_section)
        end = len(anchor.text) if anchor_end is None else anchor_end
        start, end = _validate_span(anchor.text, anchor_start, end)
        if not isinstance(label, str):
            raise ImportFailure("INVALID_LABEL")
        created_at = _iso_timestamp(self._clock())
        identifier = bookmark_id or _hash_id(
            "bmk_",
            source_id,
            str(version),
            page_or_section,
            str(start),
            str(end),
            created_at,
            label,
        )
        self._connection.execute(
            """
            INSERT OR IGNORE INTO user_bookmarks (
                bookmark_id, source_id, source_version, page_or_section,
                anchor_start, anchor_end, label, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (identifier, source_id, version, page_or_section, start, end, label, created_at),
        )
        return self._bookmark_row(identifier)

    def list_bookmarks(
        self, source_id: str | None = None, *, source_version: int | None = None
    ) -> tuple[Bookmark, ...]:
        self._require_open()
        clauses: list[str] = []
        parameters: list[object] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            parameters.append(source_id)
        if source_version is not None:
            clauses.append("source_version = ?")
            parameters.append(int(source_version))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"""
            SELECT * FROM user_bookmarks {where}
            ORDER BY source_id, source_version, page_or_section, anchor_start, bookmark_id
            """,
            parameters,
        ).fetchall()
        return tuple(self._bookmark_from_row(row) for row in rows)

    def remove_bookmark(self, source_id: str, bookmark_id: str) -> bool:
        self._require_open()
        cursor = self._connection.execute(
            "DELETE FROM user_bookmarks WHERE bookmark_id = ? AND source_id = ?",
            (bookmark_id, source_id),
        )
        return bool(cursor.rowcount)

    def set_reading_position(
        self,
        source_id: str,
        page_or_section: str,
        char_offset: int = 0,
        *,
        source_version: int | None = None,
    ) -> ReadingPosition:
        self._require_open()
        version = self._resolve_version(source_id, source_version)
        anchor = self.resolve(source_id, version, page_or_section)
        if not isinstance(char_offset, int) or isinstance(char_offset, bool):
            raise ImportFailure("ANCHOR_RANGE_INVALID")
        if char_offset < 0 or char_offset > len(anchor.text):
            raise ImportFailure("ANCHOR_RANGE_INVALID")
        updated_at = _iso_timestamp(self._clock())
        self._connection.execute(
            """
            INSERT INTO user_reading_positions (
                source_id, source_version, page_or_section, char_offset, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_id, source_version)
            DO UPDATE SET page_or_section = excluded.page_or_section,
                          char_offset = excluded.char_offset,
                          updated_at = excluded.updated_at
            """,
            (source_id, version, page_or_section, char_offset, updated_at),
        )
        return ReadingPosition(source_id, version, page_or_section, char_offset, updated_at)

    def get_reading_position(
        self, source_id: str, *, source_version: int | None = None
    ) -> ReadingPosition | None:
        self._require_open()
        version = self._resolve_version(source_id, source_version)
        row = self._connection.execute(
            """
            SELECT * FROM user_reading_positions
            WHERE source_id = ? AND source_version = ?
            """,
            (source_id, version),
        ).fetchone()
        if row is None:
            return None
        return ReadingPosition(
            source_id=row["source_id"],
            source_version=row["source_version"],
            page_or_section=row["page_or_section"],
            char_offset=row["char_offset"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _insert_source(
        self,
        *,
        source_id: str,
        source_version: int,
        checksum: str,
        name: str,
        extension: str,
        mime_type: str,
        byte_size: int,
        imported_at: str,
        original_reference: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO sources (
                source_id, source_version, checksum, filename, extension,
                mime_type, byte_size, imported_at, original_reference
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                source_version,
                checksum,
                name,
                extension,
                mime_type,
                byte_size,
                imported_at,
                original_reference,
            ),
        )

    def _source_row(self, source_id: str, source_version: int) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM sources WHERE source_id = ? AND source_version = ?",
            (source_id, int(source_version)),
        ).fetchone()
        if row is None:
            raise KeyError((source_id, int(source_version)))
        return row

    def _resolve_version(self, source_id: str, source_version: int | None) -> int:
        if source_version is not None:
            return int(source_version)
        row = self._connection.execute(
            "SELECT MAX(source_version) AS version FROM sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is None or row["version"] is None:
            raise KeyError(source_id)
        return int(row["version"])

    def _next_version(self, source_id: str) -> int:
        row = self._connection.execute(
            "SELECT MAX(source_version) AS version FROM sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        return int(row["version"] or 0) + 1

    def _record_by_checksum(self, checksum: str) -> SourceRecord | None:
        row = self._connection.execute(
            """
            SELECT source_id, source_version FROM sources
            WHERE checksum = ?
            ORDER BY source_id, source_version
            LIMIT 1
            """,
            (checksum,),
        ).fetchone()
        if row is None:
            return None
        return self._read_record(row["source_id"], row["source_version"])

    def _read_record(self, source_id: str, source_version: int) -> SourceRecord:
        """Reconstruct the slice's ``SourceRecord`` from the durable layers.

        Original metadata comes from the immutable ``sources`` row; the
        extraction status and anchor count come from the derived layer, so they
        honestly report *currently available* derived data. When derived data
        has been deleted the record reports ``DERIVED_INDEX_MISSING`` rather
        than claiming a stale success.
        """
        row = self._source_row(source_id, source_version)
        artifact = self._connection.execute(
            """
            SELECT status, error_code FROM derived_artifacts
            WHERE source_id = ? AND source_version = ?
              AND artifact_type = 'TEXT_EXTRACTION'
            ORDER BY created_at DESC, artifact_id DESC
            LIMIT 1
            """,
            (source_id, int(source_version)),
        ).fetchone()
        if artifact is None:
            extraction_status = ImportStatus.FAILED
            extraction_error: str | None = DERIVED_INDEX_MISSING
        elif artifact["status"] == ArtifactStatus.READY.value:
            extraction_status = ImportStatus.READY
            extraction_error = None
        else:
            extraction_status = ImportStatus.FAILED
            extraction_error = artifact["error_code"]
        count_row = self._connection.execute(
            """
            SELECT COUNT(*) AS anchors FROM derived_anchors
            WHERE source_id = ? AND source_version = ?
            """,
            (source_id, int(source_version)),
        ).fetchone()
        return SourceRecord(
            source_id=row["source_id"],
            source_version=row["source_version"],
            checksum=row["checksum"],
            filename=row["filename"],
            extension=row["extension"],
            mime_type=row["mime_type"],
            byte_size=row["byte_size"],
            imported_at=row["imported_at"],
            extraction_status=extraction_status,
            error_code=extraction_error,
            page_or_section_count=int(count_row["anchors"]),
        )

    def _persist_run(
        self,
        recorder: StageRecorder,
        *,
        run_kind: RunKind,
        source_id: str,
        source_version: int,
        implementation_version: str,
        status: RunStatus,
        error_code: str | None,
        retryable: bool,
        original_readable: bool,
        started_at: str,
    ) -> ImportRun:
        # Unique, deterministic run id; an identical re-run never overwrites an
        # existing audit record.
        base = _hash_id(
            "run_",
            run_kind.value,
            source_id,
            str(source_version),
            implementation_version,
            started_at,
        )
        run_id = unique_run_id(self._connection, base)
        persist_run(
            self._connection,
            run_id=run_id,
            run_kind=run_kind,
            source_id=source_id,
            source_version=source_version,
            implementation_version=implementation_version,
            status=status,
            error_code=error_code,
            retryable=retryable,
            original_readable=original_readable,
            outputs=recorder.produced_outputs,
            started_at=started_at,
            ended_at=recorder.now(),
            stages=recorder.events,
        )
        return load_run(self._connection, run_id)

    def _store_failure_result(
        self,
        *,
        recorder: StageRecorder,
        run_kind: RunKind,
        source_id: str,
        source_version: int,
        implementation_version: str,
        started_at: str,
        error: ArchiveError,
    ) -> DurableImportResult:
        """Terminal ``FAILED``: the original could not be stored, so it is not readable."""
        code = error_code(error)
        recorder.record(
            ImportStage.STORED,
            StageStatus.FAILED,
            started_at=recorder.now(),
            detail=f"{code}: original bytes were not persisted",
        )
        recorder.record(
            ImportStage.FAILED,
            StageStatus.FAILED,
            started_at=recorder.now(),
            detail=f"{code}: import abandoned; no source version was created",
        )
        with transaction(self._connection):
            run = self._persist_run(
                recorder,
                run_kind=run_kind,
                source_id=source_id,
                source_version=source_version,
                implementation_version=implementation_version,
                status=RunStatus.FAILED,
                error_code=code,
                retryable=is_retryable(error),
                original_readable=False,
                started_at=started_at,
            )
        return DurableImportResult(record=None, duplicate=False, error_code=code, run=run)

    def _best_effort_failed_run(
        self,
        recorder: StageRecorder,
        *,
        run_kind: RunKind,
        source_id: str,
        source_version: int,
        implementation_version: str,
        started_at: str,
        code: str,
        original_readable: bool,
    ) -> None:
        """Persist an audit row for a failure whose cause was the database itself.

        This can itself fail; that is not hidden — the caller still raises the
        original ``StorageFailure`` so the import is reported as failed.
        """
        try:
            with transaction(self._connection):
                self._persist_run(
                    recorder,
                    run_kind=run_kind,
                    source_id=source_id,
                    source_version=source_version,
                    implementation_version=implementation_version,
                    status=RunStatus.FAILED,
                    error_code=code,
                    retryable=True,
                    original_readable=original_readable,
                    started_at=started_at,
                )
        except (sqlite3.Error, RuntimeError):
            return

    def _annotation_from_row(self, row: sqlite3.Row) -> Annotation:
        return Annotation(
            annotation_id=row["annotation_id"],
            source_id=row["source_id"],
            source_version=row["source_version"],
            page_or_section=row["page_or_section"],
            anchor_start=row["anchor_start"],
            anchor_end=row["anchor_end"],
            anchor_text=row["anchor_text"],
            note=row["note"],
            created_at=row["created_at"],
        )

    def _annotation_row(self, annotation_id: str) -> Annotation:
        row = self._connection.execute(
            "SELECT * FROM user_annotations WHERE annotation_id = ?", (annotation_id,)
        ).fetchone()
        if row is None:  # pragma: no cover - defensive
            raise KeyError(annotation_id)
        return self._annotation_from_row(row)

    def _bookmark_from_row(self, row: sqlite3.Row) -> Bookmark:
        return Bookmark(
            bookmark_id=row["bookmark_id"],
            source_id=row["source_id"],
            source_version=row["source_version"],
            page_or_section=row["page_or_section"],
            anchor_start=row["anchor_start"],
            anchor_end=row["anchor_end"],
            label=row["label"],
            created_at=row["created_at"],
        )

    def _bookmark_row(self, bookmark_id: str) -> Bookmark:
        row = self._connection.execute(
            "SELECT * FROM user_bookmarks WHERE bookmark_id = ?", (bookmark_id,)
        ).fetchone()
        if row is None:  # pragma: no cover - defensive
            raise KeyError(bookmark_id)
        return self._bookmark_from_row(row)


__all__ = [
    "ANCHOR_TEXT_DRIFT",
    "Annotation",
    "AnchorResolution",
    "Bookmark",
    "DEFAULT_IMPLEMENTATION_VERSION",
    "DERIVED_ANCHOR_MISSING",
    "DERIVED_INDEX_MISSING",
    "DurableImportResult",
    "DurableSourceIndex",
    "ImportRun",
    "ImportStage",
    "MODEL_EXECUTION",
    "NETWORK_CALLS",
    "ReadingPosition",
    "RunKind",
    "RunStatus",
    "StageEvent",
    "StageStatus",
]
