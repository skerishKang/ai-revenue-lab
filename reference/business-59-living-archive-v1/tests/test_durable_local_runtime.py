"""Acceptance tests for the B59 durable local runtime foundation.

Covers the additive durable slice only; ``test_local_import_index.py`` keeps
covering the original in-memory prototype unchanged.

Windows note: an open :class:`DurableSourceIndex` holds a lock on its SQLite
file, so every store opened here is registered with ``addCleanup`` and closed
before the temporary directory is removed.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_runtime import durable_index, lifecycle, persistence  # noqa: E402
from local_runtime.durable_index import (  # noqa: E402
    ANCHOR_TEXT_DRIFT,
    DERIVED_ANCHOR_MISSING,
    DERIVED_INDEX_MISSING,
    DurableSourceIndex,
)
from local_runtime.lifecycle import (  # noqa: E402
    IMPORT_IMPLEMENTATION_VERSION,
    STAGE_NAMES,
    ArtifactStatus,
    ImportStage,
    RunKind,
    RunStatus,
    StageStatus,
)
from local_runtime.persistence import StorageFailure  # noqa: E402
from local_runtime.source_index import (  # noqa: E402
    MODEL_EXECUTION,
    NETWORK_CALLS,
    ImportFailure,
    ImportStatus,
    LocalSourceIndex,
    synthetic_fixture_pdf,
)


TXT_BODY = b"First local entry.\n\nSecond local entry with anchor."
MARKDOWN_BODY = b"# First\nAlpha local note.\n\n## Second\nBeta mapping note."
SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")

RUNTIME_MODULES = (durable_index, lifecycle, persistence)
FORBIDDEN_NETWORK_ROOTS = frozenset(
    {
        "socket",
        "ssl",
        "urllib",
        "urllib2",
        "http",
        "httplib",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "nntplib",
        "telnetlib",
        "xmlrpc",
        "socketserver",
        "webbrowser",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "websocket",
    }
)


class SteppingClock:
    """Deterministic injectable clock: distinct, monotonic timestamps per call."""

    def __init__(self, start: datetime | None = None) -> None:
        self._value = start or datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self._value
        self._value = value + timedelta(seconds=1)
        return value


class DurableRuntimeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.clock = SteppingClock()

    def open_store(self, clock: object | None = None) -> DurableSourceIndex:
        store = DurableSourceIndex(self.root, clock=clock or self.clock)
        # addCleanup is LIFO: stores close before the temporary directory goes.
        self.addCleanup(store.close)
        return store

    def restart(self, store: DurableSourceIndex) -> DurableSourceIndex:
        """Close the store and reopen a *new object* on the same database path."""
        db_path = store.db_path
        store.close()
        reopened = self.open_store()
        self.assertEqual(reopened.db_path, db_path)
        self.assertIsNot(reopened, store)
        return reopened

    def anchor_ids(self, store: DurableSourceIndex, source_id: str, version: int) -> tuple[str, ...]:
        rows = store.connection.execute(
            """
            SELECT anchor_id FROM derived_anchors
            WHERE source_id = ? AND source_version = ?
            ORDER BY ordinal
            """,
            (source_id, version),
        ).fetchall()
        return tuple(row["anchor_id"] for row in rows)


class ImportAndRestartTests(DurableRuntimeTestCase):
    def test_01_txt_import_then_restart_restores_source_and_exact_search(self) -> None:
        store = self.open_store()
        result = store.import_bytes("journal.txt", TXT_BODY)
        record = result.record
        self.assertIsNotNone(record)
        self.assertEqual(record.extraction_status, ImportStatus.READY)
        self.assertEqual(record.page_or_section_count, 2)
        self.assertFalse(result.duplicate)
        self.assertEqual(result.run.status, RunStatus.READY)

        reopened = self.restart(store)

        self.assertEqual(reopened.get_record(record.source_id), record)
        self.assertEqual(reopened.get_original(record.source_id), TXT_BODY)
        self.assertTrue(reopened.verify_original(record.source_id))
        hits = reopened.search("anchor")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].page_or_section, "section:2")
        self.assertEqual(
            reopened.resolve(hits[0].source_id, hits[0].source_version, "section:2").text,
            "Second local entry with anchor.",
        )
        # filename/title search and page-or-section search also survive.
        self.assertEqual(len(reopened.search("journal")), 2)
        self.assertEqual(len(reopened.search("section:1")), 1)

    def test_02_markdown_section_anchors_survive_restart(self) -> None:
        store = self.open_store()
        result = store.import_bytes("notes.md", MARKDOWN_BODY)
        source_id = result.record.source_id
        self.assertEqual(result.record.page_or_section_count, 2)

        reopened = self.restart(store)

        hits = reopened.search("mapping")
        self.assertEqual([hit.page_or_section for hit in hits], ["section:2"])
        self.assertTrue(hits[0].excerpt.startswith("## Second"))
        self.assertEqual(
            reopened.resolve(source_id, 1, "section:1").text,
            "# First\nAlpha local note.",
        )

    def test_03_extractable_pdf_page_anchors_survive_restart(self) -> None:
        store = self.open_store()
        result = store.import_bytes("report.pdf", synthetic_fixture_pdf())
        source_id = result.record.source_id
        self.assertEqual(result.record.mime_type, "application/pdf")

        reopened = self.restart(store)

        hits = reopened.search("source mapping")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].page_or_section, "page:2")
        self.assertEqual(reopened.resolve(source_id, 1, "page:2").text, hits[0].excerpt)
        self.assertEqual(
            reopened.resolve(source_id, 1, "page:1").text,
            "Living Archive report introduction",
        )
        # The reloaded run keeps the deferred stage deferred across restart.
        reloaded = reopened.runs(source_id, 1)
        self.assertEqual(len(reloaded), 1)
        preview = reloaded[0].stage(ImportStage.PREVIEW_RENDERED)
        self.assertIsNotNone(preview)
        self.assertEqual(preview.status, StageStatus.DEFERRED)
        self.assertEqual(preview.outputs, ())
        self.assertEqual(reloaded[0].outputs, ("ORIGINAL_SOURCE", "EXTRACTED_TEXT", "EXACT_ANCHOR_INDEX"))

    def test_04_duplicate_checksum_is_detected_deterministically(self) -> None:
        store = self.open_store()
        payload = b"same synthetic source"
        first = store.import_bytes("first.txt", payload)
        duplicate = store.import_bytes("renamed.txt", payload)
        self.assertFalse(first.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.record, first.record)
        self.assertIsNone(duplicate.run)
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(len(store.runs()), 1)

        reopened = self.restart(store)

        again = reopened.import_bytes("third-name.txt", payload)
        self.assertTrue(again.duplicate)
        self.assertEqual(again.record, first.record)
        self.assertEqual(len(reopened.records()), 1)
        self.assertEqual(len(reopened.runs()), 1)

    def test_05_same_filename_changed_bytes_create_next_version(self) -> None:
        store = self.open_store()
        first = store.import_bytes("versioned.txt", b"version one")
        second = store.import_bytes("versioned.txt", b"version two")
        source_id = first.record.source_id
        self.assertEqual(second.record.source_id, source_id)
        self.assertEqual(first.record.source_version, 1)
        self.assertEqual(second.record.source_version, 2)
        self.assertEqual(store.latest_version(source_id), 2)

        first_reference = store.original_reference(source_id, 1)
        first_blob_bytes = (store.root / first_reference).read_bytes()

        self.assertEqual(store.get_original(source_id, 1), b"version one")
        self.assertEqual(store.get_original(source_id, 2), b"version two")
        self.assertEqual(store.get_original(source_id), b"version two")
        self.assertTrue(store.verify_original(source_id, 1))
        # The earlier version's bytes on disk are untouched by the new import.
        self.assertEqual((store.root / first_reference).read_bytes(), first_blob_bytes)
        self.assertEqual(store.get_record(source_id, 1).checksum, first.record.checksum)

    def test_05b_original_layer_rejects_mutation_attempts(self) -> None:
        store = self.open_store()
        result = store.import_bytes("immutable.txt", b"immutable bytes")
        source_id = result.record.source_id

        with self.assertRaises(sqlite3.IntegrityError):
            store.connection.execute(
                "UPDATE sources SET checksum = 'tampered' WHERE source_id = ?", (source_id,)
            )
        with self.assertRaises(sqlite3.IntegrityError):
            store.connection.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))

        self.assertEqual(store.get_original(source_id), b"immutable bytes")
        self.assertTrue(store.verify_original(source_id))

    def test_17_durable_record_matches_in_memory_slice_for_same_input(self) -> None:
        # Same fixed clock for both stores so the comparison is about behaviour,
        # not about how many timestamps each implementation consumed.
        fixed_clock = lambda: datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc)  # noqa: E731
        memory = LocalSourceIndex(clock=fixed_clock)
        expected = memory.import_bytes("parity.txt", TXT_BODY)
        store = self.open_store(clock=fixed_clock)
        actual = store.import_bytes("parity.txt", TXT_BODY)
        self.assertEqual(actual.record, expected.record)
        self.assertEqual(actual.duplicate, expected.duplicate)
        self.assertEqual(actual.error_code, expected.error_code)
        self.assertEqual(store.search("anchor"), memory.search("anchor"))


class FailureIsolationTests(DurableRuntimeTestCase):
    def test_06_malformed_pdf_failure_preserves_original_and_exposes_safe_code(self) -> None:
        store = self.open_store()
        original = b"not a valid pdf"
        result = store.import_bytes("broken.pdf", original)
        source_id = result.record.source_id

        self.assertEqual(result.run.status, RunStatus.PARTIAL)
        self.assertEqual(result.error_code, "MALFORMED_PDF")
        self.assertTrue(SAFE_CODE.match(result.error_code))
        self.assertEqual(result.record.extraction_status, ImportStatus.FAILED)
        self.assertEqual(result.record.error_code, "MALFORMED_PDF")
        self.assertEqual(result.record.page_or_section_count, 0)
        self.assertTrue(result.run.original_readable)
        self.assertFalse(result.run.retryable)
        self.assertEqual(result.run.failed_stages, ("TEXT_EXTRACTED", "INDEXED", "PARTIAL"))
        self.assertEqual(result.run.deferred_stages, ("PREVIEW_RENDERED",))
        self.assertEqual(result.run.produced_outputs, ("ORIGINAL_SOURCE",))
        self.assertNotIn("PREVIEW_RENDER", result.run.outputs)

        reopened = self.restart(store)

        self.assertEqual(reopened.get_original(source_id), original)
        self.assertEqual(reopened.search("valid"), ())
        self.assertEqual(reopened.runs(source_id)[0].error_code, "MALFORMED_PDF")

    def test_06b_non_utf8_text_failure_preserves_original(self) -> None:
        store = self.open_store()
        original = b"\xff\xfe not utf8"
        result = store.import_bytes("legacy.txt", original)
        self.assertEqual(result.run.status, RunStatus.PARTIAL)
        self.assertEqual(result.error_code, "INVALID_UTF8")
        self.assertEqual(store.get_original(result.record.source_id), original)
        self.assertEqual(store.search("utf8"), ())

    def test_07_unsupported_source_is_preserved_and_isolated(self) -> None:
        store = self.open_store()
        original = b"synthetic unsupported docx"
        result = store.import_bytes("archive.docx", original)
        source_id = result.record.source_id

        self.assertEqual(result.run.status, RunStatus.PARTIAL)
        self.assertEqual(result.run.error_code, "UNSUPPORTED_FORMAT")
        self.assertEqual(result.run.stage(ImportStage.VALIDATED).status, StageStatus.PASSED)
        self.assertEqual(result.run.stage(ImportStage.TEXT_EXTRACTED).status, StageStatus.FAILED)
        self.assertFalse(result.run.retryable)

        reopened = self.restart(store)

        self.assertEqual(reopened.get_original(source_id), original)
        self.assertEqual(reopened.get_record(source_id).extension, ".docx")
        self.assertEqual(reopened.search("synthetic"), ())

    def test_11_one_failing_source_does_not_damage_another(self) -> None:
        store = self.open_store()
        healthy = store.import_bytes("healthy.txt", TXT_BODY)
        healthy_id = healthy.record.source_id
        annotation = store.add_annotation(
            healthy_id,
            "section:2",
            anchor_start=0,
            anchor_end=len("Second local entry with anchor."),
            note="keep this note",
        )

        broken = store.import_bytes("broken-two.pdf", b"still not a pdf")
        self.assertEqual(broken.run.status, RunStatus.PARTIAL)

        self.assertEqual(store.get_original(healthy_id), TXT_BODY)
        self.assertEqual([hit.page_or_section for hit in store.search("anchor")], ["section:2"])
        self.assertTrue(store.resolve_annotation(healthy_id, annotation.annotation_id).resolved)
        self.assertEqual(store.list_annotations(healthy_id), (annotation,))
        self.assertEqual(store.get_record(healthy_id).extraction_status, ImportStatus.READY)

        removed = store.delete_derived(source_id=broken.record.source_id)
        self.assertEqual(removed, 2)
        self.assertEqual(len(store.search("anchor")), 1)
        self.assertTrue(store.verify_original(healthy_id))
        self.assertTrue(store.resolve_annotation(healthy_id, annotation.annotation_id).resolved)

    def test_14_unstorable_original_finishes_as_failed_run(self) -> None:
        store = self.open_store()
        failure = StorageFailure("ORIGINAL_WRITE_FAILED")
        with mock.patch.object(durable_index, "write_blob", side_effect=failure):
            result = store.import_bytes("unstorable.txt", b"cannot be stored")

        self.assertIsNone(result.record)
        self.assertEqual(result.error_code, "ORIGINAL_WRITE_FAILED")
        self.assertEqual(result.run.status, RunStatus.FAILED)
        self.assertEqual(result.run.error_code, "ORIGINAL_WRITE_FAILED")
        self.assertTrue(result.run.retryable)
        self.assertFalse(result.run.original_readable)
        self.assertEqual(result.run.stage(ImportStage.STORED).status, StageStatus.FAILED)
        self.assertEqual(result.run.stage(ImportStage.FAILED).status, StageStatus.FAILED)
        # Nothing was stored, and the failure is auditable after a restart.
        self.assertEqual(store.records(), ())
        reopened = self.restart(store)
        self.assertEqual(reopened.records(), ())
        self.assertEqual([run.status for run in reopened.runs()], [RunStatus.FAILED])

    def test_12_unsafe_filenames_fail_closed(self) -> None:
        unsafe_names = (
            "../escape.txt",
            "..\\escape.txt",
            "nested/dir.txt",
            "nested\\dir.txt",
            "/etc/passwd",
            "C:/windows/system32/config.txt",
            "C:\\temp\\secret.txt",
            "a\x00b.txt",
            "",
            "   ",
            ".",
            "..",
            "a..b.txt",
            "CON.txt",
            "nul.md",
            "dotted.",
            "stream:ads.txt",
            "bad<name>.txt",
            "bad|name.txt",
            "x" * 256 + ".txt",
        )
        store = self.open_store()
        for name in unsafe_names:
            with self.subTest(filename=name):
                with self.assertRaises(ImportFailure) as caught:
                    store.import_bytes(name, b"payload")
                self.assertIn(
                    str(caught.exception), {"UNSAFE_FILENAME", "INVALID_FILENAME"}
                )
        # Nothing was persisted and no blob directory was created.
        self.assertEqual(store.records(), ())
        self.assertEqual(store.runs(), ())
        self.assertFalse(store.original_directory.exists())

        # Surrounding whitespace is stripped first (the existing slice's
        # convention), so only the Windows-safe remainder is stored.
        normalized = store.import_bytes("  spaced.txt  ", b"payload")
        self.assertEqual(normalized.record.filename, "spaced.txt")

        # A non-ASCII but safe filename is still accepted (Hangul archive names).
        accepted = store.import_bytes("나의 일기.txt", TXT_BODY)
        self.assertEqual(accepted.record.filename, "나의 일기.txt")
        self.assertTrue(store.verify_original(accepted.record.source_id))


class ReindexAndUserStateTests(DurableRuntimeTestCase):
    def test_08_reindex_keeps_annotation_present_and_resolvable(self) -> None:
        store = self.open_store()
        result = store.import_bytes("notes.md", MARKDOWN_BODY)
        source_id = result.record.source_id
        text = store.resolve(source_id, 1, "section:2").text
        annotation = store.add_annotation(
            source_id,
            "section:2",
            anchor_start=0,
            anchor_end=len("## Second"),
            note="chapter heading",
        )
        self.assertEqual(annotation.anchor_text, "## Second")

        run = store.reindex(source_id, 1, implementation_version="b59-durable-local-runtime/2")
        self.assertEqual(run.run_kind, RunKind.REINDEX)
        self.assertEqual(run.status, RunStatus.READY)
        self.assertEqual(run.implementation_version, "b59-durable-local-runtime/2")

        annotations = store.list_annotations(source_id, source_version=1)
        self.assertEqual(annotations, (annotation,))
        resolution = store.resolve_annotation(source_id, annotation.annotation_id)
        self.assertTrue(resolution.resolved)
        self.assertIsNone(resolution.reason)
        self.assertEqual(resolution.resolved_text, "## Second")
        self.assertEqual(resolution.annotation.anchor_start, 0)
        self.assertEqual(resolution.annotation.anchor_end, len("## Second"))
        self.assertEqual(store.resolve(source_id, 1, "section:2").text, text)
        self.assertEqual(len(store.search("mapping")), 1)

    def test_09_reindex_preserves_bookmark_title_tag_and_reading_position(self) -> None:
        store = self.open_store()
        result = store.import_bytes("notes.md", MARKDOWN_BODY)
        source_id = result.record.source_id
        store.set_title(source_id, "나의 기록서재")
        store.add_tag(source_id, "archive")
        store.add_tag(source_id, "2026")
        bookmark = store.add_bookmark(source_id, "section:1", label="start here")
        position = store.set_reading_position(source_id, "section:1", 6)

        run = store.reindex(source_id)
        self.assertEqual(run.status, RunStatus.READY)

        self.assertEqual(store.get_title(source_id), "나의 기록서재")
        self.assertEqual(store.list_tags(source_id), ("2026", "archive"))
        self.assertEqual(store.list_bookmarks(source_id), (bookmark,))
        self.assertEqual(store.get_reading_position(source_id), position)
        self.assertEqual(store.get_reading_position(source_id).char_offset, 6)
        # Title corrections are searchable and survive the derived regeneration.
        self.assertEqual(len(store.search("기록서재")), 2)

        reopened = self.restart(store)
        self.assertEqual(reopened.get_title(source_id), "나의 기록서재")
        self.assertEqual(reopened.list_bookmarks(source_id), (bookmark,))
        self.assertEqual(reopened.get_reading_position(source_id).char_offset, 6)
        self.assertEqual(reopened.list_tags(source_id), ("2026", "archive"))

    def test_10_derived_deletion_and_regeneration_preserve_source_and_user_state(self) -> None:
        store = self.open_store()
        result = store.import_bytes("journal.txt", TXT_BODY)
        source_id = result.record.source_id
        original = store.get_original(source_id)
        anchor_ids = self.anchor_ids(store, source_id, 1)
        store.set_title(source_id, "Kept title")
        store.add_tag(source_id, "kept")
        annotation = store.add_annotation(
            source_id, "section:2", anchor_start=0, anchor_end=6, note="kept note"
        )
        bookmark = store.add_bookmark(source_id, "section:2", label="kept bookmark")
        position = store.set_reading_position(source_id, "section:2", 3)

        removed = store.delete_derived(source_id, 1)
        self.assertEqual(removed, 3)
        self.assertEqual(self.anchor_ids(store, source_id, 1), ())

        # Derived data is gone: search is honestly empty and the record says so.
        self.assertEqual(store.search("anchor"), ())
        self.assertEqual(store.get_record(source_id).error_code, DERIVED_INDEX_MISSING)
        with self.assertRaises(KeyError):
            store.resolve(source_id, 1, "section:2")
        # Original source and every user record are untouched.
        self.assertEqual(store.get_original(source_id), original)
        self.assertTrue(store.verify_original(source_id))
        self.assertEqual(store.get_title(source_id), "Kept title")
        self.assertEqual(store.list_tags(source_id), ("kept",))
        self.assertEqual(store.list_annotations(source_id), (annotation,))
        self.assertEqual(store.list_bookmarks(source_id), (bookmark,))
        self.assertEqual(store.get_reading_position(source_id), position)
        unresolved = store.resolve_annotation(source_id, annotation.annotation_id)
        self.assertFalse(unresolved.resolved)
        self.assertEqual(unresolved.reason, DERIVED_ANCHOR_MISSING)

        run = store.reindex(source_id)
        self.assertEqual(run.status, RunStatus.READY)

        self.assertEqual(len(store.search("anchor")), 1)
        self.assertEqual(store.get_record(source_id).extraction_status, ImportStatus.READY)
        self.assertEqual(self.anchor_ids(store, source_id, 1), anchor_ids)
        self.assertEqual(store.get_original(source_id), original)
        self.assertEqual(store.get_title(source_id), "Kept title")
        self.assertEqual(store.list_tags(source_id), ("kept",))
        self.assertEqual(store.list_annotations(source_id), (annotation,))
        self.assertEqual(store.list_bookmarks(source_id), (bookmark,))
        self.assertEqual(store.get_reading_position(source_id), position)
        self.assertTrue(store.resolve_annotation(source_id, annotation.annotation_id).resolved)

    def test_08b_annotation_reports_drift_instead_of_silently_moving(self) -> None:
        store = self.open_store()
        result = store.import_bytes("notes.md", MARKDOWN_BODY)
        source_id = result.record.source_id
        annotation = store.add_annotation(
            source_id, "section:2", anchor_start=0, anchor_end=5, note="heading span"
        )
        # Simulate an implementation whose extraction shifted the text: the
        # user record must not be dragged along silently.
        store.connection.execute(
            "UPDATE derived_anchors SET text = ? WHERE source_id = ? AND page_or_section = ?",
            ("ZZZZZZ shifted", source_id, "section:2"),
        )
        resolution = store.resolve_annotation(source_id, annotation.annotation_id)
        self.assertFalse(resolution.resolved)
        self.assertEqual(resolution.reason, ANCHOR_TEXT_DRIFT)
        self.assertEqual(store.list_annotations(source_id), (annotation,))
        self.assertEqual(annotation.anchor_text, "## Se")

    def test_16_reindex_failure_keeps_previous_derived_index(self) -> None:
        store = self.open_store()
        result = store.import_bytes("report.pdf", synthetic_fixture_pdf())
        source_id = result.record.source_id

        with mock.patch.object(
            durable_index, "_extract_text", side_effect=ImportFailure("MALFORMED_PDF")
        ):
            run = store.reindex(source_id, implementation_version="broken/1")

        self.assertEqual(run.status, RunStatus.PARTIAL)
        self.assertEqual(run.error_code, "MALFORMED_PDF")
        # The previously working derived index was not destroyed by the failure.
        self.assertEqual(len(store.search("source mapping")), 1)
        self.assertTrue(run.original_readable)
        self.assertEqual(store.get_original(source_id), synthetic_fixture_pdf())
        self.assertEqual([run.run_kind for run in store.runs(source_id)], ["IMPORT", "REINDEX"])


class LifecycleModelTests(DurableRuntimeTestCase):
    def test_15_stage_vocabulary_is_exactly_the_contract(self) -> None:
        self.assertEqual(
            STAGE_NAMES,
            (
                "RECEIVED",
                "VALIDATED",
                "STORED",
                "TEXT_EXTRACTED",
                "PREVIEW_RENDERED",
                "INDEXED",
                "READY",
                "PARTIAL",
                "FAILED",
            ),
        )
        self.assertEqual(tuple(stage.value for stage in ImportStage), STAGE_NAMES)
        self.assertEqual(IMPORT_IMPLEMENTATION_VERSION, "b59-durable-local-runtime/1")

        store = self.open_store()
        txt = store.import_bytes("journal.txt", TXT_BODY)
        store.import_bytes("broken.pdf", b"not a valid pdf")
        store.reindex(txt.record.source_id)

        persisted = store.connection.execute(
            "SELECT DISTINCT stage FROM import_stage_events ORDER BY stage"
        ).fetchall()
        stage_values = {row["stage"] for row in persisted}
        self.assertTrue(stage_values.issubset(set(STAGE_NAMES)))
        self.assertIn("PREVIEW_RENDERED", stage_values)
        self.assertIn("PARTIAL", stage_values)
        deferred = store.connection.execute(
            "SELECT outputs, detail FROM import_stage_events WHERE stage = 'PREVIEW_RENDERED'"
        ).fetchall()
        self.assertEqual(len(deferred), 3)  # two imports + one re-index
        for row in deferred:
            self.assertEqual(row["outputs"], "[]")
            self.assertIn("deferred", row["detail"])

        # Deferred artifacts are recorded as deferred, never as a produced pass.
        distribution = store.connection.execute(
            """
            SELECT artifact_type, status, count(*) AS total FROM derived_artifacts
            GROUP BY artifact_type, status ORDER BY artifact_type, status
            """
        ).fetchall()
        self.assertEqual(
            [(row["artifact_type"], row["status"], row["total"]) for row in distribution],
            [
                ("EXACT_ANCHOR_INDEX", "READY", 1),
                ("PREVIEW_RENDER", "DEFERRED", 2),
                ("TEXT_EXTRACTION", "FAILED", 1),
                ("TEXT_EXTRACTION", "READY", 1),
            ],
        )
        for run in store.runs():
            self.assertNotIn("PREVIEW_RENDER", run.outputs)
        self.assertEqual(ArtifactStatus.DEFERRED.value, "DEFERRED")

        # The vocabulary is enforced by the schema, not only by convention.
        run_id = store.runs()[0].run_id
        with self.assertRaises(sqlite3.IntegrityError):
            store.connection.execute(
                """
                INSERT INTO import_stage_events
                    (run_id, stage, ordinal, status, started_at, ended_at, detail, outputs)
                VALUES (?, 'PREVIEW_PASSED', 99, 'PASSED', 'a', 'b', NULL, '[]')
                """,
                (run_id,),
            )

    def test_15b_stage_events_carry_start_end_status_and_outputs(self) -> None:
        store = self.open_store()
        result = store.import_bytes("journal.txt", TXT_BODY)
        run = result.run
        self.assertEqual(run.run_kind, RunKind.IMPORT)
        self.assertEqual(run.implementation_version, IMPORT_IMPLEMENTATION_VERSION)
        self.assertEqual(run.error_code, None)
        self.assertFalse(run.retryable)
        self.assertTrue(run.original_readable)
        self.assertEqual(run.started_at, result.record.imported_at)
        self.assertLess(run.started_at, run.ended_at)
        self.assertEqual([event.ordinal for event in run.stages], list(range(1, 8)))
        for event in run.stages:
            self.assertTrue(event.started_at <= event.ended_at)
            self.assertIn(event.status, {"PASSED", "FAILED", "DEFERRED"})
        stored = run.stage(ImportStage.STORED)
        self.assertEqual(stored.outputs, ("ORIGINAL_SOURCE",))
        self.assertEqual(run.stage(ImportStage.INDEXED).outputs, ("EXACT_ANCHOR_INDEX",))
        self.assertIsNone(run.stage(ImportStage.PREVIEW_RENDERED).outputs or None)

        reloaded = self.restart(store).run(run.run_id)
        self.assertEqual(reloaded, run)


class ZeroNetworkTests(DurableRuntimeTestCase):
    FORBIDDEN_CALLS = {"urlopen", "socket", "create_connection", "getaddrinfo", "socketpair"}

    def test_13_runtime_modules_import_no_network_client(self) -> None:
        for module in RUNTIME_MODULES:
            with self.subTest(module=module.__name__):
                source = Path(module.__file__).read_text(encoding="utf-8")
                tree = ast.parse(source)
                roots: set[str] = set()
                called: set[str] = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        roots.update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        roots.add((node.module or "").split(".")[0])
                    elif isinstance(node, ast.Name):
                        if node.id in {"__import__", "importlib", "eval", "exec", "compile"}:
                            called.add(node.id)
                    elif isinstance(node, ast.Attribute):
                        if node.attr in self.FORBIDDEN_CALLS:
                            called.add(node.attr)
                self.assertEqual(roots & FORBIDDEN_NETWORK_ROOTS, set())
                self.assertEqual(called, set())
        self.assertEqual(MODEL_EXECUTION, "OFF")
        self.assertEqual(NETWORK_CALLS, 0)

    def test_13b_full_local_cycle_works_while_sockets_are_disabled(self) -> None:
        def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("network access attempted by the local runtime")

        with mock.patch.object(socket, "socket", forbidden), mock.patch.object(
            socket, "create_connection", forbidden
        ), mock.patch.object(socket, "getaddrinfo", forbidden):
            store = self.open_store()
            txt = store.import_bytes("journal.txt", TXT_BODY)
            pdf = store.import_bytes("report.pdf", synthetic_fixture_pdf())
            self.assertEqual(len(store.search("anchor")), 1)
            annotation = store.add_annotation(
                txt.record.source_id, "section:2", anchor_start=0, anchor_end=6, note="local"
            )
            store.set_reading_position(txt.record.source_id, "section:2", 2)
            self.assertEqual(store.reindex(txt.record.source_id).status, RunStatus.READY)
            self.assertTrue(
                store.resolve_annotation(txt.record.source_id, annotation.annotation_id).resolved
            )
            self.assertEqual(len(store.search("source mapping")), 1)
            self.assertEqual(store.get_original(pdf.record.source_id), synthetic_fixture_pdf())

            reopened = self.restart(store)
            self.assertEqual(len(reopened.search("anchor")), 1)
            self.assertEqual(reopened.get_original(txt.record.source_id), TXT_BODY)
            self.assertEqual(
                persistence.applied_versions(reopened.connection),
                ("0001_durable_local_runtime",),
            )


if __name__ == "__main__":
    unittest.main()
