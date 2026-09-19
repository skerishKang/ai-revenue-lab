from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_runtime.source_index import (  # noqa: E402
    ImportStatus,
    LocalSourceIndex,
    MODEL_EXECUTION,
    NETWORK_CALLS,
    synthetic_fixture_pdf,
)


class LocalImportIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = LocalSourceIndex(
            clock=lambda: datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc)
        )

    def test_inventory_locks_model_execution_off_and_network_zero(self) -> None:
        self.assertEqual(MODEL_EXECUTION, "OFF")
        self.assertEqual(NETWORK_CALLS, 0)

    def test_txt_import_metadata_mapping_and_search(self) -> None:
        result = self.index.import_bytes(
            "journal.txt",
            b"First local entry.\n\nSecond local entry with anchor.",
        )
        self.assertEqual(result.record.extraction_status, ImportStatus.READY)
        self.assertEqual(result.record.mime_type, "text/plain")
        self.assertEqual(result.record.extension, ".txt")
        self.assertEqual(result.record.byte_size, 51)
        self.assertEqual(len(result.record.checksum), 64)
        hits = self.index.search("anchor")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].source_id, result.record.source_id)
        self.assertEqual(hits[0].source_version, 1)
        self.assertEqual(hits[0].page_or_section, "section:2")
        self.assertEqual(self.index.resolve(hits[0].source_id, hits[0].source_version, hits[0].page_or_section).text, hits[0].excerpt)

    def test_markdown_heading_sections_are_stable(self) -> None:
        result = self.index.import_bytes(
            "notes.md",
            b"# First\nAlpha local note.\n\n## Second\nBeta mapping note.",
        )
        hits = self.index.search("mapping")
        self.assertEqual(result.record.page_or_section_count, 2)
        self.assertEqual(hits[0].page_or_section, "section:2")
        self.assertTrue(hits[0].excerpt.startswith("## Second"))

    def test_extractable_pdf_import_maps_pages(self) -> None:
        result = self.index.import_bytes("report.pdf", synthetic_fixture_pdf())
        self.assertEqual(result.record.extraction_status, ImportStatus.READY)
        self.assertEqual(result.record.mime_type, "application/pdf")
        hits = self.index.search("source mapping")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].page_or_section, "page:2")
        self.assertEqual(self.index.resolve(hits[0].source_id, 1, "page:2").text, hits[0].excerpt)

    def test_failure_is_visible_and_original_is_preserved(self) -> None:
        original = b"not a valid pdf"
        result = self.index.import_bytes("broken.pdf", original)
        self.assertEqual(result.record.extraction_status, ImportStatus.FAILED)
        self.assertEqual(result.record.error_code, "MALFORMED_PDF")
        self.assertEqual(self.index.get_original(result.record.source_id, 1), original)
        self.assertEqual(self.index.search("valid"), ())

    def test_unsupported_fixture_fails_without_network_or_source_loss(self) -> None:
        result = self.index.import_bytes("archive.docx", b"synthetic unsupported")
        self.assertEqual(result.record.extraction_status, ImportStatus.FAILED)
        self.assertEqual(result.record.error_code, "UNSUPPORTED_FORMAT")
        self.assertEqual(self.index.get_original(result.record.source_id, 1), b"synthetic unsupported")

    def test_duplicate_checksum_returns_existing_record_deterministically(self) -> None:
        payload = b"same synthetic source"
        first = self.index.import_bytes("first.txt", payload)
        duplicate = self.index.import_bytes("renamed.txt", payload)
        self.assertFalse(first.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.record, first.record)
        self.assertEqual(len(self.index.records()), 1)

    def test_same_filename_changed_content_creates_next_version(self) -> None:
        first = self.index.import_bytes("versioned.txt", b"version one")
        second = self.index.import_bytes("versioned.txt", b"version two")
        self.assertEqual(first.record.source_id, second.record.source_id)
        self.assertEqual(first.record.source_version, 1)
        self.assertEqual(second.record.source_version, 2)
        self.assertEqual(self.index.get_original(first.record.source_id, 1), b"version one")
        self.assertEqual(self.index.get_original(second.record.source_id, 2), b"version two")


if __name__ == "__main__":
    unittest.main()
