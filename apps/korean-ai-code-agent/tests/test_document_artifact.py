"""#2115 in-memory generated document artifact handoff tests (network-free)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
import zipfile

from kagent.document_export import (
    DOCUMENT_ARTIFACT_KIND,
    DOCX_MEDIA_TYPE,
    MAX_DOCUMENT_ARTIFACT_BYTES,
    MD_MEDIA_TYPE,
    DocumentExportError,
    GeneratedDocumentArtifact,
    build_document_artifact,
    export_outcome_to_file,
    safe_document_filename,
)

QUOTA_ARGS = dict(
    document_type="quote",
    file_format="docx",
    title="견적서 초안 (2026-09)",
    metadata_fields=[("저장소", "test/repo"), ("거래처", "㈜한빛상사")],
    section_title="견적서 초안 (DRAFT)",
    body_text="견적 본문\n특이조건: 부가세 별도.",
    items=[("카테고리 A", "2주", "1,500,000", "3,000,000")],
    total="3,000,000",
    markdown_fallback_text="# 견적서\n\n- 합계: 3,000,000",
)


class BuildDocumentArtifactTests(unittest.TestCase):
    def test_docx_artifact_is_valid_nonempty_ooxml_with_full_metadata(self) -> None:
        artifact = build_document_artifact(**QUOTA_ARGS)
        self.assertIsInstance(artifact, GeneratedDocumentArtifact)
        content = artifact.content_bytes()
        self.assertGreater(len(content), 0)
        self.assertEqual(artifact.kind, DOCUMENT_ARTIFACT_KIND)
        self.assertEqual(artifact.document_type, "quote")
        self.assertEqual(artifact.format, "docx")
        self.assertEqual(artifact.media_type, DOCX_MEDIA_TYPE)
        self.assertEqual(artifact.byte_length, len(content))
        self.assertTrue(artifact.filename.endswith(".docx"))
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            self.assertIsNone(zf.testzip())
            names = set(zf.namelist())
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("_rels/.rels", names)
            self.assertIn("word/document.xml", names)
            document_xml = zf.read("word/document.xml").decode("utf-8")
            self.assertIn("견적서 초안", document_xml)
            self.assertIn("3,000,000", document_xml)

    def test_docx_artifact_bytes_identical_to_file_export(self) -> None:
        artifact = build_document_artifact(**QUOTA_ARGS)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "quote.docx"
            export_outcome_to_file(
                out_path=out,
                file_format=QUOTA_ARGS["file_format"],
                title=QUOTA_ARGS["title"],
                metadata_fields=QUOTA_ARGS["metadata_fields"],
                section_title=QUOTA_ARGS["section_title"],
                body_text=QUOTA_ARGS["body_text"],
                items=QUOTA_ARGS["items"],
                total=QUOTA_ARGS["total"],
                markdown_fallback_text=QUOTA_ARGS["markdown_fallback_text"],
            )
            self.assertEqual(out.read_bytes(), artifact.content_bytes())

    def test_markdown_artifact_uses_fallback_text_and_md_media_type(self) -> None:
        artifact = build_document_artifact(**{**QUOTA_ARGS, "file_format": "md"})
        self.assertEqual(artifact.format, "md")
        self.assertEqual(artifact.media_type, MD_MEDIA_TYPE)
        self.assertEqual(
            artifact.content_bytes(),
            QUOTA_ARGS["markdown_fallback_text"].encode("utf-8"),
        )
        self.assertTrue(artifact.filename.endswith(".md"))

    def test_in_memory_path_performs_no_filesystem_write(self) -> None:
        original_open = open
        writes: list[str] = []

        def spy_open(file, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            if any(flag in str(mode) for flag in ("w", "a", "x")):
                writes.append(str(file))
            return original_open(file, *args, **kwargs)

        import builtins

        builtins.open = spy_open
        try:
            build_document_artifact(**QUOTA_ARGS)
        finally:
            builtins.open = original_open
        self.assertEqual(writes, [])

    def test_hwpx_and_hwp_and_unknown_fail_closed_same_as_file_path(self) -> None:
        for fmt in ("hwpx", "hwp", "pdf"):
            with self.subTest(fmt=fmt):
                with self.assertRaises(DocumentExportError) as ctx:
                    build_document_artifact(**{**QUOTA_ARGS, "file_format": fmt})
                self.assertEqual(ctx.exception.code, "document_format_unsupported")

    def test_byte_bound_enforced_and_default_is_conservative(self) -> None:
        self.assertLessEqual(MAX_DOCUMENT_ARTIFACT_BYTES, 8 * 1024 * 1024)
        with self.assertRaises(DocumentExportError) as ctx:
            build_document_artifact(**QUOTA_ARGS, max_bytes=8)
        self.assertEqual(ctx.exception.code, "document_artifact_too_large")
        with self.assertRaises(DocumentExportError) as ctx:
            build_document_artifact(**QUOTA_ARGS, max_bytes=0)
        self.assertEqual(ctx.exception.code, "document_artifact_invalid")

    def test_invalid_document_type_fails_closed(self) -> None:
        with self.assertRaises(DocumentExportError) as ctx:
            build_document_artifact(**{**QUOTA_ARGS, "document_type": "   "})
        self.assertEqual(ctx.exception.code, "document_artifact_invalid")


class PublicProjectionTests(unittest.TestCase):
    def test_projection_is_json_safe_and_excludes_document_bytes(self) -> None:
        artifact = build_document_artifact(**QUOTA_ARGS)
        projection = artifact.public_projection()
        self.assertEqual(
            set(projection),
            {
                "kind",
                "document_type",
                "filename",
                "format",
                "media_type",
                "byte_length",
                "title",
                "summary",
            },
        )
        for key, value in projection.items():
            self.assertIsInstance(value, str | int, f"{key} must stay JSON metadata")
        serialized = json.dumps(projection, ensure_ascii=False)
        self.assertNotIn("word/document.xml", serialized)
        self.assertNotIn("base64", serialized.lower())
        self.assertNotIn("_Content_Types", serialized)
        blob_marker = artifact.content_bytes()[:64].hex()
        self.assertNotIn(blob_marker, serialized)

    def test_content_bytes_never_appear_in_repr(self) -> None:
        artifact = build_document_artifact(**QUOTA_ARGS)
        marker = "Padiem Claw · Deterministic".encode("utf-8")[:12]
        self.assertNotIn(marker.hex(), repr(artifact).lower())
        self.assertNotIn("content=", repr(artifact))


class BoundedDisplayTextTests(unittest.TestCase):
    def test_title_and_summary_bounded(self) -> None:
        long_title = "견적서 " + "가나다 " * 200
        artifact = build_document_artifact(**{**QUOTA_ARGS, "title": long_title})
        self.assertLessEqual(len(artifact.title), 120)
        self.assertTrue(artifact.title.endswith("…"))
        self.assertLessEqual(len(artifact.filename), 120 + len(".docx"))
        # Default summary derives from the first non-empty body line.
        self.assertEqual(artifact.summary, "견적 본문")
        custom = build_document_artifact(**{**QUOTA_ARGS, "summary": " 요약 " + "R" * 400})
        self.assertLessEqual(len(custom.summary), 120)
        self.assertTrue(custom.summary.startswith("요약"))

    def test_filename_survives_path_traversal_and_control_input(self) -> None:
        cases = [
            ("../../etc/passwd", "passwd"),
            ("C:\\Users\\secret\\견적서.docx.exe", "견적서"),
            ("..", None),
            ("....", None),
            ("", None),
            ("   ", None),
            ("견적/서\\이름:*?|<>\"\x00", "견적"),
            ("스페이스  두개\t탭", "스페이스"),
        ]
        for title, must_contain in cases:
            with self.subTest(title=title):
                name = safe_document_filename(title, "DOCX")
                self.assertNotIn("/", name)
                self.assertNotIn("\\", name)
                self.assertNotIn(":", name)
                self.assertNotIn("\x00", name)
                self.assertFalse(name.startswith("."))
                self.assertNotIn("..", name)
                self.assertTrue(name.endswith(".docx"))
                base = name[: -len(".docx")]
                self.assertTrue(base)
                self.assertLessEqual(len(base), 120)
                if must_contain is None:
                    self.assertEqual(name, "document.docx")
                else:
                    self.assertIn(must_contain, name)

    def test_unknown_format_filename_fails_closed(self) -> None:
        with self.assertRaises(DocumentExportError):
            safe_document_filename("견적서", "exe")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
