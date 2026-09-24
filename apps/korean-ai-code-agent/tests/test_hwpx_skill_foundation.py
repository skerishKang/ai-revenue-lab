"""#2937: HWPX Skill foundation (inspect/read/validate) contract tests."""

from __future__ import annotations

import io
import unittest
import zipfile
from pathlib import Path

from kagent import hwpx_skill
from kagent.claw_skill_registry import (
    CAPABILITY_FILE_INSPECT,
    CAPABILITY_HWPX_READ,
    CAPABILITY_HWPX_VALIDATE,
    RESERVED_CAPABILITY_IDS,
)
from kagent.document_parser_contract import is_bounded_reason_code
from kagent.hwpx_skill import (
    STATUS_OK,
    STATUS_REFUSED,
    VALIDATION_SCOPE_GATE_AND_TEXT,
    hwpx_inspect,
    hwpx_read,
    hwpx_validate,
)

MODULE_PATH = Path(hwpx_skill.__file__)

INSPECT_KEYS = frozenset(
    {"status", "capability_id", "reason_code", "gate"}
)
GATE_KEYS = frozenset(
    {
        "decision",
        "reason_code",
        "detected_format",
        "detected_media_type",
        "extension_media_type",
        "mismatch",
        "encrypted",
        "byte_size",
        "archive_entry_count",
        "archive_uncompressed_bytes",
        "archive_depth",
        "safe_to_parse",
        "hwpx_candidate",
    }
)
READ_KEYS = frozenset({"status", "capability_id", "reason_code", "note", "text"})
VALIDATE_KEYS = frozenset(
    {
        "status",
        "capability_id",
        "reason_code",
        "note",
        "scope",
        "full_spec_support_claimed",
        "text_present",
        "gate",
    }
)


def _hwpx_section_xml(*paragraphs: str) -> str:
    body = "".join(
        f"<hp:p><hp:r><hp:t>{paragraph}</hp:t></hp:r></hp:p>"
        for paragraph in paragraphs
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
        ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        + body
        + "</hs:sec>"
    )


def _build_zip(
    members: list[tuple[str, bytes]], *, external_attr: int | None = None
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if external_attr is not None:
                info.external_attr = external_attr
            archive.writestr(info, payload)
    return buffer.getvalue()


def _minimal_hwpx(*paragraphs: str) -> bytes:
    section = _hwpx_section_xml(*(paragraphs or ("Hello HwpX Document",)))
    return _build_zip(
        [
            ("mimetype", b"application/hwp+zip"),
            ("Contents/section0.xml", section.encode("utf-8")),
        ]
    )


def _corrupt_hwpx() -> bytes:
    return _build_zip(
        [
            ("mimetype", b"application/hwp+zip"),
            ("Contents/section0.xml", b"<broken"),
        ]
    )


def _wrong_mimetype_hwpx() -> bytes:
    section = _hwpx_section_xml("Hello HwpX Document")
    return _build_zip(
        [
            ("mimetype", b"application/zip"),
            ("Contents/section0.xml", section.encode("utf-8")),
        ]
    )


def _hwpx_with_bomb() -> bytes:
    section = _hwpx_section_xml("bomb")
    return _build_zip(
        [
            ("mimetype", b"application/hwp+zip"),
            ("Contents/section0.xml", section.encode("utf-8")),
            ("bomb.bin", b"\x00" * 500_000),
        ]
    )


def _hwpx_with_traversal() -> bytes:
    section = _hwpx_section_xml("traversal")
    return _build_zip(
        [
            ("mimetype", b"application/hwp+zip"),
            ("Contents/section0.xml", section.encode("utf-8")),
            ("../escape.xml", b"<x/>"),
        ]
    )


def _mark_encrypted(payload: bytes) -> bytes:
    data = bytearray(payload)
    position = 0
    while True:
        index = data.find(b"PK\x01\x02", position)
        if index == -1:
            break
        data[index + 8] |= 0x01
        position = index + 4
    return bytes(data)


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class HwpxInspectFoundationTests(unittest.TestCase):
    def test_valid_hwpx_returns_bounded_ok_metadata(self) -> None:
        payload = _minimal_hwpx("견적서")
        receipt = hwpx_inspect("doc.hwpx", payload)
        self.assertEqual(receipt.status, STATUS_OK)
        self.assertEqual(receipt.reason_code, "ok")
        self.assertEqual(receipt.capability_id, CAPABILITY_FILE_INSPECT)
        gate = receipt.gate
        self.assertEqual(gate.decision, "safe_candidate")
        self.assertEqual(gate.detected_format, "hwpx_candidate")
        self.assertEqual(gate.detected_media_type, "application/hwp+zip")
        self.assertEqual(gate.extension_media_type, "application/hwp+zip")
        self.assertFalse(gate.mismatch)
        self.assertFalse(gate.encrypted)
        self.assertEqual(gate.byte_size, len(payload))
        self.assertGreaterEqual(gate.archive_entry_count, 2)
        self.assertGreater(gate.archive_uncompressed_bytes, 0)
        self.assertEqual(gate.archive_depth, 0)
        self.assertTrue(gate.safe_to_parse)
        self.assertTrue(gate.hwpx_candidate)
        self.assertTrue(is_bounded_reason_code(gate.reason_code))

    def test_public_dict_is_exactly_the_bounded_key_set(self) -> None:
        receipt = hwpx_inspect("doc.hwpx", _minimal_hwpx())
        public = receipt.to_public_dict()
        self.assertEqual(set(public), set(INSPECT_KEYS))
        self.assertEqual(set(public["gate"]), set(GATE_KEYS))
        for key in list(public) + list(GATE_KEYS):
            lowered = str(key).lower()
            self.assertNotIn("filename", lowered)
            self.assertNotIn("path", lowered)
            self.assertNotIn("member", lowered)
            self.assertNotIn("payload", lowered)
            self.assertNotIn("xml", lowered)

    def test_plain_zip_renamed_hwpx_is_refused(self) -> None:
        payload = _build_zip([("data.bin", b"hello")])
        receipt = hwpx_inspect("fake.hwpx", payload)
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "hwpx_structure_missing")
        self.assertTrue(is_bounded_reason_code(receipt.reason_code))
        self.assertFalse(receipt.gate.hwpx_candidate)

    def test_wrong_declared_mimetype_is_refused(self) -> None:
        receipt = hwpx_inspect("wrong.hwpx", _wrong_mimetype_hwpx())
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "hwpx_mimetype_mismatch")
        self.assertTrue(receipt.gate.mismatch)

    def test_png_content_named_hwpx_is_content_mismatch_not_admission(self) -> None:
        receipt = hwpx_inspect("fake.hwpx", _png_bytes())
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "content_mismatch")
        self.assertEqual(receipt.gate.detected_format, "png")
        self.assertFalse(receipt.gate.hwpx_candidate)
        self.assertTrue(receipt.gate.safe_to_parse)

    def test_archive_bomb_is_refused_with_bounded_code(self) -> None:
        receipt = hwpx_inspect("bomb.hwpx", _hwpx_with_bomb())
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "archive_expansion_ratio")
        self.assertTrue(is_bounded_reason_code(receipt.reason_code))

    def test_empty_payload_is_refused(self) -> None:
        receipt = hwpx_inspect("doc.hwpx", b"")
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "empty_payload")

    def test_host_style_filename_never_appears_in_public_output(self) -> None:
        receipt = hwpx_inspect(r"C:\temp\secret\doc.hwpx", _minimal_hwpx())
        public = str(receipt.to_public_dict())
        self.assertNotIn("secret", public)
        self.assertNotIn("temp", public)
        self.assertNotIn("C:", public)
        self.assertNotIn("doc.hwpx", public)

    def test_inspect_runs_no_parser_text_surface(self) -> None:
        receipt = hwpx_inspect("doc.hwpx", _minimal_hwpx("견적서"))
        self.assertNotIn("text", receipt.to_public_dict())
        self.assertNotIn("견적서", str(receipt.to_public_dict()))


class HwpxReadFoundationTests(unittest.TestCase):
    def test_read_extracts_korean_paragraph_text(self) -> None:
        receipt = hwpx_read("note.hwpx", _minimal_hwpx("견적서", "합계 1,000원"))
        self.assertEqual(receipt.status, STATUS_OK)
        self.assertEqual(receipt.reason_code, "ok")
        self.assertEqual(receipt.capability_id, CAPABILITY_HWPX_READ)
        self.assertEqual(receipt.text, "견적서\n합계 1,000원")
        self.assertIsNone(receipt.note)

    def test_read_text_is_plain_not_raw_xml(self) -> None:
        receipt = hwpx_read("note.hwpx", _minimal_hwpx("견적서"))
        assert receipt.text is not None
        self.assertNotIn("<hp:t>", receipt.text)
        self.assertNotIn("hancom.co.kr", receipt.text)

    def test_read_corrupt_section_fails_closed_with_bounded_note(self) -> None:
        receipt = hwpx_read("bad.hwpx", _corrupt_hwpx())
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "intake_rejected")
        self.assertIsNone(receipt.text)
        assert receipt.note is not None
        self.assertIn("ooxml_invalid_xml", receipt.note)

    def test_read_wrong_mimetype_refused_at_common_gate(self) -> None:
        receipt = hwpx_read("wrong.hwpx", _wrong_mimetype_hwpx())
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "hwpx_mimetype_mismatch")
        self.assertIsNone(receipt.text)
        self.assertIsNone(receipt.note)

    def test_read_requires_hwpx_route_claim(self) -> None:
        receipt = hwpx_read("note.txt", _minimal_hwpx("견적서"))
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "hwpx_route_required")
        self.assertIsNone(receipt.text)

    def test_read_never_parses_non_hwpx_content(self) -> None:
        receipt = hwpx_read("plan.pdf", _png_bytes())
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "content_mismatch")
        self.assertIsNone(receipt.text)

    def test_read_fake_hwpx_bytes_refused_as_unknown_format(self) -> None:
        receipt = hwpx_read("fake.hwpx", b"PK not a real hwpx archive")
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "unknown_format")
        self.assertIsNone(receipt.text)

    def test_read_public_dict_keys_are_bounded(self) -> None:
        receipt = hwpx_read("bad.hwpx", _corrupt_hwpx())
        public = receipt.to_public_dict()
        self.assertEqual(set(public), set(READ_KEYS))
        self.assertNotIn("C:\\", str(public))


class HwpxValidateFoundationTests(unittest.TestCase):
    def test_validate_valid_package_is_ok_and_scope_bounded(self) -> None:
        receipt = hwpx_validate("doc.hwpx", _minimal_hwpx("견적서"))
        self.assertEqual(receipt.status, STATUS_OK)
        self.assertEqual(receipt.reason_code, "ok")
        self.assertEqual(receipt.capability_id, CAPABILITY_HWPX_VALIDATE)
        self.assertEqual(receipt.scope, VALIDATION_SCOPE_GATE_AND_TEXT)
        self.assertFalse(receipt.full_spec_support_claimed)
        self.assertTrue(receipt.text_present)
        self.assertTrue(receipt.gate.hwpx_candidate)
        self.assertIsNone(receipt.note)

    def test_validate_corrupt_section_is_refused_with_note(self) -> None:
        receipt = hwpx_validate("bad.hwpx", _corrupt_hwpx())
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "intake_rejected")
        self.assertFalse(receipt.text_present)
        assert receipt.note is not None
        self.assertIn("ooxml_invalid_xml", receipt.note)
        self.assertFalse(receipt.full_spec_support_claimed)

    def test_validate_archive_bomb_is_refused(self) -> None:
        receipt = hwpx_validate("bomb.hwpx", _hwpx_with_bomb())
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "archive_expansion_ratio")
        self.assertFalse(receipt.text_present)

    def test_validate_wrong_mimetype_is_refused(self) -> None:
        receipt = hwpx_validate("wrong.hwpx", _wrong_mimetype_hwpx())
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "hwpx_mimetype_mismatch")
        self.assertFalse(receipt.text_present)

    def test_validate_path_traversal_is_refused(self) -> None:
        receipt = hwpx_validate("evil.hwpx", _hwpx_with_traversal())
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "archive_unsafe_path")
        self.assertFalse(receipt.text_present)

    def test_validate_encrypted_archive_is_refused(self) -> None:
        payload = _mark_encrypted(_minimal_hwpx())
        receipt = hwpx_validate("locked.hwpx", payload)
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "archive_encrypted")
        self.assertTrue(receipt.gate.encrypted)
        self.assertFalse(receipt.text_present)

    def test_validate_missing_section_package_is_refused(self) -> None:
        payload = _build_zip([("mimetype", b"application/hwp+zip")])
        receipt = hwpx_validate("partial.hwpx", payload)
        self.assertEqual(receipt.status, STATUS_REFUSED)
        self.assertEqual(receipt.reason_code, "hwpx_structure_missing")
        self.assertFalse(receipt.text_present)

    def test_validate_never_claims_full_spec_support(self) -> None:
        for name, payload in (
            ("ok.hwpx", _minimal_hwpx()),
            ("bad.hwpx", _corrupt_hwpx()),
            ("bomb.hwpx", _hwpx_with_bomb()),
            ("fake.hwpx", _build_zip([("data.bin", b"x")])),
        ):
            with self.subTest(name=name):
                receipt = hwpx_validate(name, payload)
                self.assertFalse(receipt.full_spec_support_claimed)
                self.assertEqual(receipt.scope, VALIDATION_SCOPE_GATE_AND_TEXT)

    def test_validate_public_dict_is_bounded(self) -> None:
        receipt = hwpx_validate("doc.hwpx", _minimal_hwpx())
        public = receipt.to_public_dict()
        self.assertEqual(set(public), set(VALIDATE_KEYS))
        self.assertEqual(set(public["gate"]), set(GATE_KEYS))


class AuthorityContractTests(unittest.TestCase):
    def test_facade_source_adds_no_second_authority(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import zipfile",
            "ZipFile",
            "writestr",
            "BytesIO",
            "xml.etree",
            "extract_hwpx_text(",
            "extract_binary_document",
            "from padiem_ai_core.document_normalization",
            "subprocess",
            "import socket",
            "urllib",
            "import tempfile",
            "shutil",
            "os.system",
            "open(",
        ):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertIn("inspect_file", source)
        self.assertIn("intake_document", source)

    def test_facade_reaches_core_only_through_the_canonical_serializer(self) -> None:
        """#2962: the facade's whole Core surface is an allow-list, not a ban.

        ``serialize_hwpx_package`` is the accepted single HWPX byte authority
        and ``DocumentNormalizationError`` is its bounded failure type. Any
        other Core import — in particular the parser-layer normalizer that
        holds ``extract_hwpx_text`` — fails this test, so create cannot grow a
        second byte, XML or parser authority by accident.
        """

        source = MODULE_PATH.read_text(encoding="utf-8")
        imported_core_modules = {
            line.split()[1] for line in source.splitlines() if line.startswith("from padiem_ai_core")
        }
        # #2989 added the single package-preserving mutation authority, which
        # the template_fill facade composes. It is the accepted #2979 Core
        # mutator, so it joins the allow-list; no other Core module may.
        self.assertEqual(
            imported_core_modules,
            {
                "padiem_ai_core.document_semantics",
                "padiem_ai_core.hwpx_package_mutation",
                "padiem_ai_core.hwpx_package_serializer",
            },
        )
        self.assertIn("serialize_hwpx_package(", source)

    def test_capability_ids_are_existing_reserved_ids(self) -> None:
        self.assertIn(CAPABILITY_FILE_INSPECT, RESERVED_CAPABILITY_IDS)
        self.assertIn(CAPABILITY_HWPX_READ, RESERVED_CAPABILITY_IDS)
        self.assertIn(CAPABILITY_HWPX_VALIDATE, RESERVED_CAPABILITY_IDS)

    def test_acceptance_block_matches_issue_2937(self) -> None:
        expected = {
            "HWPX_INSPECT_FOUNDATION": "PASS",
            "HWPX_READ_FOUNDATION": "PASS",
            "HWPX_VALIDATE_FOUNDATION": "PASS",
            "COMMON_FILE_INTAKE_GATE_REUSED": "YES",
            "DIRECT_EXTENSION_AUTHORITY": "NO",
            "SECOND_HWPX_PARSER_AUTHORITY": "0",
            "SECOND_ARCHIVE_GATE_AUTHORITY": "0",
            "SECOND_XML_AUTHORITY": "0",
            "HOST_FS_EXTRACTION": "0",
            "RAW_XML_PUBLIC_OUTPUT": "0",
            "PAYLOAD_PUBLIC_OUTPUT": "0",
            "UNSUPPORTED_FEATURES_EXPLICIT": "YES",
            "NEW_RUNTIME_DEPENDENCY": "0",
            "NETWORK_CALLS": "0",
            "PROVIDER_CALLS": "0",
            "EXTERNAL_SEND": "0",
            "PRODUCTION_MUTATION": "0",
        }
        for key, value in expected.items():
            self.assertEqual(hwpx_skill.ACCEPTANCE.get(key), value, key)

    def test_bounded_capability_claims_remain_explicit(self) -> None:
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_CREATE_FOUNDATION"), "PASS")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_CREATE"), "FOUNDATION_ONLY")
        self.assertNotIn(hwpx_skill.ACCEPTANCE.get("HWPX_CREATE"), {"PASS", "YES"})
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_EDIT_FOUNDATION"), "PASS")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_EDIT"), "FOUNDATION_ONLY")
        self.assertNotIn(hwpx_skill.ACCEPTANCE.get("HWPX_EDIT"), {"PASS", "YES"})
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_TEMPLATE_FILL_FOUNDATION"), "PASS")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_TEMPLATE_FILL"), "PASS")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_TEMPLATE_FILL_SCOPE"), "BOUNDED_FOUNDATION")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_INSERT_TABLE_FACADE"), "PASS")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("TABLE_INSERT"), "PASS")
        self.assertEqual(
            hwpx_skill.ACCEPTANCE.get("TABLE_INSERT_SCOPE"),
            "BOUNDED_CANONICAL_BLOCK_SUBSET",
        )
        for key in ("TABLE_EDIT", "IMAGE_INSERT"):
            self.assertEqual(hwpx_skill.ACCEPTANCE.get(key), "NOT_CLAIMED", key)
            self.assertNotIn(hwpx_skill.ACCEPTANCE.get(key), {"PASS", "YES"})

    def test_create_edit_insert_table_and_template_fill_exist(self) -> None:
        for attribute in (
            "hwpx_create",
            "hwpx_edit",
            "hwpx_insert_table",
            "hwpx_template_fill",
        ):
            self.assertTrue(callable(getattr(hwpx_skill, attribute, None)), attribute)
        self.assertFalse(hasattr(hwpx_skill, "hwpx_insert_image"))

    def test_receipts_reject_unbounded_reason_codes(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxInspectReceipt(
                status=STATUS_REFUSED,
                capability_id=CAPABILITY_FILE_INSPECT,
                reason_code="leak:secret/path",
                gate=hwpx_skill.HwpxGateMetadata(
                    decision="safe_candidate",
                    reason_code="ok",
                    detected_format="hwpx_candidate",
                    detected_media_type="application/hwp+zip",
                    extension_media_type=None,
                    mismatch=False,
                    encrypted=False,
                    byte_size=1,
                    archive_entry_count=0,
                    archive_uncompressed_bytes=0,
                    archive_depth=0,
                    safe_to_parse=True,
                    hwpx_candidate=True,
                ),
            )

    def test_validate_receipt_cannot_claim_full_spec(self) -> None:
        gate = hwpx_skill.HwpxGateMetadata(
            decision="safe_candidate",
            reason_code="ok",
            detected_format="hwpx_candidate",
            detected_media_type="application/hwp+zip",
            extension_media_type=None,
            mismatch=False,
            encrypted=False,
            byte_size=1,
            archive_entry_count=0,
            archive_uncompressed_bytes=0,
            archive_depth=0,
            safe_to_parse=True,
            hwpx_candidate=True,
        )
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxValidateReceipt(
                status=STATUS_OK,
                capability_id=CAPABILITY_HWPX_VALIDATE,
                reason_code="ok",
                note=None,
                scope=VALIDATION_SCOPE_GATE_AND_TEXT,
                full_spec_support_claimed=True,
                text_present=True,
                gate=gate,
            )


if __name__ == "__main__":
    unittest.main()
