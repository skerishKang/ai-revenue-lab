"""#2824: generic bounded file intake safety gate tests.

All fixtures are generated in memory. No large binary is committed to the repo.
Every test is deterministic, provider-free and network-free.
"""

from __future__ import annotations

import random
import unittest
import zipfile

from io import BytesIO

from kagent.file_intake_safety import (
    DEFAULT_POLICY,
    MAX_SUPPORTED_ARCHIVE_DEPTH,
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


def _set_first_central_dir_compress_size(payload: bytes, value: int) -> bytes:
    """Patch the first central-directory record's compressed-size field."""

    data = bytearray(payload)
    index = data.find(b"PK\x01\x02")
    if index == -1:
        raise AssertionError("no central directory record to patch")
    data[index + 20 : index + 24] = value.to_bytes(4, "little")
    return bytes(data)


def hwpx_bytes(*, mimetype: bytes = b"application/hwp+zip") -> bytes:
    return build_zip(
        [
            ("mimetype", mimetype),
            ("Contents/section0.xml", b"<section><p>hello</p></section>"),
        ]
    )


def incompressible(size: int) -> bytes:
    """Deterministic random bytes: deflate cannot shrink them, ratio stays ~1."""

    return random.Random(0x28_24).randbytes(size)


def nested_chain(levels: int) -> bytes:
    """A ZIP nested inside a ZIP, ``levels`` deep (levels==1 is a bare ZIP)."""

    payload = build_zip([("leaf.txt", b"leaf")])
    for _ in range(max(0, levels - 1)):
        payload = build_zip([("inner.bin", payload)])
    return payload


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
        # Incompressible so the per-entry ratio guard stays quiet; the raw bound
        # is raised so the cumulative uncompressed bound is the limiter.
        members = [(f"big{index}.bin", incompressible(700_000)) for index in range(4)]
        policy = FileIntakePolicy(max_raw_bytes=4_000_000, max_archive_uncompressed_bytes=2_000_000)
        result = inspect_file("total.zip", build_zip(members), policy=policy)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_total_size")

    def test_zip_with_high_expansion_ratio_is_denied(self) -> None:
        # ~500 KB declared from a tiny compressed payload: classic zip bomb.
        payload = build_zip([("bomb.bin", b"\x00" * 500_000)])
        result = inspect_file("bomb.zip", payload, policy=FileIntakePolicy(max_archive_depth=1))
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_expansion_ratio")

    def test_zip_with_single_huge_entry_is_denied(self) -> None:
        payload = build_zip([("huge.bin", b"\x00" * 1_500_000)])
        result = inspect_file("huge.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_entry_size")

    def test_nested_archive_is_denied_by_default_policy(self) -> None:
        payload = build_zip([("inner.zip", build_zip([("a.txt", b"x")]))])
        result = inspect_file("outer.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_depth_exceeded")

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
                "archive_depth_reached",
                "encrypted",
                "safe_to_parse",
            },
        )


class NestedArchiveDepthTests(unittest.TestCase):
    """B1: nesting must be real, content-driven and budget-shared."""

    def test_nested_zip_disguised_as_bin_is_denied_by_default_policy(self) -> None:
        # The payload is a ZIP but the entry is named inner.bin: filename-based
        # detection would miss it entirely.
        payload = build_zip([("inner.bin", build_zip([("a.txt", b"x")]))])
        result = inspect_file("outer.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_depth_exceeded")

    def test_allowed_depth_matches_policy_exactly(self) -> None:
        three_deep = nested_chain(3)
        # depth budget 2 admits a two-level nest (top-level is depth 0).
        allowed = inspect_file("n.zip", three_deep, policy=FileIntakePolicy(max_archive_depth=2))
        denied = inspect_file("n.zip", three_deep, policy=FileIntakePolicy(max_archive_depth=1))
        self.assertEqual(allowed.decision, IntakeDecision.SAFE_CANDIDATE)
        self.assertEqual(allowed.archive_depth_reached, 2)
        self.assertEqual(denied.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(denied.reason_code, "archive_depth_exceeded")

    def test_three_level_chain_rejected_when_depth_is_zero(self) -> None:
        for levels in (2, 3, 4):
            with self.subTest(levels=levels):
                result = inspect_file("chain.zip", nested_chain(levels))
                self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
                self.assertEqual(result.reason_code, "archive_depth_exceeded")

    def test_nested_tree_shares_one_entry_budget(self) -> None:
        # Each level holds 6 entries; with a budget of 10 nothing resets per
        # level, so the shared count must trip.
        inner = build_zip([(f"i{i}.txt", b"x") for i in range(6)])
        outer = build_zip([("inner.bin", inner)] + [(f"o{i}.txt", b"x") for i in range(6)])
        shared = inspect_file("s.zip", outer, policy=FileIntakePolicy(max_archive_entries=10, max_archive_depth=2))
        self.assertEqual(shared.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(shared.reason_code, "archive_entry_count")
        # With a budget above the whole tree it is admitted, proving the count
        # above was genuinely cumulative rather than a single-level artefact.
        roomy = inspect_file("s.zip", outer, policy=FileIntakePolicy(max_archive_entries=64, max_archive_depth=2))
        self.assertEqual(roomy.decision, IntakeDecision.SAFE_CANDIDATE)
        self.assertEqual(roomy.archive_entry_count, 13)

    def test_nested_tree_shares_one_byte_budget(self) -> None:
        inner = build_zip([("big.bin", incompressible(80_000))])
        outer = build_zip([("inner.bin", inner), ("pad.bin", incompressible(80_000))])
        denied = inspect_file(
            "b.zip",
            outer,
            policy=FileIntakePolicy(
                max_archive_uncompressed_bytes=120_000,
                max_archive_depth=2,
            ),
        )
        self.assertEqual(denied.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(denied.reason_code, "archive_total_size")

    def test_high_expansion_nested_archive_is_rejected(self) -> None:
        bomb = build_zip([("bomb.bin", b"\x00" * 400_000)])
        outer = build_zip([("outer.bin", bomb), ("pad.bin", incompressible(100_000))])
        result = inspect_file("n.zip", outer, policy=FileIntakePolicy(max_archive_depth=2))
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_expansion_ratio")


class ExpansionRatioTests(unittest.TestCase):
    """B2: the ratio denominator must be real compressed content."""

    def test_ratio_uses_compressed_content_not_raw_payload(self) -> None:
        # A tight bomb entry cannot be hidden by unrelated incompressible
        # padding: the uncompressed budget stays the limiter and the per-entry
        # ratio is evaluated against the entry's own compressed size.
        bomb = build_zip([("bomb.bin", b"\x00" * 300_000)])
        padding = incompressible(300_000)
        outer = build_zip([("bomb.bin", bomb), ("pad.bin", padding)])
        result = inspect_file(
            "mixed.zip",
            outer,
            policy=FileIntakePolicy(max_archive_uncompressed_bytes=1_000_000, max_archive_depth=2),
        )
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertIn(result.reason_code, {"archive_expansion_ratio", "archive_entry_size"})

    def test_mixed_padding_does_not_authorise_a_bomb_entry(self) -> None:
        payload = build_zip(
            [("pad.bin", incompressible(200_000)), ("bomb.bin", b"\x00" * 900_000)]
        )
        result = inspect_file("mixed2.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_expansion_ratio")

    def test_incompressible_archive_is_admitted(self) -> None:
        # Ratio ~1: a legitimate archive of already-compressed bytes passes.
        payload = build_zip([("a.bin", incompressible(200_000))])
        result = inspect_file("real.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.SAFE_CANDIDATE)

    def test_invalid_compressed_size_fails_closed(self) -> None:
        payload = _set_first_central_dir_compress_size(build_zip([("a.txt", b"x" * 5000)]), 0)
        result = inspect_file("odd.zip", payload)
        self.assertEqual(result.decision, IntakeDecision.POLICY_DENIED)
        self.assertEqual(result.reason_code, "archive_compressed_size_invalid")


class PolicyValidationTests(unittest.TestCase):
    """Invalid policy values must fail closed, not widen authority."""

    def test_non_positive_bounds_are_rejected(self) -> None:
        for field in (
            "max_raw_bytes",
            "max_archive_entries",
            "max_archive_uncompressed_bytes",
            "max_single_archive_entry_bytes",
            "max_filename_bytes",
        ):
            with self.subTest(field=field):
                with self.assertRaises(FileIntakeSafetyError):
                    FileIntakePolicy(**{field: 0})
                with self.assertRaises(FileIntakeSafetyError):
                    FileIntakePolicy(**{field: -1})

    def test_non_positive_ratio_is_rejected(self) -> None:
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(FileIntakeSafetyError):
                    FileIntakePolicy(max_expansion_ratio=value)

    def test_depth_beyond_supported_maximum_is_rejected(self) -> None:
        FileIntakePolicy(max_archive_depth=MAX_SUPPORTED_ARCHIVE_DEPTH)
        with self.assertRaises(FileIntakeSafetyError):
            FileIntakePolicy(max_archive_depth=MAX_SUPPORTED_ARCHIVE_DEPTH + 1)
        with self.assertRaises(FileIntakeSafetyError):
            FileIntakePolicy(max_archive_depth=-1)

    def test_default_policy_is_no_nesting(self) -> None:
        self.assertEqual(DEFAULT_POLICY.max_archive_depth, 0)

    def test_valid_policy_is_accepted(self) -> None:
        policy = FileIntakePolicy(max_archive_depth=2, max_expansion_ratio=50.0)
        self.assertEqual(policy.max_archive_depth, 2)

    def test_repeated_input_is_deterministic(self) -> None:
        payload = hwpx_bytes()
        first = inspect_file("d.hwpx", payload)
        second = inspect_file("d.hwpx", payload)
        self.assertEqual(first.decision, second.decision)
        self.assertEqual(first.reason_code, second.reason_code)
        self.assertEqual(first.safe_dict(), second.safe_dict())


if __name__ == "__main__":
    unittest.main()
