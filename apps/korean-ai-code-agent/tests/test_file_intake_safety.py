"""#2824: generic bounded file intake safety gate tests.

All fixtures are generated in memory. No large binary is committed to the repo.
Every test is deterministic, provider-free and network-free.
"""

from __future__ import annotations

import unittest
import zipfile

from io import BytesIO

from kagent.file_intake_safety import (
    DEFAULT_POLICY,
    DetectedFormat,
    FileIntakePolicy,
    FileIntakeSafetyError,
    IntakeDecision,
    inspect_file,
    sanitize_filename,
)


PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF_BYTES = b"GIF89a" + b"\x00" * 32
WEBP_BYTES = b"RIFF" + (32).to_bytes(4, "little") + b"WEBP" + b"\x00" * 16
UNKNOWN_BYTES = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c"
OLE_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32

_S_IFLNK_MODE = 0o120777


def build_zip(
    members: list[tuple[str, bytes]],
    *,
    external_attr: int | None = None,
    flag_bits: int | None = None,
    compress: bool = True,
) -> bytes:
    """Build a ZIP in memory with optional per-entry metadata overrides."""

    buffer = BytesIO()
    mode = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", mode) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(name)
            # An explicit ZipInfo keeps ZipInfo's own default compress_type
            # (ZIP_STORED), so the archive's compression must be set here or
            # fixtures never diverge from their declared uncompressed size.
            info.compress_type = mode
            if external_attr is not None:
                info.external_attr = external_attr
            if flag_bits is not None:
                info.flag_bits = flag_bits
            archive.writestr(info, data)
    return buffer.getvalue()


def mark_encrypted(payload: bytes) -> bytes:
    """Set the encrypted flag on every central-directory record.

    ``zipfile.writestr`` overwrites ``ZipInfo.flag_bits``, so the bit cannot be
    authored through ``ZipInfo``. The gate reads entry flags from the central
    directory, which is what this patches.
    """

    data = bytearray(payload)
    position = 0
    while True:
        index = data.find(b"PK\x01\x02", position)
        if index == -1:
            break
        data[index + 8] |= 0x01
        position = index + 4
    return bytes(data)


def hwpx_bytes(*, mimetype: bytes = b"application/hwp+zip") -> bytes:
    return build_zip(
        [
            ("mimetype", mimetype),
            ("Contents/section0.xml", b"<section><p>hello</p></section>"),
        ]
    )


class SignatureClassificationTests(unittest.TestCase):
    def test_valid_pdf_signature_is_a_safe_candidate(self) -> None:
        result = inspect_file("report.pdf", PDF_BYTES)
        self.assertEqual(result.decision, IntakeDecision.SAFE_CANDIDATE)
        self.assertEqual(result.detected_format, DetectedFormat.PDF)
        self.assertTrue(result.safe_to_parse)
        self.assertFalse(result.mismatch)

    def test_pdf_extension_with_non_pdf_content_is_rejected(self) -> None:
        result = inspect_file("report.pdf", UNKNOWN_BYTES)
        self.assertEqual(result.decision, IntakeDecision.UNSUPPORTED)
        self.assertEqual(result.reason_code, "unknown_format")
        self.assertTrue(result.mismatch)
        self.assertFalse(result.safe_to_parse)

    def test_pdf_content_with_misleading_extension_still_detects_pdf(self) -> None:
        result = inspect_file("photo.png", PDF_BYTES)
        self.assertEqual(result.detected_format, DetectedFormat.PDF)
        self.assertEqual(result.detected_media_type, "application/pdf")
        self.assertEqual(result.extension_media_type, "image/png")
        self.assertTrue(result.mismatch)

    def test_valid_png_and_jpeg_signatures_are_safe_candidates(self) -> None:
        png = inspect_file("a.png", PNG_BYTES)
        jpeg = inspect_file("a.jpg", JPEG_BYTES)
        self.assertEqual(png.detected_format, DetectedFormat.PNG)
        self.assertEqual(jpeg.detected_format, DetectedFormat.JPEG)
        self.assertTrue(png.safe_to_parse and jpeg.safe_to_parse)
        self.assertFalse(png.mismatch and jpeg.mismatch)

    def test_gif_and_webp_signatures_are_classified(self) -> None:
        self.assertEqual(inspect_file("a.gif", GIF_BYTES).detected_format, DetectedFormat.GIF)
        self.assertEqual(inspect_file("a.webp", WEBP_BYTES).detected_format, DetectedFormat.WEBP)

    def test_unknown_binary_is_unsupported(self) -> None:
        result = inspect_file("blob.bin", UNKNOWN_BYTES)
        self.assertEqual(result.decision, IntakeDecision.UNSUPPORTED)
        self.assertEqual(result.detected_format, DetectedFormat.UNKNOWN)
        self.assertFalse(result.safe_to_parse)

    def test_legacy_ole_compound_is_unsupported(self) -> None:
        result = inspect_file("legacy.hwp", OLE_BYTES)
        self.assertEqual(result.detected_format, DetectedFormat.OLE_COMPOUND)
        self.assertEqual(result.reason_code, "legacy_ole_compound_unsupported")
        self.assertFalse(result.safe_to_parse)


class RawBoundTests(unittest.TestCase):
    def test_oversized_raw_file_is_denied_before_parser(self) -> None:
        policy = FileIntakePolicy(max_raw_bytes=64)
        result = inspect_file("big.pdf", PDF_BYTES + b"\x00" * 128, policy=policy)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "raw_too_large")
        self.assertFalse(result.safe_to_parse)

    def test_default_raw_bound_matches_core_binary_document_bound(self) -> None:
        self.assertEqual(DEFAULT_POLICY.max_raw_bytes, 2 * 1024 * 1024)
        oversized = b"%PDF-" + b"\x00" * DEFAULT_POLICY.max_raw_bytes
        result = inspect_file("big.pdf", oversized)
        self.assertEqual(result.reason_code, "raw_too_large")

    def test_empty_payload_is_corrupt(self) -> None:
        result = inspect_file("empty.pdf", b"")
        self.assertEqual(result.decision, IntakeDecision.CORRUPT)
        self.assertEqual(result.reason_code, "empty_payload")

    def test_non_bytes_payload_is_a_programming_error(self) -> None:
        with self.assertRaises(FileIntakeSafetyError):
            inspect_file("a.pdf", "not-bytes")  # type: ignore[arg-type]


class ArchiveSafetyTests(unittest.TestCase):
    def test_valid_bounded_zip_is_a_safe_candidate(self) -> None:
        payload = build_zip([("a.txt", b"hello"), ("b.txt", b"world")])
        result = inspect_file("bundle.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.SAFE_CANDIDATE)
        self.assertEqual(result.detected_format, DetectedFormat.ZIP_CONTAINER)
        self.assertEqual(result.archive_entry_count, 2)

    def test_zip_with_too_many_entries_is_denied(self) -> None:
        members = [(f"f{index}.txt", b"x") for index in range(DEFAULT_POLICY.max_archive_entries + 1)]
        result = inspect_file("many.zip", build_zip(members))
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_entry_count")

    def test_zip_with_excessive_total_uncompressed_bytes_is_denied(self) -> None:
        members = [(f"big{index}.bin", b"\x00" * 900_000) for index in range(10)]
        result = inspect_file("total.zip", build_zip(members))
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_total_size")

    def test_zip_with_high_expansion_ratio_is_denied(self) -> None:
        # ~500 KB declared from a tiny compressed payload: classic zip bomb.
        payload = build_zip([("bomb.bin", b"\x00" * 500_000)])
        result = inspect_file("bomb.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_expansion_ratio")

    def test_zip_with_single_huge_entry_is_denied(self) -> None:
        payload = build_zip([("huge.bin", b"\x00" * 1_500_000)])
        result = inspect_file("huge.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_entry_size")

    def test_nested_archive_is_denied_under_depth_policy(self) -> None:
        payload = build_zip([("inner.zip", build_zip([("a.txt", b"x")]))])
        result = inspect_file("outer.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "nested_archive_not_allowed")

    def test_corrupt_zip_is_classified_corrupt(self) -> None:
        result = inspect_file("broken.zip", b"PK\x03\x04" + b"\x00" * 24)
        self.assertEqual(result.decision, IntakeDecision.CORRUPT)
        self.assertEqual(result.reason_code, "archive_malformed")

    def test_encrypted_zip_is_classified_encrypted(self) -> None:
        payload = mark_encrypted(build_zip([("a.txt", b"secret")]))
        result = inspect_file("locked.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.ENCRYPTED)
        self.assertEqual(result.reason_code, "archive_encrypted")
        self.assertTrue(result.encrypted)
        self.assertFalse(result.safe_to_parse)


class ArchivePathSafetyTests(unittest.TestCase):
    def test_parent_traversal_entry_is_denied(self) -> None:
        payload = build_zip([("../evil.xml", b"x")])
        result = inspect_file("t.zip", payload)
        self.assertEqual(result.reason_code, "archive_unsafe_path")
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)

    def test_backslash_traversal_entry_is_denied(self) -> None:
        payload = build_zip([("..\\evil.xml", b"x")])
        result = inspect_file("t.zip", payload)
        self.assertEqual(result.reason_code, "archive_unsafe_path")

    def test_absolute_posix_entry_is_denied(self) -> None:
        payload = build_zip([("/etc/passwd", b"x")])
        result = inspect_file("t.zip", payload)
        self.assertEqual(result.reason_code, "archive_unsafe_path")

    def test_windows_drive_entry_is_denied(self) -> None:
        for name in ("C:/evil.xml", "C:\\evil.xml"):
            with self.subTest(name=name):
                result = inspect_file("t.zip", build_zip([(name, b"x")]))
                self.assertEqual(result.reason_code, "archive_unsafe_path")

    def test_unc_like_entry_is_denied(self) -> None:
        payload = build_zip([("\\\\server\\share\\evil.xml", b"x")])
        result = inspect_file("t.zip", payload)
        self.assertEqual(result.reason_code, "archive_unsafe_path")

    def test_symlink_entry_is_denied(self) -> None:
        payload = build_zip(
            [("link.txt", b"target")],
            external_attr=(_S_IFLNK_MODE << 16),
        )
        result = inspect_file("t.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_link_entry")


class HwpxSafetyTests(unittest.TestCase):
    def test_structural_hwpx_candidate_is_a_safe_candidate(self) -> None:
        result = inspect_file("doc.hwpx", hwpx_bytes())
        self.assertEqual(result.decision, IntakeDecision.SAFE_CANDIDATE)
        self.assertEqual(result.detected_format, DetectedFormat.HWPX_CANDIDATE)
        self.assertEqual(result.detected_media_type, "application/hwp+zip")
        self.assertFalse(result.mismatch)

    def test_fake_hwpx_ordinary_zip_renamed_hwpx_is_rejected(self) -> None:
        payload = build_zip([("a.txt", b"not a hangul document")])
        result = inspect_file("fake.hwpx", payload)
        self.assertEqual(result.decision, IntakeDecision.UNSUPPORTED)
        self.assertEqual(result.reason_code, "hwpx_structure_missing")
        self.assertTrue(result.mismatch)
        self.assertFalse(result.safe_to_parse)

    def test_malformed_hwpx_missing_section_is_rejected(self) -> None:
        payload = build_zip([("mimetype", b"application/hwp+zip")])
        result = inspect_file("partial.hwpx", payload)
        self.assertEqual(result.decision, IntakeDecision.UNSUPPORTED)
        self.assertEqual(result.reason_code, "hwpx_structure_missing")

    def test_hwpx_with_wrong_declared_mimetype_is_rejected(self) -> None:
        result = inspect_file("wrong.hwpx", hwpx_bytes(mimetype=b"application/zip"))
        self.assertEqual(result.decision, IntakeDecision.UNSUPPORTED)
        self.assertEqual(result.reason_code, "hwpx_mimetype_mismatch")

    def test_hwpx_bytes_are_not_approved_as_hwpx_without_markers(self) -> None:
        # A ZIP is never promoted to HWPX on the strength of being a ZIP alone.
        result = inspect_file("plain.zip", build_zip([("a.txt", b"x")]))
        self.assertEqual(result.detected_format, DetectedFormat.ZIP_CONTAINER)
        self.assertNotEqual(result.detected_format, DetectedFormat.HWPX_CANDIDATE)


class FilenameAndProjectionTests(unittest.TestCase):
    def test_filename_is_sanitized_to_a_flat_bounded_name(self) -> None:
        self.assertEqual(sanitize_filename("../../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename("C:\\tmp\\report.pdf"), "report.pdf")
        self.assertEqual(sanitize_filename("\\\\server\\share\\a.pdf"), "a.pdf")
        self.assertEqual(sanitize_filename(""), "unnamed")
        self.assertEqual(sanitize_filename(".."), "unnamed")

    def test_long_filename_is_bounded(self) -> None:
        long_name = "a" * 500 + ".pdf"
        self.assertLessEqual(len(sanitize_filename(long_name, max_bytes=64)), 64)

    def test_public_projection_leaks_no_raw_content_or_host_path(self) -> None:
        marker = b"RAWSECRETMARKERDO_NOT_LEAK"
        result = inspect_file("/tmp/secret/report.pdf", b"%PDF-" + marker)
        projection = str(result.safe_dict())
        self.assertNotIn("RAWSECRETMARKERDO_NOT_LEAK", projection)
        self.assertNotIn("/tmp/secret", projection)
        self.assertNotIn("Traceback", projection)
        for key in ("payload", "raw_content", "data", "traceback", "exception"):
            self.assertNotIn(key, result.safe_dict())

    def test_public_projection_has_only_bounded_fields(self) -> None:
        result = inspect_file("a.pdf", PDF_BYTES)
        self.assertEqual(
            set(result.safe_dict()),
            {
                "decision",
                "safe_reason_code",
                "detected_media_type",
                "extension_media_type",
                "mismatch",
                "raw_bytes",
                "filename",
                "archive_entry_count",
                "archive_uncompressed_bytes",
                "encrypted",
                "safe_to_parse",
            },
        )

    def test_repeated_input_is_deterministic(self) -> None:
        payload = hwpx_bytes()
        first = inspect_file("d.hwpx", payload)
        second = inspect_file("d.hwpx", payload)
        self.assertEqual(first.decision, second.decision)
        self.assertEqual(first.reason_code, second.reason_code)
        self.assertEqual(first.safe_dict(), second.safe_dict())


if __name__ == "__main__":
    unittest.main()
