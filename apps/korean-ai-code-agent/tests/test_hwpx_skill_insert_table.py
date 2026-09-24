from __future__ import annotations

import socket
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock
from zipfile import ZIP_STORED, ZipFile

from padiem_ai_core.document_semantics import DocumentNormalizationError
from padiem_ai_core.hwpx_package_serializer import (
    MAX_HWPX_CELL_TEXT_CHARS,
    MAX_HWPX_TABLE_COLUMNS,
    MAX_HWPX_TABLE_ROWS,
    HwpxPackageContent,
    HwpxPackageSection,
    HwpxSectionBlock,
    HwpxTable,
    HwpxTableCell,
    deserialize_hwpx_package,
    serialize_hwpx_package,
)

from kagent import hwpx_skill
from kagent.claw_skill_registry import CAPABILITY_HWPX_EDIT, RESERVED_CAPABILITY_IDS
from kagent.document_parser_contract import is_bounded_reason_code
from kagent.file_intake_safety import DetectedFormat, inspect_file
from kagent.hwpx_skill import (
    REASON_INSERT_TABLE_BLOCK_INDEX_NEGATIVE,
    REASON_INSERT_TABLE_BLOCK_OUT_OF_RANGE,
    REASON_INSERT_TABLE_CELL_TEXT_REJECTED,
    REASON_INSERT_TABLE_COLUMN_LIMIT,
    REASON_INSERT_TABLE_GATE_REJECTED,
    REASON_INSERT_TABLE_OUTPUT_COUNT_DRIFT,
    REASON_INSERT_TABLE_OUTPUT_DECODER_REJECTED,
    REASON_INSERT_TABLE_OUTPUT_GATE_REJECTED,
    REASON_INSERT_TABLE_OUTPUT_NON_TARGET_DRIFT,
    REASON_INSERT_TABLE_OUTPUT_READBACK_REJECTED,
    REASON_INSERT_TABLE_OUTPUT_TABLE_MISMATCH,
    REASON_INSERT_TABLE_OUTPUT_VALIDATE_REJECTED,
    REASON_INSERT_TABLE_REQUEST_SHAPE,
    REASON_INSERT_TABLE_ROW_LIMIT,
    REASON_INSERT_TABLE_ROWS_EMPTY,
    REASON_INSERT_TABLE_ROWS_RAGGED,
    REASON_INSERT_TABLE_SECTION_INDEX_NEGATIVE,
    REASON_INSERT_TABLE_SECTION_OUT_OF_RANGE,
    REASON_INSERT_TABLE_SERIALIZER_REJECTED,
    REASON_INSERT_TABLE_SOURCE_DECODER_REJECTED,
    REASON_INSERT_TABLE_SOURCE_NOT_CANONICAL,
    STATUS_OK,
    STATUS_REFUSED,
    VALIDATION_SCOPE_GATE_AND_TEXT,
    VALIDATION_STATUS_INSERT_TABLE_OK,
    HwpxInsertTableReceipt,
    HwpxTableInsertionRequest,
    hwpx_create,
    hwpx_insert_table,
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
        "table_count",
        "inserted_row_count",
        "inserted_column_count",
        "validation_status",
    }
)
SECTION_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/section"
PARAGRAPH_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _paragraph_block(text: str) -> HwpxSectionBlock:
    return HwpxSectionBlock("paragraph", text=text)


def _table(rows: tuple[tuple[str, ...], ...]) -> HwpxTable:
    return HwpxTable(tuple(tuple(HwpxTableCell(text) for text in row) for row in rows))


def _table_block(rows: tuple[tuple[str, ...], ...]) -> HwpxSectionBlock:
    return HwpxSectionBlock("table", table=_table(rows))


def _section(*blocks: HwpxSectionBlock) -> HwpxPackageSection:
    return HwpxPackageSection(
        paragraphs=tuple(block.text for block in blocks if block.kind == "paragraph"),
        blocks=blocks,
    )


def _content(*sections: HwpxPackageSection) -> HwpxPackageContent:
    return HwpxPackageContent(sections=tuple(sections))


def _payload(*sections: HwpxPackageSection) -> bytes:
    return serialize_hwpx_package(_content(*sections))


def _request(
    section_index: int,
    block_index: int,
    rows: object = (("cell",),),
) -> HwpxTableInsertionRequest:
    return HwpxTableInsertionRequest(section_index, block_index, rows)


def _paragraph_xml(text: str = "") -> str:
    return f"<hp:p><hp:runs><hp:t>{text}</hp:t></hp:runs></hp:p>"


def _table_xml(rows: tuple[tuple[str, ...], ...]) -> str:
    body = "".join(
        "<hp:tr>"
        + "".join(f"<hp:tc>{_paragraph_xml(text)}</hp:tc>" for text in row)
        + "</hp:tr>"
        for row in rows
    )
    return f"<hp:tbl>{body}</hp:tbl>"


def _raw_package(body: str) -> bytes:
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hs:sec xmlns:hs="{SECTION_NAMESPACE}" xmlns:hp="{PARAGRAPH_NAMESPACE}">'
        f"{body}</hs:sec>"
    ).encode()
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("Contents/section1.xml", section)
    return buffer.getvalue()


def _extra_member_payload() -> bytes:
    canonical = _payload(_section(_paragraph_block("본문")))
    with ZipFile(BytesIO(canonical)) as archive:
        members = [(info.filename, archive.read(info)) for info in archive.infolist()]
    members.append(("version.xml", b"<version>1</version>"))
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _gate_metadata() -> hwpx_skill.HwpxGateMetadata:
    return hwpx_skill.HwpxGateMetadata.from_gate(
        inspect_file("fake.hwpx", _png_bytes())
    )


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


class HwpxInsertTableSuccessTests(unittest.TestCase):
    def test_1x1_1xn_nx1_and_nxm_shapes_succeed(self) -> None:
        cases = (
            (("한글",),),
            (("한글", "Latin", "123", ""),),
            (("한",), ("둘",), ("셋",)),
            (("한", "둘"), ("셋", "넷"), ("다섯", "여섯")),
        )
        for rows in cases:
            with self.subTest(rows=rows):
                result = hwpx_insert_table(
                    "doc.hwpx",
                    _payload(_section(_paragraph_block("본문"))),
                    _request(0, 0, rows),
                )
                self.assertEqual(result.receipt.status, STATUS_OK)
                self.assertEqual(result.receipt.inserted_row_count, len(rows))
                self.assertEqual(result.receipt.inserted_column_count, len(rows[0]))
                decoded = deserialize_hwpx_package(result.artifact.payload)
                self.assertEqual(decoded.sections[0].blocks[0].table, _table(rows))

    def test_korean_latin_numeric_and_empty_cells_round_trip(self) -> None:
        rows = (("한글", "Latin", "123", ""),)
        result = hwpx_insert_table(
            "doc.hwpx",
            _payload(_section(_paragraph_block("본문"))),
            _request(0, 1, rows),
        )
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(
            tuple(cell.text for cell in decoded.sections[0].blocks[1].table.rows[0]),
            ("한글", "Latin", "123", ""),
        )

    def test_insert_before_between_and_after_paragraphs(self) -> None:
        source = _section(
            _paragraph_block("first"),
            _paragraph_block("middle"),
            _paragraph_block("last"),
        )
        for block_index in (0, 2, 3):
            with self.subTest(block_index=block_index):
                result = hwpx_insert_table(
                    "doc.hwpx", _payload(source), _request(0, block_index)
                )
                self.assertEqual(result.receipt.status, STATUS_OK)
                decoded = deserialize_hwpx_package(result.artifact.payload)
                self.assertEqual(
                    [block.kind for block in decoded.sections[0].blocks],
                    ["table", "paragraph", "paragraph", "paragraph"]
                    if block_index == 0
                    else ["paragraph", "paragraph", "table", "paragraph"]
                    if block_index == 2
                    else ["paragraph", "paragraph", "paragraph", "table"],
                )

    def test_existing_tables_and_inserted_table_keep_exact_order(self) -> None:
        source = _section(
            _paragraph_block("before"),
            _table_block((("old-a",),)),
            _table_block((("old-b",),)),
            _paragraph_block("after"),
        )
        result = hwpx_insert_table(
            "doc.hwpx", _payload(source), _request(0, 2, (("new",),))
        )
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(
            [block.kind for block in decoded.sections[0].blocks],
            ["paragraph", "table", "table", "table", "paragraph"],
        )
        self.assertEqual(decoded.sections[0].blocks[1].table, _table((("old-a",),)))
        self.assertEqual(decoded.sections[0].blocks[2].table, _table((("new",),)))
        self.assertEqual(decoded.sections[0].blocks[3].table, _table((("old-b",),)))

    def test_second_section_address_is_exact(self) -> None:
        source = _content(
            _section(_paragraph_block("first-section")),
            _section(_paragraph_block("second-a"), _paragraph_block("second-b")),
        )
        result = hwpx_insert_table(
            "doc.hwpx", serialize_hwpx_package(source), _request(1, 1, (("target",),))
        )
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("first-section",))
        self.assertEqual(
            [block.kind for block in decoded.sections[1].blocks],
            ["paragraph", "table", "paragraph"],
        )

    def test_output_reenters_gate_validate_read_and_decoder(self) -> None:
        result = hwpx_insert_table(
            "doc.hwpx", _payload(_section(_paragraph_block("본문"))), _request(0, 0)
        )
        payload = result.artifact.payload
        self.assertEqual(
            inspect_file("out.hwpx", payload).detected_format,
            DetectedFormat.HWPX_CANDIDATE,
        )
        self.assertEqual(
            hwpx_skill.hwpx_validate("out.hwpx", payload).status, STATUS_OK
        )
        self.assertEqual(hwpx_skill.hwpx_read("out.hwpx", payload).status, STATUS_OK)
        self.assertEqual(
            deserialize_hwpx_package(payload).sections[0].blocks[0].table,
            _table((("cell",),)),
        )

    def test_same_request_is_deterministic(self) -> None:
        payload = _payload(_section(_paragraph_block("본문")))
        first = hwpx_insert_table(
            "doc.hwpx", payload, _request(0, 0, (("가", "A"), ("1", "")))
        )
        second = hwpx_insert_table(
            "doc.hwpx", payload, _request(0, 0, [["가", "A"], ["1", ""]])
        )
        self.assertEqual(first.artifact.payload, second.artifact.payload)
        self.assertEqual(
            first.receipt.to_public_dict(), second.receipt.to_public_dict()
        )

    def test_create_output_is_a_valid_insert_table_source(self) -> None:
        created = hwpx_create
        content = _content(_section(_paragraph_block("생성")))
        result = hwpx_insert_table(
            "created.hwpx", created(content).artifact.payload, _request(0, 1)
        )
        self.assertEqual(result.receipt.status, STATUS_OK)


class HwpxInsertTableRequestRefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = _payload(
            _section(_paragraph_block("본문"), _paragraph_block("둘째"))
        )

    def test_foreign_request_and_non_integer_or_bool_indexes_are_refused(self) -> None:
        requests = (
            (0, 0),
            HwpxTableInsertionRequest("0", 0, (("cell",),)),
            HwpxTableInsertionRequest(True, 0, (("cell",),)),
            HwpxTableInsertionRequest(0, False, (("cell",),)),
        )
        for request in requests:
            with self.subTest(request=request):
                result = hwpx_insert_table("doc.hwpx", self.payload, request)
                self.assertEqual(
                    result.receipt.reason_code, REASON_INSERT_TABLE_REQUEST_SHAPE
                )
                self.assertIsNone(result.artifact)

    def test_negative_section_and_block_indexes_are_refused(self) -> None:
        section_result = hwpx_insert_table("doc.hwpx", self.payload, _request(-1, 0))
        block_result = hwpx_insert_table("doc.hwpx", self.payload, _request(0, -1))
        self.assertEqual(
            section_result.receipt.reason_code,
            REASON_INSERT_TABLE_SECTION_INDEX_NEGATIVE,
        )
        self.assertEqual(
            block_result.receipt.reason_code,
            REASON_INSERT_TABLE_BLOCK_INDEX_NEGATIVE,
        )

    def test_section_and_block_bounds_are_exact(self) -> None:
        section = hwpx_insert_table("doc.hwpx", self.payload, _request(1, 0))
        block = hwpx_insert_table("doc.hwpx", self.payload, _request(0, 3))
        self.assertEqual(
            section.receipt.reason_code, REASON_INSERT_TABLE_SECTION_OUT_OF_RANGE
        )
        self.assertEqual(
            block.receipt.reason_code, REASON_INSERT_TABLE_BLOCK_OUT_OF_RANGE
        )
        self.assertIsNone(section.artifact)
        self.assertIsNone(block.artifact)

    def test_empty_table_and_invalid_row_containers_are_refused(self) -> None:
        for rows in ((), [], "cell", (("cell",), 1)):
            with self.subTest(rows=rows):
                result = hwpx_insert_table(
                    "doc.hwpx", self.payload, _request(0, 0, rows)
                )
                expected = (
                    REASON_INSERT_TABLE_ROWS_EMPTY
                    if rows in ((), [])
                    else REASON_INSERT_TABLE_REQUEST_SHAPE
                )
                self.assertEqual(result.receipt.reason_code, expected)
                self.assertIsNone(result.artifact)

    def test_ragged_rows_are_refused(self) -> None:
        result = hwpx_insert_table(
            "doc.hwpx", self.payload, _request(0, 0, (("a",), ("b", "c")))
        )
        self.assertEqual(result.receipt.reason_code, REASON_INSERT_TABLE_ROWS_RAGGED)
        self.assertIsNone(result.artifact)

    def test_row_and_column_overflow_are_refused(self) -> None:
        row_overflow = tuple(("x",) for _ in range(MAX_HWPX_TABLE_ROWS + 1))
        column_overflow = (tuple("x" for _ in range(MAX_HWPX_TABLE_COLUMNS + 1)),)
        self.assertEqual(
            hwpx_insert_table(
                "doc.hwpx", self.payload, _request(0, 0, row_overflow)
            ).receipt.reason_code,
            REASON_INSERT_TABLE_ROW_LIMIT,
        )
        self.assertEqual(
            hwpx_insert_table(
                "doc.hwpx", self.payload, _request(0, 0, column_overflow)
            ).receipt.reason_code,
            REASON_INSERT_TABLE_COLUMN_LIMIT,
        )

    def test_cell_text_overflow_and_control_characters_are_refused(self) -> None:
        overflow = (("x" * (MAX_HWPX_CELL_TEXT_CHARS + 1),),)
        control = (("bad\x00text",),)
        for rows in (overflow, control):
            with self.subTest(rows=rows):
                result = hwpx_insert_table(
                    "doc.hwpx", self.payload, _request(0, 0, rows)
                )
                self.assertEqual(
                    result.receipt.reason_code,
                    REASON_INSERT_TABLE_CELL_TEXT_REJECTED,
                )
                self.assertIsNone(result.artifact)

    def test_package_cell_count_overflow_is_refused_by_core_serializer(self) -> None:
        maximum = _table(
            tuple(
                tuple("x" for _ in range(MAX_HWPX_TABLE_COLUMNS))
                for _ in range(MAX_HWPX_TABLE_ROWS)
            )
        )
        source = _payload(_section(HwpxSectionBlock("table", table=maximum)))
        result = hwpx_insert_table("doc.hwpx", source, _request(0, 1))
        self.assertEqual(
            result.receipt.reason_code, REASON_INSERT_TABLE_SERIALIZER_REJECTED
        )
        self.assertEqual(result.receipt.note, "hwpx_serialize_table_cell_limit")


class HwpxInsertTableSourceRefusalTests(unittest.TestCase):
    def test_common_gate_failure_precedes_request_validation(self) -> None:
        result = hwpx_insert_table("fake.hwpx", _png_bytes(), (0, 0))
        self.assertEqual(result.receipt.reason_code, REASON_INSERT_TABLE_GATE_REJECTED)
        self.assertIsNone(result.artifact)

    def test_nested_merged_drawing_image_and_shape_sources_are_refused(self) -> None:
        nested = (
            "<hp:tbl><hp:tr><hp:tc>"
            "<hp:tbl><hp:tr><hp:tc>"
            + _paragraph_xml("inner")
            + "</hp:tc></hp:tr></hp:tbl>"
            "</hp:tc></hp:tr></hp:tbl>"
        )
        merged = (
            '<hp:tbl><hp:tr><hp:tc colSpan="2">'
            + _paragraph_xml("merged")
            + "</hp:tc></hp:tr></hp:tbl>"
        )
        drawing = _table_xml((("",),)).replace(
            _paragraph_xml(""), "<hp:p><hp:runs><hp:drawing/></hp:runs></hp:p>"
        )
        image = '<hp:p><hp:runs><hp:img href="rId1"/></hp:runs></hp:p>'
        shape = "<hp:p><hp:runs><hp:gm><hp:pts/></hp:gm></hp:runs></hp:p>"
        for body in (nested, merged, drawing, image, shape):
            with self.subTest(body=body):
                payload = _raw_package(body)
                self.assertEqual(
                    inspect_file("source.hwpx", payload).detected_format,
                    DetectedFormat.HWPX_CANDIDATE,
                )
                result = hwpx_insert_table("source.hwpx", payload, _request(0, 0))
                self.assertEqual(
                    result.receipt.reason_code,
                    REASON_INSERT_TABLE_SOURCE_DECODER_REJECTED,
                )
                self.assertEqual(result.receipt.note, "hwpx_unsupported_structure")
                self.assertIsNone(result.artifact)

    def test_noncanonical_source_is_refused_before_request_validation(self) -> None:
        payload = _extra_member_payload()
        self.assertNotEqual(
            serialize_hwpx_package(deserialize_hwpx_package(payload)), payload
        )
        result = hwpx_insert_table("source.hwpx", payload, (0, 0))
        self.assertEqual(
            result.receipt.reason_code, REASON_INSERT_TABLE_SOURCE_NOT_CANONICAL
        )
        self.assertIsNone(result.artifact)

    def test_decoder_exception_is_projected_as_a_bounded_refusal(self) -> None:
        payload = _payload(_section(_paragraph_block("본문")))
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package",
            side_effect=DocumentNormalizationError("hwpx_unsupported_structure", "x"),
        ):
            result = hwpx_insert_table("doc.hwpx", payload, _request(0, 0))
        self.assertEqual(
            result.receipt.reason_code, REASON_INSERT_TABLE_SOURCE_DECODER_REJECTED
        )
        self.assertEqual(result.receipt.note, "hwpx_unsupported_structure")


class HwpxInsertTableOutputRefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = _payload(
            _section(_paragraph_block("before"), _paragraph_block("after"))
        )

    def test_serializer_refusal_produces_no_artifact(self) -> None:
        with mock.patch(
            "kagent.hwpx_skill.serialize_hwpx_package",
            side_effect=[
                self.payload,
                DocumentNormalizationError("hwpx_serialize_model", "x"),
            ],
        ):
            result = hwpx_insert_table("doc.hwpx", self.payload, _request(0, 1))
        self.assertEqual(
            result.receipt.reason_code, REASON_INSERT_TABLE_SERIALIZER_REJECTED
        )
        self.assertIsNone(result.artifact)

    def test_output_gate_validate_read_and_decoder_failures_produce_no_artifact(
        self,
    ) -> None:
        denied = inspect_file("fake.hwpx", _png_bytes())
        with mock.patch(
            "kagent.hwpx_skill.inspect_file",
            side_effect=[inspect_file("doc.hwpx", self.payload), denied],
        ):
            gate = hwpx_insert_table("doc.hwpx", self.payload, _request(0, 1))
        self.assertEqual(
            gate.receipt.reason_code, REASON_INSERT_TABLE_OUTPUT_GATE_REJECTED
        )

        with mock.patch(
            "kagent.hwpx_skill.hwpx_validate", return_value=_refused_validate_receipt()
        ):
            validation = hwpx_insert_table("doc.hwpx", self.payload, _request(0, 1))
        self.assertEqual(
            validation.receipt.reason_code,
            REASON_INSERT_TABLE_OUTPUT_VALIDATE_REJECTED,
        )

        with (
            mock.patch(
                "kagent.hwpx_skill.hwpx_validate", return_value=_ok_validate_receipt()
            ),
            mock.patch(
                "kagent.hwpx_skill.hwpx_read", return_value=_refused_read_receipt()
            ),
        ):
            readback = hwpx_insert_table("doc.hwpx", self.payload, _request(0, 1))
        self.assertEqual(
            readback.receipt.reason_code, REASON_INSERT_TABLE_OUTPUT_READBACK_REJECTED
        )

        source = deserialize_hwpx_package(self.payload)
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package",
            side_effect=[
                source,
                DocumentNormalizationError("hwpx_unsupported_structure", "x"),
            ],
        ):
            decoder = hwpx_insert_table("doc.hwpx", self.payload, _request(0, 1))
        self.assertEqual(
            decoder.receipt.reason_code, REASON_INSERT_TABLE_OUTPUT_DECODER_REJECTED
        )
        for result in (gate, validation, readback, decoder):
            self.assertIsNone(result.artifact)

    def test_inserted_table_mismatch_is_refused(self) -> None:
        source = deserialize_hwpx_package(self.payload)
        mismatched = _content(
            _section(
                _paragraph_block("before"),
                _table_block((("wrong",),)),
                _paragraph_block("after"),
            )
        )
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package",
            side_effect=[source, mismatched],
        ):
            result = hwpx_insert_table("doc.hwpx", self.payload, _request(0, 1))
        self.assertEqual(
            result.receipt.reason_code, REASON_INSERT_TABLE_OUTPUT_TABLE_MISMATCH
        )
        self.assertIsNone(result.artifact)

    def test_non_target_block_drift_is_refused(self) -> None:
        source = deserialize_hwpx_package(self.payload)
        drifted = _content(
            _section(
                _paragraph_block("drifted"),
                _table_block((("cell",),)),
                _paragraph_block("after"),
            )
        )
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package", side_effect=[source, drifted]
        ):
            result = hwpx_insert_table("doc.hwpx", self.payload, _request(0, 1))
        self.assertEqual(
            result.receipt.reason_code, REASON_INSERT_TABLE_OUTPUT_NON_TARGET_DRIFT
        )
        self.assertIsNone(result.artifact)

    def test_block_count_drift_is_refused(self) -> None:
        source = deserialize_hwpx_package(self.payload)
        drifted = _content(
            _section(_paragraph_block("before"), _paragraph_block("after"))
        )
        with mock.patch(
            "kagent.hwpx_skill.deserialize_hwpx_package", side_effect=[source, drifted]
        ):
            result = hwpx_insert_table("doc.hwpx", self.payload, _request(0, 1))
        self.assertEqual(
            result.receipt.reason_code, REASON_INSERT_TABLE_OUTPUT_COUNT_DRIFT
        )
        self.assertIsNone(result.artifact)


class HwpxInsertTableProjectionAndAuthorityTests(unittest.TestCase):
    def test_capability_reuses_existing_hwpx_edit_id(self) -> None:
        self.assertIn(CAPABILITY_HWPX_EDIT, RESERVED_CAPABILITY_IDS)
        result = hwpx_insert_table(
            "doc.hwpx", _payload(_section(_paragraph_block("본문"))), _request(0, 0)
        )
        self.assertEqual(result.receipt.capability_id, CAPABILITY_HWPX_EDIT)

    def test_public_receipt_has_bounded_keys_and_excludes_content(self) -> None:
        result = hwpx_insert_table(
            "C:\\secret\\doc.hwpx",
            _payload(_section(_paragraph_block("보존문단"))),
            _request(0, 0, (("비밀셀",),)),
        )
        public = result.to_public_dict()
        self.assertEqual(set(public), set(RECEIPT_KEYS))
        projection = str(public)
        for forbidden in (
            "비밀셀",
            "보존문단",
            "C:\\",
            "secret",
            "<hp:",
            "Contents/",
            "mimetype",
        ):
            self.assertNotIn(forbidden, projection, forbidden)

    def test_refusal_reasons_and_notes_are_bounded(self) -> None:
        payload = _payload(_section(_paragraph_block("본문")))
        for request in (
            _request(-1, 0),
            _request(0, -1),
            _request(0, 0, ()),
            _request(0, 0, (("a",), ("b", "c"))),
        ):
            result = hwpx_insert_table("doc.hwpx", payload, request)
            self.assertEqual(result.receipt.status, STATUS_REFUSED)
            self.assertTrue(is_bounded_reason_code(result.receipt.reason_code))
            if result.receipt.note is not None:
                self.assertTrue(is_bounded_reason_code(result.receipt.note))

    def test_facade_uses_one_decoder_and_one_serializer(self) -> None:
        payload = _payload(_section(_paragraph_block("본문")))
        with (
            mock.patch(
                "kagent.hwpx_skill.deserialize_hwpx_package",
                wraps=deserialize_hwpx_package,
            ) as decoder,
            mock.patch(
                "kagent.hwpx_skill.serialize_hwpx_package", wraps=serialize_hwpx_package
            ) as serializer,
        ):
            result = hwpx_insert_table("doc.hwpx", payload, _request(0, 0))
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(decoder.call_count, 2)
        self.assertEqual(serializer.call_count, 2)

    def test_facade_has_no_second_parser_xml_archive_or_registry_authority(
        self,
    ) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        imported_core_modules = {
            line.split()[1]
            for line in source.splitlines()
            if line.startswith("from padiem_ai_core")
        }
        self.assertEqual(
            imported_core_modules,
            {
                "padiem_ai_core.document_semantics",
                "padiem_ai_core.hwpx_package_mutation",
                "padiem_ai_core.hwpx_package_serializer",
            },
        )
        for forbidden in (
            "import zipfile",
            "from zipfile",
            "ZipFile(",
            "writestr(",
            "BytesIO(",
            "xml.etree",
            "ElementTree(",
            "minidom",
            "_package_bytes",
            "Contents/",
        ):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertFalse(hasattr(hwpx_skill, "CAPABILITY_HWPX_INSERT_TABLE"))

    def test_insert_table_writes_no_host_file_and_opens_no_socket(self) -> None:
        payload = _payload(_section(_paragraph_block("본문")))
        with mock.patch(
            "builtins.open", side_effect=AssertionError("host write attempted")
        ):
            result = hwpx_insert_table("doc.hwpx", payload, _request(0, 0))
        self.assertEqual(result.receipt.status, STATUS_OK)
        with mock.patch.object(
            socket, "socket", side_effect=AssertionError("network attempted")
        ):
            result = hwpx_insert_table("doc.hwpx", payload, _request(0, 0))
        self.assertEqual(result.receipt.status, STATUS_OK)

    def test_ok_receipt_requires_exact_shape_metadata(self) -> None:
        with self.assertRaises(ValueError):
            HwpxInsertTableReceipt(
                status=STATUS_OK,
                capability_id=CAPABILITY_HWPX_EDIT,
                reason_code="ok",
                note=None,
                media_type="application/hwp+zip",
                suggested_filename="doc.hwpx",
                byte_size=1,
                section_count=1,
                paragraph_count=0,
                table_count=1,
                inserted_row_count=1,
                inserted_column_count=0,
                validation_status=VALIDATION_STATUS_INSERT_TABLE_OK,
            )


if __name__ == "__main__":
    unittest.main()
