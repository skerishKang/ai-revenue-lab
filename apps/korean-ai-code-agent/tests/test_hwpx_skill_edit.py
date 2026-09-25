"""#2972: hwpx.edit Skill facade contract tests.

The edit foundation must compose accepted authorities and add none: bounded
paragraph replacements go through the single Core structured decoder and the
single Core byte producer, and edited bytes are reported as success only after
the common intake gate, the existing validate authority, the existing read
authority and a structured decode of the output all agreed with the intended
edited model.

Nothing here writes to the host filesystem, opens a socket, or mutates
Production.
"""

from __future__ import annotations

import socket
import unittest
from dataclasses import FrozenInstanceError
from io import BytesIO
from pathlib import Path
from unittest import mock
from zipfile import ZIP_STORED, ZipFile

from padiem_ai_core.document_semantics import DocumentNormalizationError
from padiem_ai_core.hwpx_package_serializer import (
    MAX_HWPX_PARAGRAPH_CHARS,
    HwpxPackageContent,
    HwpxPackageSection,
    deserialize_hwpx_package,
    serialize_hwpx_package,
)

from kagent import hwpx_skill
from kagent.claw_skill_registry import CAPABILITY_HWPX_EDIT, RESERVED_CAPABILITY_IDS
from kagent.document_parser_contract import is_bounded_reason_code
from kagent.file_intake_safety import DetectedFormat, inspect_file
from kagent.hwpx_skill import (
    MAX_EDIT_OPERATIONS,
    REASON_EDIT_DUPLICATE_TARGET,
    REASON_EDIT_GATE_REJECTED,
    REASON_EDIT_INDEX_NEGATIVE,
    REASON_EDIT_OPERATION_SHAPE,
    REASON_EDIT_OPERATIONS_INVALID,
    REASON_EDIT_OPERATIONS_LIMIT,
    REASON_EDIT_OUTPUT_COUNT_DRIFT,
    REASON_EDIT_OUTPUT_GATE_REJECTED,
    REASON_EDIT_OUTPUT_NON_TARGET_DRIFT,
    REASON_EDIT_OUTPUT_READBACK_REJECTED,
    REASON_EDIT_OUTPUT_ROUNDTRIP_MISMATCH,
    REASON_EDIT_OUTPUT_VALIDATE_REJECTED,
    REASON_EDIT_PARAGRAPH_OUT_OF_RANGE,
    REASON_EDIT_SECTION_OUT_OF_RANGE,
    REASON_EDIT_SERIALIZER_REJECTED,
    REASON_EDIT_SOURCE_DECODER_REJECTED,
    REASON_EDIT_SOURCE_NOT_CANONICAL,
    REASON_EDIT_TEXT_REJECTED,
    STATUS_OK,
    STATUS_REFUSED,
    VALIDATION_SCOPE_GATE_AND_TEXT,
    VALIDATION_STATUS_EDIT_OK,
    HwpxParagraphReplacement,
    hwpx_create,
    hwpx_edit,
)

MODULE_PATH = Path(hwpx_skill.__file__ or "")

RECEIPT_KEYS = frozenset(
    {
        "status",
        "capability_id",
        "reason_code",
        "note",
        "media_type",
        "suggested_filename",
        "byte_size",
        "section_count",
        "paragraph_count",
        "replacement_count",
        "validation_status",
    }
)

SECTION_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/section"
PARAGRAPH_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HWPX_MIMETYPE = b"application/hwp+zip"

KOREAN_TEXT = "견적서"


def _content(*sections: tuple[str, ...]) -> HwpxPackageContent:
    return HwpxPackageContent(
        sections=tuple(HwpxPackageSection(paragraphs=tuple(paragraphs)) for paragraphs in sections)
    )


def _payload(*sections: tuple[str, ...]) -> bytes:
    """A real canonical HWPX package built by the accepted Core serializer."""

    return serialize_hwpx_package(_content(*sections))


def _replace(section_index: int, paragraph_index: int, text: str) -> HwpxParagraphReplacement:
    return HwpxParagraphReplacement(
        section_index=section_index,
        paragraph_index=paragraph_index,
        text=text,
    )


def _paragraph_xml(text: str) -> str:
    return f"<hp:p><hp:runs><hp:t>{text}</hp:t></hp:runs></hp:p>"


def _part_bytes(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hs:sec xmlns:hs="{SECTION_NAMESPACE}" xmlns:hp="{PARAGRAPH_NAMESPACE}">'
        f"{body}</hs:sec>"
    ).encode()


def _raw_package(parts: list[tuple[str, bytes]]) -> bytes:
    """Assemble a package by hand so a non-canonical source can be expressed."""

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name, content in parts:
            archive.writestr(name, content)
    return buffer.getvalue()


def _table_source() -> bytes:
    """A gate-admitted HWPX whose structure the editable model cannot represent."""

    body = (
        _paragraph_xml("표앞")
        + "<hp:tbl><hp:tr><hp:tc>"
        + _paragraph_xml("셀")
        + "</hp:tc></hp:tr></hp:tbl>"
    )
    return _raw_package(
        [("mimetype", HWPX_MIMETYPE), ("Contents/section1.xml", _part_bytes(body))]
    )


def _extra_member_source() -> bytes:
    """A gate-admitted, decodable HWPX carrying a part the writer does not own."""

    canonical = _payload(("본문", "둘째"))
    with ZipFile(BytesIO(canonical)) as archive:
        mimetype = archive.read("mimetype")
        section = archive.read("Contents/section1.xml")
    return _raw_package(
        [
            ("mimetype", mimetype),
            ("Contents/section1.xml", section),
            ("version.xml", b"<v>1</v>"),
        ]
    )


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _gate_metadata() -> hwpx_skill.HwpxGateMetadata:
    return hwpx_skill.HwpxGateMetadata.from_gate(inspect_file("fake.hwpx", _png_bytes()))


def _refused_validate_receipt() -> hwpx_skill.HwpxValidateReceipt:
    return hwpx_skill.HwpxValidateReceipt(
        status=STATUS_REFUSED,
        capability_id="hwpx.validate",
        reason_code="hwpx_mimetype_mismatch",
        note=None,
        scope=VALIDATION_SCOPE_GATE_AND_TEXT,
        full_spec_support_claimed=False,
        text_present=False,
        gate=_gate_metadata(),
    )


def _ok_validate_receipt() -> hwpx_skill.HwpxValidateReceipt:
    return hwpx_skill.HwpxValidateReceipt(
        status=STATUS_OK,
        capability_id="hwpx.validate",
        reason_code="ok",
        note=None,
        scope=VALIDATION_SCOPE_GATE_AND_TEXT,
        full_spec_support_claimed=False,
        text_present=True,
        gate=_gate_metadata(),
    )


def _refused_read_receipt() -> hwpx_skill.HwpxReadReceipt:
    return hwpx_skill.HwpxReadReceipt(
        status=STATUS_REFUSED,
        capability_id="hwpx.read",
        reason_code="hwpx_mimetype_mismatch",
        note=None,
        text=None,
    )


class HwpxEditSuccessTests(unittest.TestCase):
    def test_korean_paragraph_replacement_succeeds(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload((KOREAN_TEXT,)), (_replace(0, 0, "세금계산서"),))
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(result.receipt.reason_code, "ok")
        self.assertEqual(result.receipt.capability_id, CAPABILITY_HWPX_EDIT)
        self.assertEqual(result.receipt.validation_status, VALIDATION_STATUS_EDIT_OK)
        self.assertIsNone(result.receipt.note)
        self.assertEqual(result.receipt.replacement_count, 1)

    def test_multi_section_target_replacement_succeeds(self) -> None:
        payload = _payload(("첫섹션", "첫섹션둘"), ("둘째섹션",))
        result = hwpx_edit("doc.hwpx", payload, (_replace(1, 0, "수정된둘째"),))
        self.assertEqual(result.receipt.status, STATUS_OK)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[1].paragraphs, ("수정된둘째",))

    def test_multiple_distinct_replacements_are_atomic(self) -> None:
        payload = _payload(("A", "B"), ("C",))
        result = hwpx_edit(
            "doc.hwpx",
            payload,
            (_replace(0, 0, "A1"), _replace(0, 1, "B1"), _replace(1, 0, "C1")),
        )
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(result.receipt.replacement_count, 3)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("A1", "B1"))
        self.assertEqual(decoded.sections[1].paragraphs, ("C1",))

    def test_zero_based_addressing_is_exact(self) -> None:
        payload = _payload(("제로", "원", "둘"), ("다음섹션",))
        result = hwpx_edit("doc.hwpx", payload, (_replace(0, 2, "삼"), _replace(1, 0, "네")))
        decoded = deserialize_hwpx_package(result.artifact.payload)
        # Index 0 is the first paragraph of the first section, index 1 the next.
        self.assertEqual(decoded.sections[0].paragraphs, ("제로", "원", "삼"))
        self.assertEqual(decoded.sections[1].paragraphs, ("네",))

    def test_non_target_paragraphs_are_identical(self) -> None:
        payload = _payload(("보존1", "교체대상", "보존3"), ("보존4",))
        result = hwpx_edit("doc.hwpx", payload, (_replace(0, 1, "교체됨"),))
        source = deserialize_hwpx_package(payload)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        for section_index, section in enumerate(source.sections):
            for paragraph_index, text in enumerate(section.paragraphs):
                if (section_index, paragraph_index) == (0, 1):
                    continue
                self.assertEqual(
                    decoded.sections[section_index].paragraphs[paragraph_index], text
                )

    def test_section_count_is_unchanged(self) -> None:
        payload = _payload(("하나",), ("둘",), ("셋",))
        result = hwpx_edit("doc.hwpx", payload, (_replace(1, 0, "수정"),))
        self.assertEqual(result.receipt.section_count, 3)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(len(decoded.sections), 3)

    def test_paragraph_counts_are_unchanged(self) -> None:
        payload = _payload(("1", "2", "3"), ("4", "5"))
        result = hwpx_edit("doc.hwpx", payload, (_replace(0, 1, "수정"),))
        self.assertEqual(result.receipt.paragraph_count, 5)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(len(decoded.sections[0].paragraphs), 3)
        self.assertEqual(len(decoded.sections[1].paragraphs), 2)

    def test_same_request_is_deterministic(self) -> None:
        payload = _payload((KOREAN_TEXT, "합계 1,000원"))
        operations = (_replace(0, 0, "세금계산서"), _replace(0, 1, "합계 2,000원"))
        first = hwpx_edit("doc.hwpx", payload, operations)
        second = hwpx_edit("doc.hwpx", payload, operations)
        self.assertEqual(first.artifact.payload, second.artifact.payload)
        self.assertEqual(first.receipt.to_public_dict(), second.receipt.to_public_dict())

    def test_xml_metacharacter_text_round_trips_safely(self) -> None:
        payload = _payload((KOREAN_TEXT,))
        result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "<a> & </a> \"q\""),))
        self.assertEqual(result.receipt.status, STATUS_OK)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("<a> & </a> \"q\"",))

    def test_media_type_and_counts_are_reported(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.media_type, "application/hwp+zip")
        self.assertEqual(result.receipt.section_count, 1)
        self.assertEqual(result.receipt.paragraph_count, 1)
        self.assertGreater(result.receipt.byte_size, 0)

    def test_generated_bytes_pass_the_common_gate(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),))
        gate = inspect_file("out.hwpx", result.artifact.payload)
        self.assertEqual(gate.detected_format, DetectedFormat.HWPX_CANDIDATE)

    def test_existing_validate_and_read_accept_the_output(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문", "둘"),), (_replace(0, 0, "수정"),))
        self.assertEqual(hwpx_skill.hwpx_validate("out.hwpx", result.artifact.payload).status, STATUS_OK)
        read = hwpx_skill.hwpx_read("out.hwpx", result.artifact.payload)
        self.assertEqual(read.status, STATUS_OK)
        self.assertIn("수정", read.text or "")

    def test_output_decodes_to_the_intended_model(self) -> None:
        payload = _payload(("본문", "둘"), ("셋",))
        result = hwpx_edit("doc.hwpx", payload, (_replace(0, 1, "수정"), _replace(1, 0, "수정2")))
        self.assertEqual(
            deserialize_hwpx_package(result.artifact.payload),
            _content(("본문", "수정"), ("수정2",)),
        )

    def test_empty_replacement_text_is_allowed_while_the_document_stays_readable(self) -> None:
        payload = _payload(("남는문단", "지울문단"))
        result = hwpx_edit("doc.hwpx", payload, (_replace(0, 1, ""),))
        self.assertEqual(result.receipt.status, STATUS_OK)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("남는문단", ""))

    def test_maximum_operation_bound_is_accepted(self) -> None:
        paragraphs = tuple(f"문단{index}" for index in range(MAX_EDIT_OPERATIONS))
        operations = tuple(
            _replace(0, index, f"수정{index}") for index in range(MAX_EDIT_OPERATIONS)
        )
        result = hwpx_edit("doc.hwpx", _payload(paragraphs), operations)
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(result.receipt.replacement_count, MAX_EDIT_OPERATIONS)

    def test_artifact_holds_bounded_in_memory_bytes(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),))
        self.assertIsInstance(result.artifact.payload, bytes)
        self.assertEqual(result.artifact.byte_size, len(result.artifact.payload))
        self.assertEqual(result.artifact.media_type, "application/hwp+zip")
        self.assertEqual(result.artifact.replacement_count, 1)

    def test_suggested_filename_is_sanitized_flat(self) -> None:
        result = hwpx_edit("../../etc/passwd.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.suggested_filename, "passwd.hwpx")
        self.assertNotIn("/", result.receipt.suggested_filename or "")


class HwpxEditOperationRefusalTests(unittest.TestCase):
    def test_empty_operations_are_rejected(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), ())
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OPERATIONS_INVALID)
        self.assertIsNone(result.artifact)

    def test_non_tuple_operations_are_rejected(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), [_replace(0, 0, "수정")])
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OPERATIONS_INVALID)

    def test_operation_count_bound_is_enforced(self) -> None:
        operations = tuple(
            _replace(0, 0, f"수정{index}") for index in range(MAX_EDIT_OPERATIONS + 1)
        )
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), operations)
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OPERATIONS_LIMIT)
        self.assertIsNone(result.artifact)

    def test_bool_indexes_are_rejected_despite_being_int_like(self) -> None:
        payload = _payload(("본문", "둘"))
        for operation in (_replace(True, 0, "수정"), _replace(0, False, "수정")):
            result = hwpx_edit("doc.hwpx", payload, (operation,))
            self.assertEqual(result.receipt.reason_code, REASON_EDIT_OPERATION_SHAPE)
            self.assertIsNone(result.artifact)

    def test_negative_indexes_are_rejected(self) -> None:
        payload = _payload(("본문",))
        for operation in (_replace(-1, 0, "수정"), _replace(0, -1, "수정")):
            result = hwpx_edit("doc.hwpx", payload, (operation,))
            self.assertEqual(result.receipt.reason_code, REASON_EDIT_INDEX_NEGATIVE)
            self.assertIsNone(result.artifact)

    def test_non_integer_indexes_are_rejected(self) -> None:
        payload = _payload(("본문",))
        for operation in (_replace("0", 0, "수정"), _replace(0, 1.5, "수정")):
            result = hwpx_edit("doc.hwpx", payload, (operation,))
            self.assertEqual(result.receipt.reason_code, REASON_EDIT_OPERATION_SHAPE)

    def test_non_string_text_is_rejected(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, 123),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OPERATION_SHAPE)

    def test_foreign_operation_shape_is_rejected(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), ((0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OPERATION_SHAPE)

    def test_section_out_of_range_is_rejected(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(1, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_SECTION_OUT_OF_RANGE)
        self.assertIsNone(result.artifact)

    def test_paragraph_out_of_range_is_rejected(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 1, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_PARAGRAPH_OUT_OF_RANGE)
        self.assertIsNone(result.artifact)

    def test_duplicate_target_is_rejected(self) -> None:
        result = hwpx_edit(
            "doc.hwpx",
            _payload(("본문",)),
            (_replace(0, 0, "첫번째"), _replace(0, 0, "두번째")),
        )
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_DUPLICATE_TARGET)
        self.assertIsNone(result.artifact)

    def test_invalid_control_character_is_rejected(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, "제어\x00문자"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_TEXT_REJECTED)
        self.assertIsNone(result.artifact)

    def test_oversized_replacement_text_is_rejected(self) -> None:
        oversized = "가" * (MAX_HWPX_PARAGRAPH_CHARS + 1)
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, oversized),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_TEXT_REJECTED)
        self.assertIsNone(result.artifact)

    def test_replacing_the_only_text_with_nothing_is_rejected(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, ""),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_TEXT_REJECTED)
        self.assertIsNone(result.artifact)

    def test_noncanonical_table_source_fails_before_editing(self) -> None:
        payload = _table_source()
        self.assertEqual(
            inspect_file("t.hwpx", payload).detected_format, DetectedFormat.HWPX_CANDIDATE
        )
        result = hwpx_edit("t.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_SOURCE_NOT_CANONICAL)
        self.assertIsNone(result.artifact)

    def test_non_canonical_source_is_refused_by_the_canonical_source_gate(self) -> None:
        payload = _extra_member_source()
        self.assertEqual(
            inspect_file("e.hwpx", payload).detected_format, DetectedFormat.HWPX_CANDIDATE
        )
        # The model is readable, but re-serializing it does not reproduce the
        # input bytes, so editing would silently drop a part the writer does not
        # own. The gate must refuse instead.
        self.assertNotEqual(serialize_hwpx_package(deserialize_hwpx_package(payload)), payload)
        result = hwpx_edit("e.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_SOURCE_NOT_CANONICAL)
        self.assertEqual(result.receipt.validation_status, "source_not_canonical")
        self.assertIsNone(result.artifact)

    def test_source_gate_rejection_fails_closed(self) -> None:
        result = hwpx_edit("doc.hwpx", _png_bytes(), (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_GATE_REJECTED)
        self.assertIsNone(result.artifact)

    def test_source_decoder_rejection_fails_closed(self) -> None:
        payload = _payload(("본문",))
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package",
            side_effect=DocumentNormalizationError("hwpx_unsupported_structure", "refused"),
        ):
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_SOURCE_DECODER_REJECTED)
        self.assertEqual(result.receipt.note, "hwpx_unsupported_structure")
        self.assertIsNone(result.artifact)

    def test_serializer_error_produces_no_artifact(self) -> None:
        payload = _payload(("본문",))
        with mock.patch(
            "kagent.hwpx_skill.serialize_hwpx_package",
            side_effect=[
                payload,
                DocumentNormalizationError("hwpx_serialize_model", "refused"),
            ],
        ):
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_SERIALIZER_REJECTED)
        self.assertIsNone(result.artifact)

    def test_serializer_returning_no_bytes_fails_closed(self) -> None:
        payload = _payload(("본문",))
        with mock.patch(
            "kagent.hwpx_skill.serialize_hwpx_package", side_effect=[payload, b""]
        ):
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_SERIALIZER_REJECTED)
        self.assertIsNone(result.artifact)

    def test_output_gate_rejection_produces_no_success(self) -> None:
        payload = _payload(("본문",))
        denied = inspect_file("fake.hwpx", _png_bytes())
        with mock.patch(
            "kagent.hwpx_skill.inspect_file", side_effect=[inspect_file("doc.hwpx", payload), denied]
        ):
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OUTPUT_GATE_REJECTED)
        self.assertIsNone(result.artifact)

    def test_output_validate_rejection_produces_no_success(self) -> None:
        payload = _payload(("본문",))
        with mock.patch(
            "kagent.hwpx_skill.hwpx_validate", return_value=_refused_validate_receipt()
        ):
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OUTPUT_VALIDATE_REJECTED)
        self.assertIsNone(result.artifact)

    def test_output_readback_rejection_produces_no_success(self) -> None:
        payload = _payload(("본문",))
        # hwpx_validate composes hwpx_read internally, so the validate stage is
        # held at ok here to isolate the readback stage under test.
        with mock.patch(
            "kagent.hwpx_skill.hwpx_validate", return_value=_ok_validate_receipt()
        ), mock.patch("kagent.hwpx_skill.hwpx_read", return_value=_refused_read_receipt()):
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OUTPUT_READBACK_REJECTED)
        self.assertIsNone(result.artifact)

    def test_output_structured_mismatch_produces_no_success(self) -> None:
        payload = _payload(("본문",))
        source = deserialize_hwpx_package(payload)
        tampered = _content(("변조",))
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package", side_effect=[source, tampered]
        ):
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OUTPUT_ROUNDTRIP_MISMATCH)
        self.assertIsNone(result.artifact)

    def test_output_count_drift_produces_no_success(self) -> None:
        payload = _payload(("본문",))
        source = deserialize_hwpx_package(payload)
        tampered = _content(("수정", "추가문단"))
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package", side_effect=[source, tampered]
        ):
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OUTPUT_COUNT_DRIFT)
        self.assertIsNone(result.artifact)

    def test_output_non_target_drift_produces_no_success(self) -> None:
        payload = _payload(("보존대상", "교체대상"))
        source = deserialize_hwpx_package(payload)
        tampered = _content(("변조된보존문단", "수정"))
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package", side_effect=[source, tampered]
        ):
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 1, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OUTPUT_NON_TARGET_DRIFT)
        self.assertIsNone(result.artifact)

    def test_output_decoder_rejection_produces_no_success(self) -> None:
        payload = _payload(("본문",))
        source = deserialize_hwpx_package(payload)
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package",
            side_effect=[source, DocumentNormalizationError("hwpx_unsupported_structure", "x")],
        ):
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OUTPUT_ROUNDTRIP_MISMATCH)
        self.assertIsNone(result.artifact)

    def test_refusal_reason_codes_and_notes_are_bounded(self) -> None:
        payload = _payload(("본문",))
        cases = (
            ((), REASON_EDIT_OPERATIONS_INVALID),
            ((_replace(0, 0, "수정"), _replace(0, 0, "수정2")), REASON_EDIT_DUPLICATE_TARGET),
            ((_replace(5, 0, "수정"),), REASON_EDIT_SECTION_OUT_OF_RANGE),
            ((_replace(0, 9, "수정"),), REASON_EDIT_PARAGRAPH_OUT_OF_RANGE),
            ((_replace(0, 0, "제어\x01"),), REASON_EDIT_TEXT_REJECTED),
        )
        for operations, expected in cases:
            result = hwpx_edit("doc.hwpx", payload, operations)
            self.assertEqual(result.receipt.status, STATUS_REFUSED)
            self.assertEqual(result.receipt.reason_code, expected)
            self.assertTrue(is_bounded_reason_code(result.receipt.reason_code))
            self.assertIsNone(result.artifact)
            if result.receipt.note is not None:
                self.assertTrue(is_bounded_reason_code(result.receipt.note))


class HwpxEditProjectionTests(unittest.TestCase):
    def test_public_receipt_is_exactly_the_bounded_key_set(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),))
        self.assertEqual(set(result.to_public_dict()), set(RECEIPT_KEYS))

    def test_public_receipt_excludes_the_payload(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),))
        public = result.to_public_dict()
        self.assertNotIn(result.artifact.payload, public.values())
        self.assertNotIn(str(result.artifact.payload), str(public))
        self.assertNotIn(b"PK\x03\x04", str(public).encode("utf-8"))

    def test_public_receipt_excludes_document_text(self) -> None:
        result = hwpx_edit(
            "doc.hwpx", _payload(("원본문서텍스트",)), (_replace(0, 0, "교체문서텍스트"),)
        )
        public = str(result.to_public_dict())
        self.assertNotIn("원본문서텍스트", public)
        self.assertNotIn("교체문서텍스트", public)

    def test_public_receipt_excludes_raw_xml_and_member_names(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),))
        public = str(result.to_public_dict())
        for forbidden in ("<hp:", "hancom.co.kr", "Contents/", "section1.xml", "mimetype"):
            self.assertNotIn(forbidden, public, forbidden)

    def test_public_receipt_excludes_host_paths(self) -> None:
        result = hwpx_edit("C:\\temp\\doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),))
        public = str(result.to_public_dict())
        self.assertNotIn("C:\\", public)
        self.assertNotIn("temp", public)

    def test_public_receipt_key_set_is_identical_on_refusal(self) -> None:
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), ())
        self.assertEqual(set(result.to_public_dict()), set(RECEIPT_KEYS))
        self.assertIsNone(result.to_public_dict()["replacement_count"])


class HwpxEditAuthorityTests(unittest.TestCase):
    def test_capability_id_is_an_existing_reserved_id(self) -> None:
        self.assertIn(CAPABILITY_HWPX_EDIT, RESERVED_CAPABILITY_IDS)
        result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.capability_id, CAPABILITY_HWPX_EDIT)

    def test_edit_reuses_exactly_one_decoder_and_one_serializer(self) -> None:
        payload = _payload(("본문",))
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package", wraps=deserialize_hwpx_package
        ) as decode, mock.patch(
            "kagent.hwpx_skill.serialize_hwpx_package", wraps=serialize_hwpx_package
        ) as encode:
            result = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.status, STATUS_OK)
        # One decode of the source, one decode of the output; one canonical
        # source serialization, one edited serialization. No second authority.
        self.assertEqual(decode.call_count, 2)
        self.assertEqual(encode.call_count, 2)

    def test_edit_path_writes_nothing_to_the_host_filesystem(self) -> None:
        with mock.patch("builtins.open", side_effect=AssertionError("host write attempted")):
            result = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertIsInstance(result.artifact.payload, bytes)

    def test_edit_path_opens_no_network_socket(self) -> None:
        def _forbidden_socket(*args: object, **kwargs: object) -> None:
            raise AssertionError("network access attempted")

        with mock.patch.object(socket, "socket", side_effect=_forbidden_socket):
            result = hwpx_edit("doc.hwpx", _payload(("네트워크",)), (_replace(0, 0, "수정"),))
        self.assertEqual(result.receipt.status, STATUS_OK)

    def test_facade_reaches_core_only_through_accepted_modules(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        imported_core_modules = {
            line.split()[1] for line in source.splitlines() if line.startswith("from padiem_ai_core")
        }
        # #2989 added the accepted #2979 package-preserving mutation authority
        # and #2825 added the accepted single image insertion authority plus the
        # two read-only document_normalization accessors it uses to prove member
        # preservation and picture readback. All three compose accepted Core
        # authorities and none is a parser, decoder or byte producer; no other
        # Core module may.
        self.assertEqual(
            imported_core_modules,
            {
                "padiem_ai_core.document_normalization",
                "padiem_ai_core.document_semantics",
                "padiem_ai_core.hwpx_image_insertion",
                "padiem_ai_core.hwpx_package_mutation",
                "padiem_ai_core.hwpx_package_serializer",
            },
        )

    def test_facade_has_no_second_parser_archive_or_xml_authority(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import zipfile",
            "from zipfile",
            "ZipFile(",
            "writestr(",
            "BytesIO(",
            "xml.etree",
            "ElementTree(",
            "minidom",
            "escape(",
            "_section_xml",
            "_package_bytes",
            "Contents/",
        ):
            self.assertNotIn(forbidden, source, forbidden)

    def test_acceptance_block_matches_issue_2972(self) -> None:
        expected = {
            "HWPX_EDIT_FOUNDATION": "PASS",
            "HWPX_EDIT": "FOUNDATION_ONLY",
            "PARAGRAPH_TEXT_REPLACE": "PASS",
            "CORE_HWPX_DECODER_REUSED": "YES",
            "CORE_HWPX_SERIALIZER_REUSED": "YES",
            "COMMON_FILE_INTAKE_GATE_REUSED": "YES",
            "EXISTING_HWPX_VALIDATE_REUSED": "YES",
            "CAPABILITY_HWPX_EDIT_REUSED": "YES",
            "SOURCE_CANONICAL_BYTE_ROUNDTRIP_REQUIRED": "YES",
            "LOSSY_SOURCE_CANONICALIZATION": "0",
            "UNSUPPORTED_SOURCE_FAILS_CLOSED": "YES",
            "EDIT_SUCCESS_REQUIRES_STRUCTURED_ROUNDTRIP": "YES",
            "NON_TARGET_PARAGRAPHS_PRESERVED": "YES",
            "SECTION_COUNT_PRESERVED": "YES",
            "PARAGRAPH_COUNT_PRESERVED": "YES",
            "PARTIAL_EDIT_OUTPUT": "0",
            "SECOND_HWPX_PARSER_AUTHORITY": "0",
            "SECOND_HWPX_SERIALIZER_AUTHORITY": "0",
            "SECOND_XML_AUTHORITY": "0",
            "SECOND_ARCHIVE_GATE_AUTHORITY": "0",
            "SECOND_SKILL_REGISTRY_AUTHORITY": "0",
        }
        for key, value in expected.items():
            self.assertEqual(hwpx_skill.ACCEPTANCE.get(key), value, key)

    def test_edit_never_claims_a_wider_capability(self) -> None:
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_TEMPLATE_FILL"), "PASS")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_TEMPLATE_FILL_SCOPE"), "BOUNDED_FOUNDATION")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("TABLE_INSERT"), "PASS")
        self.assertEqual(
            hwpx_skill.ACCEPTANCE.get("TABLE_INSERT_SCOPE"),
            "BOUNDED_CANONICAL_BLOCK_SUBSET",
        )
        # #2825 bounded image insertion reuses this same reserved edit
        # capability; it does not widen what paragraph replacement claims.
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("IMAGE_INSERT_UNDER_HWPX_EDIT"), "YES")
        for key in (
            "PARAGRAPH_INSERT",
            "PARAGRAPH_DELETE",
            "SECTION_INSERT",
            "SECTION_DELETE",
            "TABLE_EDIT",
            "TABLE_DELETE",
            "ROW_COLUMN_MUTATION",
            "IMAGE_EDIT",
            "STYLE_EDIT",
            "LAYOUT_FIDELITY",
        ):
            self.assertEqual(hwpx_skill.ACCEPTANCE.get(key), "NOT_CLAIMED", key)
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_FULL_SPEC_SUPPORT"), "NO")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("DOCUMENT_EXPORT_HWPX_ENABLED"), "NO")
        self.assertNotIn(hwpx_skill.ACCEPTANCE.get("HWPX_EDIT"), {"PASS", "YES"})


class HwpxEditReceiptContractTests(unittest.TestCase):
    def test_ok_receipt_cannot_skip_the_structured_roundtrip(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxEditReceipt(
                status=STATUS_OK,
                capability_id=CAPABILITY_HWPX_EDIT,
                reason_code="ok",
                note=None,
                media_type="application/hwp+zip",
                suggested_filename="doc.hwpx",
                byte_size=1,
                section_count=1,
                paragraph_count=1,
                replacement_count=1,
                validation_status="not_run",
            )

    def test_refused_receipt_cannot_claim_a_verified_roundtrip(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxEditReceipt(
                status=STATUS_REFUSED,
                capability_id=CAPABILITY_HWPX_EDIT,
                reason_code=REASON_EDIT_DUPLICATE_TARGET,
                note=None,
                media_type=None,
                suggested_filename=None,
                byte_size=None,
                section_count=None,
                paragraph_count=None,
                replacement_count=None,
                validation_status=VALIDATION_STATUS_EDIT_OK,
            )

    def test_refused_receipt_cannot_carry_artifact_metadata(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxEditReceipt(
                status=STATUS_REFUSED,
                capability_id=CAPABILITY_HWPX_EDIT,
                reason_code=REASON_EDIT_DUPLICATE_TARGET,
                note=None,
                media_type="application/hwp+zip",
                suggested_filename="doc.hwpx",
                byte_size=1,
                section_count=1,
                paragraph_count=1,
                replacement_count=1,
                validation_status="operations_refused",
            )

    def test_ok_receipt_cannot_omit_the_replacement_count(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxEditReceipt(
                status=STATUS_OK,
                capability_id=CAPABILITY_HWPX_EDIT,
                reason_code="ok",
                note=None,
                media_type="application/hwp+zip",
                suggested_filename="doc.hwpx",
                byte_size=1,
                section_count=1,
                paragraph_count=1,
                replacement_count=None,
                validation_status=VALIDATION_STATUS_EDIT_OK,
            )

    def test_edit_receipt_rejects_unbounded_reason_code(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxEditReceipt(
                status=STATUS_REFUSED,
                capability_id=CAPABILITY_HWPX_EDIT,
                reason_code="leak:secret/path",
                note=None,
                media_type=None,
                suggested_filename=None,
                byte_size=None,
                section_count=None,
                paragraph_count=None,
                replacement_count=None,
                validation_status="not_run",
            )

    def test_edit_receipt_rejects_unbounded_note(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxEditReceipt(
                status=STATUS_REFUSED,
                capability_id=CAPABILITY_HWPX_EDIT,
                reason_code=REASON_EDIT_SOURCE_DECODER_REJECTED,
                note="free text leak: C:\\secret\\path",
                media_type=None,
                suggested_filename=None,
                byte_size=None,
                section_count=None,
                paragraph_count=None,
                replacement_count=None,
                validation_status="source_refused",
            )

    def test_edit_receipt_rejects_unbounded_validation_status(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxEditReceipt(
                status=STATUS_REFUSED,
                capability_id=CAPABILITY_HWPX_EDIT,
                reason_code=REASON_EDIT_DUPLICATE_TARGET,
                note=None,
                media_type=None,
                suggested_filename=None,
                byte_size=None,
                section_count=None,
                paragraph_count=None,
                replacement_count=None,
                validation_status="almost_ok",
            )

    def test_ok_result_requires_its_artifact(self) -> None:
        receipt = hwpx_edit("doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),)).receipt
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxEditResult(receipt=receipt)

    def test_refused_result_cannot_carry_an_artifact(self) -> None:
        refused = hwpx_edit("doc.hwpx", _payload(("본문",)), ()).receipt
        ok_artifact = hwpx_edit(
            "doc.hwpx", _payload(("본문",)), (_replace(0, 0, "수정"),)
        ).artifact
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxEditResult(receipt=refused, artifact=ok_artifact)

    def test_operation_shape_documents_zero_based_indexes(self) -> None:
        operation = _replace(0, 0, "수정")
        self.assertEqual(operation.section_index, 0)
        self.assertEqual(operation.paragraph_index, 0)
        self.assertEqual(operation.text, "수정")
        with self.assertRaises(FrozenInstanceError):
            operation.section_index = 1  # type: ignore[misc]


class HwpxEditAuthorityOrderTests(unittest.TestCase):
    """The common gate and the canonical-source proof decide before the request.

    CENTRAL exact-head review found the published order ("common gate always
    first") did not match the executed order: an empty or malformed operation
    request returned before the common intake authority saw the source. These
    tests pin the corrected order so it cannot regress.
    """

    def test_common_gate_is_the_first_authority_call(self) -> None:
        order: list[str] = []
        real_gate = hwpx_skill.inspect_file
        real_decode = hwpx_skill.deserialize_hwpx_package

        def gate(*args: object, **kwargs: object) -> object:
            order.append("inspect_file")
            return real_gate(*args, **kwargs)  # type: ignore[arg-type]

        def decode(*args: object, **kwargs: object) -> object:
            order.append("deserialize_hwpx_package")
            return real_decode(*args, **kwargs)  # type: ignore[arg-type]

        with mock.patch("kagent.hwpx_skill.inspect_file", side_effect=gate), mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package", side_effect=decode
        ):
            result = hwpx_edit("doc.hwpx", _payload(("본문",)), ())

        self.assertEqual(order, ["inspect_file", "deserialize_hwpx_package"])
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OPERATIONS_INVALID)

    def test_empty_operations_do_not_pre_empt_the_common_gate(self) -> None:
        """A gate-refused source plus empty operations must report the gate."""

        payload = _png_bytes()
        with mock.patch("kagent.hwpx_skill.inspect_file", wraps=inspect_file) as gate, mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package", wraps=deserialize_hwpx_package
        ) as decode:
            result = hwpx_edit("doc.hwpx", payload, ())

        # The gate ran; the decoder never did, because the gate refused first.
        self.assertGreaterEqual(gate.call_count, 1)
        self.assertEqual(decode.call_count, 0)
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_GATE_REJECTED)
        self.assertNotEqual(result.receipt.reason_code, REASON_EDIT_OPERATIONS_INVALID)
        self.assertIsNone(result.artifact)

    def test_common_gate_precedes_the_operation_count_bound(self) -> None:
        operations = tuple(
            _replace(0, 0, f"수정{index}") for index in range(MAX_EDIT_OPERATIONS + 1)
        )
        result = hwpx_edit("doc.hwpx", _png_bytes(), operations)
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_GATE_REJECTED)
        self.assertNotEqual(result.receipt.reason_code, REASON_EDIT_OPERATIONS_LIMIT)

    def test_common_gate_precedes_the_operation_shape_check(self) -> None:
        for operations in ((_replace(True, 0, "수정"),), (_replace(0, -1, "수정"),)):
            result = hwpx_edit("doc.hwpx", _png_bytes(), operations)
            self.assertEqual(result.receipt.reason_code, REASON_EDIT_GATE_REJECTED)
            self.assertNotEqual(result.receipt.reason_code, REASON_EDIT_OPERATION_SHAPE)
            self.assertNotEqual(result.receipt.reason_code, REASON_EDIT_INDEX_NEGATIVE)

    def test_common_gate_precedes_a_non_tuple_request(self) -> None:
        result = hwpx_edit("doc.hwpx", _png_bytes(), [_replace(0, 0, "수정")])
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_GATE_REJECTED)

    def test_table_source_canonical_gate_precedes_operation_validation(self) -> None:
        result = hwpx_edit("t.hwpx", _table_source(), ())
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_SOURCE_NOT_CANONICAL)

    def test_canonical_source_gate_precedes_operation_validation(self) -> None:
        """A readable but non-byte-stable source outranks an empty request."""

        result = hwpx_edit("e.hwpx", _extra_member_source(), ())
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_SOURCE_NOT_CANONICAL)
        self.assertNotEqual(result.receipt.reason_code, REASON_EDIT_OPERATIONS_INVALID)

    def test_valid_source_reaches_operation_validation_after_the_source_gates(self) -> None:
        """With a valid source the source gates run, then operations are judged."""

        payload = _payload(("본문",))
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package", wraps=deserialize_hwpx_package
        ) as decode, mock.patch(
            "kagent.hwpx_skill.serialize_hwpx_package", wraps=serialize_hwpx_package
        ) as encode:
            result = hwpx_edit("doc.hwpx", payload, ())

        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OPERATIONS_INVALID)
        # One structured decode and one canonical-source serialization happened
        # before the request container was judged.
        self.assertEqual(decode.call_count, 1)
        self.assertEqual(encode.call_count, 1)

    def test_target_validation_still_follows_the_container_checks(self) -> None:
        """A request that is both malformed and out of range reports the container."""

        payload = _payload(("본문",))
        result = hwpx_edit("doc.hwpx", payload, ())
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_OPERATIONS_INVALID)
        result = hwpx_edit("doc.hwpx", payload, (_replace(0, 9, "수정"),))
        self.assertEqual(result.receipt.reason_code, REASON_EDIT_PARAGRAPH_OUT_OF_RANGE)


class HwpxEditRegressionTests(unittest.TestCase):
    def test_create_surface_still_works(self) -> None:
        """#2962: the create foundation is untouched by this child."""

        result = hwpx_create(_content(("견적서", "합계 1,000원")))
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertIsNotNone(result.artifact)
        # A created package is a valid edit source, so create and edit compose.
        edited = hwpx_edit(
            "created.hwpx", result.artifact.payload, (_replace(0, 0, "세금계산서"),)
        )
        self.assertEqual(edited.receipt.status, STATUS_OK)
        self.assertEqual(
            deserialize_hwpx_package(edited.artifact.payload),
            _content(("세금계산서", "합계 1,000원")),
        )

    def test_edit_output_is_a_valid_edit_source(self) -> None:
        """Two edits compose: the output of one is canonical input to the next."""

        payload = _payload(("A", "B"))
        first = hwpx_edit("doc.hwpx", payload, (_replace(0, 0, "A1"),))
        second = hwpx_edit("doc.hwpx", first.artifact.payload, (_replace(0, 1, "B1"),))
        self.assertEqual(second.receipt.status, STATUS_OK)
        self.assertEqual(
            deserialize_hwpx_package(second.artifact.payload), _content(("A1", "B1"))
        )


if __name__ == "__main__":
    unittest.main()
