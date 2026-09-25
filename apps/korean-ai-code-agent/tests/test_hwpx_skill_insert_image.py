"""#2825 bounded ``hwpx.insert_image`` KAgent facade.

The tests pin the facade, not the Core authority: admission order, the bounded
request contract, the readback/preservation proof, the public projection's
absence of image bytes, and the claim that no second parser, decoder, archive
writer, host write or network call was introduced here.
"""

from __future__ import annotations

import socket
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

from PIL import Image

from kagent import hwpx_skill
from kagent.claw_skill_registry import CAPABILITY_HWPX_EDIT, RESERVED_CAPABILITY_IDS
from kagent.document_parser_contract import is_bounded_reason_code
from kagent.file_intake_safety import DetectedFormat, inspect_file
from kagent.hwpx_skill import (
    MAX_INSERT_IMAGE_BYTES,
    REASON_INSERT_IMAGE_EXTENT_TYPE,
    REASON_INSERT_IMAGE_GATE_REJECTED,
    REASON_INSERT_IMAGE_IMAGE_BYTES_INVALID,
    REASON_INSERT_IMAGE_IMAGE_BYTES_LIMIT,
    REASON_INSERT_IMAGE_OUTPUT_GATE_REJECTED,
    REASON_INSERT_IMAGE_OUTPUT_NON_TARGET_DRIFT,
    REASON_INSERT_IMAGE_OUTPUT_PICTURE_MISMATCH,
    REASON_INSERT_IMAGE_OUTPUT_READBACK_REJECTED,
    REASON_INSERT_IMAGE_OUTPUT_VALIDATE_REJECTED,
    REASON_INSERT_IMAGE_REQUEST_SHAPE,
    REASON_INSERT_IMAGE_SECTION_INDEX_NEGATIVE,
    REASON_INSERT_IMAGE_SOURCE_REJECTED,
    STATUS_OK,
    STATUS_REFUSED,
    VALIDATION_STATUS_INSERT_IMAGE_OK,
    HwpxImageInsertionRequest,
    HwpxInsertImageReceipt,
    hwpx_insert_image,
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
        "picture_count",
        "inserted_image_count",
        "binary_item_id_ref",
        "image_media_type",
        "image_source_format",
        "image_bytes",
        "image_width_hwpunit",
        "image_height_hwpunit",
        "image_width_px",
        "image_height_px",
        "validation_status",
    }
)
SECTION_NS = "http://www.hancom.co.kr/hwpml/2011/section"
PARAGRAPH_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
CORE_NS = "http://www.hancom.co.kr/hwpml/2011/core"
OPF_NS = "http://www.idpf.org/2007/opf/"
DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'


def _png(width: int = 24, height: int = 16) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(width: int = 24, height: int = 16) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 30, 40)).save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def _webp() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (5, 5, 5)).save(buffer, format="WEBP")
    return buffer.getvalue()


def _section_part(text: str) -> bytes:
    body = (
        '<hp:p id="2764991984" paraPrIDRef="3" styleIDRef="0" pageBreak="0">'
        f'<hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run>'
        '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000"'
        ' textheight="1000" baseline="850" horzpos="0" horzsize="42520" flags="393216"/>'
        "</hp:linesegarray></hp:p>"
    )
    document = (
        f'{DECLARATION}<hs:sec xmlns:hs="{SECTION_NS}" xmlns:hp="{PARAGRAPH_NS}"'
        f' xmlns:hc="{CORE_NS}" version="1.4">{body}</hs:sec>'
    )
    return document.encode("utf-8")


def _manifest() -> bytes:
    manifest = (
        f'{DECLARATION}<opf:package xmlns:opf="{OPF_NS}" version="" id="">'
        "<opf:metadata><opf:title/><opf:language>ko</opf:language></opf:metadata>"
        "<opf:manifest>"
        '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
        "</opf:manifest>"
        '<opf:spine><opf:itemref idref="header" linear="yes"/>'
        '<opf:itemref idref="section0" linear="yes"/></opf:spine>'
        "</opf:package>"
    )
    return manifest.encode("utf-8")


def _archive(members: list[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _template(*, sections: int = 1, manifest: bytes | None = None) -> bytes:
    members: list[tuple[str, bytes]] = [
        ("mimetype", b"application/hwp+zip"),
        ("version.xml", b"<version>1</version>"),
    ]
    for index in range(sections):
        members.append((f"Contents/section{index}.xml", _section_part(f"본문 {index}")))
    members += [
        ("Contents/content.hpf", _manifest() if manifest is None else manifest),
        ("META-INF/container.xml", b"<container/>"),
        ("Unrelated/opaque.bin", b"\x00\x01opaque\xff"),
    ]
    return _archive(members)


def _request(image: bytes | None = None, **kwargs) -> HwpxImageInsertionRequest:
    return HwpxImageInsertionRequest(
        section_index=kwargs.pop("section_index", 0),
        image=_png() if image is None else image,
        **kwargs,
    )


def _fake_png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class HwpxInsertImageSuccessTests(unittest.TestCase):
    def test_png_insert_succeeds_and_reports_bounded_geometry(self) -> None:
        result = hwpx_insert_image("doc.hwpx", _template(), _request())
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(result.receipt.reason_code, "ok")
        self.assertIsNone(result.receipt.note)
        self.assertEqual(result.receipt.validation_status, VALIDATION_STATUS_INSERT_IMAGE_OK)
        self.assertEqual(result.receipt.binary_item_id_ref, "BIN0001")
        self.assertEqual(result.receipt.image_media_type, "image/png")
        self.assertEqual(result.receipt.image_source_format, "PNG")
        self.assertEqual(result.receipt.image_width_px, 24)
        self.assertEqual(result.receipt.image_height_px, 16)
        self.assertEqual(result.receipt.inserted_image_count, 1)
        self.assertEqual(result.receipt.picture_count, 1)
        self.assertIsInstance(result.artifact, hwpx_skill.HwpxInsertImageArtifact)

    def test_explicit_and_derived_draw_extents_are_honoured(self) -> None:
        derived = hwpx_insert_image("doc.hwpx", _template(), _request())
        # No extent supplied: Core derives the draw size from the pixel geometry.
        self.assertEqual(derived.receipt.image_width_hwpunit, 24 * 75)
        self.assertEqual(derived.receipt.image_height_hwpunit, 16 * 75)

        both = hwpx_insert_image(
            "doc.hwpx", _template(), _request(width_hwpunit=7200, height_hwpunit=4800)
        )
        self.assertEqual(both.receipt.status, STATUS_OK)
        self.assertEqual(both.receipt.image_width_hwpunit, 7200)
        self.assertEqual(both.receipt.image_height_hwpunit, 4800)

        one_axis = hwpx_insert_image("doc.hwpx", _template(), _request(width_hwpunit=7200))
        self.assertEqual(one_axis.receipt.status, STATUS_OK)
        self.assertEqual(one_axis.receipt.image_width_hwpunit, 7200)
        self.assertEqual(one_axis.receipt.image_height_hwpunit, 4800)

    def test_jpeg_input_is_reported_as_jpeg_in_and_png_out(self) -> None:
        result = hwpx_insert_image("doc.hwpx", _template(), _request(_jpeg()))
        self.assertEqual(result.receipt.status, STATUS_OK)
        # The conversion is visible rather than silent.
        self.assertEqual(result.receipt.image_source_format, "JPEG")
        self.assertEqual(result.receipt.image_media_type, "image/png")

    def test_second_section_address_is_exact(self) -> None:
        result = hwpx_insert_image(
            "doc.hwpx", _template(sections=2), _request(section_index=1)
        )
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(result.receipt.section_count, 2)
        self.assertEqual(result.receipt.picture_count, 1)

    def test_output_reenters_the_accepted_authorities(self) -> None:
        result = hwpx_insert_image("doc.hwpx", _template(), _request())
        payload = result.artifact.payload
        self.assertEqual(
            inspect_file("out.hwpx", payload).detected_format,
            DetectedFormat.HWPX_CANDIDATE,
        )
        self.assertEqual(hwpx_skill.hwpx_validate("out.hwpx", payload).status, STATUS_OK)
        self.assertEqual(hwpx_skill.hwpx_read("out.hwpx", payload).status, STATUS_OK)

    def test_paragraph_text_and_unrelated_members_survive(self) -> None:
        result = hwpx_insert_image("doc.hwpx", _template(), _request())
        self.assertEqual(result.receipt.paragraph_count, 1)
        self.assertEqual(
            hwpx_skill.hwpx_read("out.hwpx", result.artifact.payload).text, "본문 0"
        )
        with ZipFile(BytesIO(result.artifact.payload)) as archive:
            self.assertEqual(archive.read("Unrelated/opaque.bin"), b"\x00\x01opaque\xff")
            self.assertEqual(archive.read("version.xml"), b"<version>1</version>")

    def test_same_request_is_deterministic(self) -> None:
        template = _template()
        first = hwpx_insert_image("doc.hwpx", template, _request())
        second = hwpx_insert_image("doc.hwpx", template, _request())
        self.assertEqual(first.artifact.payload, second.artifact.payload)
        self.assertEqual(first.to_public_dict(), second.to_public_dict())


class HwpxInsertImageRequestRefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = _template()

    def test_foreign_request_and_non_integer_or_bool_section_index_are_refused(self) -> None:
        requests = (
            (0, _png()),
            HwpxImageInsertionRequest("0", _png()),
            HwpxImageInsertionRequest(True, _png()),
        )
        for request in requests:
            with self.subTest(request=request):
                result = hwpx_insert_image("doc.hwpx", self.payload, request)
                self.assertEqual(result.receipt.reason_code, REASON_INSERT_IMAGE_REQUEST_SHAPE)
                self.assertIsNone(result.artifact)

    def test_negative_section_index_is_refused(self) -> None:
        result = hwpx_insert_image("doc.hwpx", self.payload, _request(section_index=-1))
        self.assertEqual(
            result.receipt.reason_code, REASON_INSERT_IMAGE_SECTION_INDEX_NEGATIVE
        )
        self.assertIsNone(result.artifact)

    def test_non_integer_or_bool_draw_extent_is_refused(self) -> None:
        for width, height in (("7200", None), (True, None), (None, 4800.0)):
            with self.subTest(width=width, height=height):
                result = hwpx_insert_image(
                    "doc.hwpx",
                    self.payload,
                    HwpxImageInsertionRequest(0, _png(), width, height),
                )
                self.assertEqual(result.receipt.reason_code, REASON_INSERT_IMAGE_EXTENT_TYPE)
                self.assertIsNone(result.artifact)

    def test_empty_and_non_bytes_image_payloads_are_refused(self) -> None:
        for image in (b"", "not-bytes", None, 42):
            with self.subTest(image=image):
                result = hwpx_insert_image(
                    "doc.hwpx", self.payload, HwpxImageInsertionRequest(0, image)
                )
                self.assertEqual(
                    result.receipt.reason_code, REASON_INSERT_IMAGE_IMAGE_BYTES_INVALID
                )
                self.assertIsNone(result.artifact)

    def test_oversized_image_is_refused_before_core_is_reached(self) -> None:
        request = HwpxImageInsertionRequest(0, b"\x89PNG\r\n\x1a\n" + b"\x00" * MAX_INSERT_IMAGE_BYTES)
        with mock.patch(
            "kagent.hwpx_skill.insert_hwpx_image", side_effect=AssertionError("core reached")
        ) as core:
            result = hwpx_insert_image("doc.hwpx", self.payload, request)
        self.assertEqual(result.receipt.reason_code, REASON_INSERT_IMAGE_IMAGE_BYTES_LIMIT)
        self.assertIsNone(result.artifact)
        self.assertFalse(core.called)

    def test_section_index_past_the_package_is_refused(self) -> None:
        result = hwpx_insert_image("doc.hwpx", self.payload, _request(section_index=5))
        self.assertEqual(result.receipt.reason_code, REASON_INSERT_IMAGE_SOURCE_REJECTED)
        self.assertEqual(result.receipt.note, "hwpx_image_section_missing")
        self.assertIsNone(result.artifact)


class HwpxInsertImageSourceRefusalTests(unittest.TestCase):
    def test_common_gate_failure_precedes_request_validation(self) -> None:
        result = hwpx_insert_image("fake.hwpx", _fake_png_bytes(), (0, _png()))
        self.assertEqual(result.receipt.reason_code, REASON_INSERT_IMAGE_GATE_REJECTED)
        self.assertIsNone(result.artifact)

    def test_package_without_a_manifest_is_refused_by_the_core_authority(self) -> None:
        # A package this Core created from scratch carries no content.hpf, so it
        # is outside the insertable subset and is refused rather than given a
        # manifest this facade has no authority to invent.
        from padiem_ai_core.hwpx_package_serializer import (
            HwpxPackageContent,
            HwpxPackageSection,
            serialize_hwpx_package,
        )

        payload = serialize_hwpx_package(
            HwpxPackageContent(sections=(HwpxPackageSection(paragraphs=("본문",)),))
        )
        result = hwpx_insert_image("doc.hwpx", payload, _request())
        self.assertEqual(result.receipt.reason_code, REASON_INSERT_IMAGE_SOURCE_REJECTED)
        self.assertEqual(result.receipt.note, "hwpx_image_manifest_missing")
        self.assertIsNone(result.artifact)

    def test_unsupported_image_format_is_refused_with_the_core_code(self) -> None:
        result = hwpx_insert_image("doc.hwpx", _template(), _request(_webp()))
        self.assertEqual(result.receipt.reason_code, REASON_INSERT_IMAGE_SOURCE_REJECTED)
        self.assertEqual(result.receipt.note, "hwpx_image_format_unsupported")
        self.assertIsNone(result.artifact)

    def test_malformed_image_is_refused_with_a_core_image_code(self) -> None:
        result = hwpx_insert_image(
            "doc.hwpx", _template(), _request(b"\x89PNG\r\n\x1a\n truncated")
        )
        self.assertEqual(result.receipt.reason_code, REASON_INSERT_IMAGE_SOURCE_REJECTED)
        self.assertIn(
            result.receipt.note, {"image_decode_failed", "image_bytes_invalid"}
        )
        self.assertIsNone(result.artifact)

    def test_core_refusals_are_reported_as_bounded_codes_only(self) -> None:
        for image in (_webp(), b"\x89PNG\r\n\x1a\n truncated", b"not-an-image"):
            with self.subTest(image=image[:16]):
                result = hwpx_insert_image("doc.hwpx", _template(), _request(image))
                self.assertEqual(result.receipt.status, STATUS_REFUSED)
                self.assertEqual(
                    result.receipt.reason_code, REASON_INSERT_IMAGE_SOURCE_REJECTED
                )
                self.assertTrue(is_bounded_reason_code(result.receipt.reason_code))
                if result.receipt.note is not None:
                    self.assertTrue(is_bounded_reason_code(result.receipt.note))


class HwpxInsertImageOutputRefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = _template()

    def test_output_gate_validate_and_read_failures_produce_no_artifact(self) -> None:
        denied = inspect_file("fake.hwpx", _fake_png_bytes())
        with mock.patch(
            "kagent.hwpx_skill.inspect_file",
            side_effect=[inspect_file("doc.hwpx", self.payload), denied],
        ):
            gate = hwpx_insert_image("doc.hwpx", self.payload, _request())
        self.assertEqual(
            gate.receipt.reason_code, REASON_INSERT_IMAGE_OUTPUT_GATE_REJECTED
        )

        refused_validation = hwpx_skill.HwpxValidateReceipt(
            status=STATUS_REFUSED,
            capability_id="hwpx.validate",
            reason_code="hwpx_mimetype_mismatch",
            note=None,
            scope=hwpx_skill.VALIDATION_SCOPE_GATE_AND_TEXT,
            full_spec_support_claimed=False,
            text_present=False,
            gate=hwpx_skill.HwpxGateMetadata.from_gate(
                inspect_file("fake.hwpx", _fake_png_bytes())
            ),
        )
        with mock.patch(
            "kagent.hwpx_skill.hwpx_validate", return_value=refused_validation
        ):
            validation = hwpx_insert_image("doc.hwpx", self.payload, _request())
        self.assertEqual(
            validation.receipt.reason_code, REASON_INSERT_IMAGE_OUTPUT_VALIDATE_REJECTED
        )

        refused_read = hwpx_skill.HwpxReadReceipt(
            status=STATUS_REFUSED,
            capability_id="hwpx.read",
            reason_code="hwpx_mimetype_mismatch",
            note=None,
            text=None,
        )
        ok_validation = hwpx_skill.HwpxValidateReceipt(
            status=STATUS_OK,
            capability_id="hwpx.validate",
            reason_code="ok",
            note=None,
            scope=hwpx_skill.VALIDATION_SCOPE_GATE_AND_TEXT,
            full_spec_support_claimed=False,
            text_present=True,
            gate=hwpx_skill.HwpxGateMetadata.from_gate(
                inspect_file("fake.hwpx", _fake_png_bytes())
            ),
        )
        with (
            mock.patch("kagent.hwpx_skill.hwpx_validate", return_value=ok_validation),
            mock.patch("kagent.hwpx_skill.hwpx_read", return_value=refused_read),
        ):
            readback = hwpx_insert_image("doc.hwpx", self.payload, _request())
        self.assertEqual(
            readback.receipt.reason_code, REASON_INSERT_IMAGE_OUTPUT_READBACK_REJECTED
        )

        for result in (gate, validation, readback):
            self.assertIsNone(result.artifact)

    def test_core_refusal_during_insertion_produces_no_artifact(self) -> None:
        from padiem_ai_core.document_semantics import DocumentNormalizationError

        with mock.patch(
            "kagent.hwpx_skill.insert_hwpx_image",
            side_effect=DocumentNormalizationError("hwpx_image_manifest_missing", "x"),
        ):
            result = hwpx_insert_image("doc.hwpx", self.payload, _request())
        self.assertEqual(result.receipt.reason_code, REASON_INSERT_IMAGE_SOURCE_REJECTED)
        self.assertEqual(result.receipt.note, "hwpx_image_manifest_missing")
        self.assertIsNone(result.artifact)

    def test_unpaired_core_receipts_are_refused_defensively(self) -> None:
        with mock.patch(
            "kagent.hwpx_skill.insert_hwpx_image", return_value=(_template(), ())
        ):
            result = hwpx_insert_image("doc.hwpx", self.payload, _request())
        self.assertEqual(result.receipt.reason_code, REASON_INSERT_IMAGE_SOURCE_REJECTED)
        self.assertIsNone(result.artifact)

    def test_missing_picture_readback_is_refused(self) -> None:
        # The picture is present and the counts hold, but the reader reports a
        # different manifest item id than the Core receipt claims, so the
        # receipt's own claim cannot be corroborated by the single reader.
        real_facts = hwpx_skill.read_hwpx_section_facts
        calls: list[int] = []

        def _facts_with_another_item_id(payload: bytes):
            facts = real_facts(payload)
            calls.append(1)
            if len(calls) == 1:
                return facts
            return tuple(
                _SectionFacts(
                    index=section.index,
                    blocks=tuple(
                        _Block(
                            block.kind,
                            _Picture("BIN9999", block.picture.width_hwpunit, block.picture.height_hwpunit)
                            if block.kind == "picture" and block.picture is not None
                            else block.picture,
                        )
                        for block in section.blocks
                    ),
                )
                for section in facts
            )

        with mock.patch(
            "kagent.hwpx_skill.read_hwpx_section_facts",
            side_effect=_facts_with_another_item_id,
        ):
            result = hwpx_insert_image("doc.hwpx", self.payload, _request())
        self.assertEqual(
            result.receipt.reason_code, REASON_INSERT_IMAGE_OUTPUT_PICTURE_MISMATCH
        )
        self.assertIsNone(result.artifact)

    def test_member_preservation_drift_is_refused(self) -> None:
        # A Core output that rewrites a member the splice cannot have touched is
        # refused: the preservation proof is about bytes, not about a plausible
        # result. Only the unrelated member is altered, so the member count and
        # sequence stay correct and the drift itself is what refuses.
        from padiem_ai_core.hwpx_image_insertion import HwpxImageInsertion, insert_hwpx_image

        inserted, _ = insert_hwpx_image(self.payload, (HwpxImageInsertion(0, _png()),))
        drifted = _members_with_altered_unrelated_member(inserted)
        with mock.patch(
            "kagent.hwpx_skill.read_hwpx_package_members",
            side_effect=[_members(self.payload), drifted],
        ):
            result = hwpx_insert_image("doc.hwpx", self.payload, _request())
        self.assertEqual(
            result.receipt.reason_code, REASON_INSERT_IMAGE_OUTPUT_NON_TARGET_DRIFT
        )
        self.assertIsNone(result.artifact)


class _Block:
    """The minimal block shape the facade reads back."""

    def __init__(self, kind: str, picture: object | None = None) -> None:
        self.kind = kind
        self.picture = picture


class _Picture:
    """The minimal picture shape the facade reads back."""

    def __init__(self, item_id: str, width: int, height: int) -> None:
        self.binary_item_id_ref = item_id
        self.width_hwpunit = width
        self.height_hwpunit = height
        self.unsupported = ()


class _SectionFacts:
    """The minimal section-fact shape the facade reads back."""

    def __init__(self, index: int, blocks: tuple) -> None:
        self.index = index
        self.blocks = blocks
        self.structured_unsupported_nodes = 0


def _members(payload: bytes) -> list:
    from padiem_ai_core.document_normalization import HwpxPackageMember

    with ZipFile(BytesIO(payload)) as archive:
        return [
            HwpxPackageMember(name=info.filename, payload=archive.read(info))
            for info in archive.infolist()
        ]


def _members_with_altered_unrelated_member(payload: bytes) -> list:
    """The real member sequence, with one untouched member's bytes rewritten."""

    members = _members(payload)
    altered = []
    for member in members:
        if member.name == "Unrelated/opaque.bin":
            member = type(member)(
                name=member.name, payload=member.payload + b"drift"
            )
        altered.append(member)
    return altered


class HwpxInsertImageProjectionAndAuthorityTests(unittest.TestCase):
    def test_capability_reuses_existing_hwpx_edit_id(self) -> None:
        self.assertIn(CAPABILITY_HWPX_EDIT, RESERVED_CAPABILITY_IDS)
        result = hwpx_insert_image("doc.hwpx", _template(), _request())
        self.assertEqual(result.receipt.capability_id, CAPABILITY_HWPX_EDIT)
        # No new registry capability exists for image insertion.
        self.assertFalse(hasattr(hwpx_skill, "CAPABILITY_HWPX_INSERT_IMAGE"))
        for reserved in RESERVED_CAPABILITY_IDS:
            self.assertNotIn("INSERT_IMAGE", reserved)

    def test_public_receipt_has_bounded_keys_and_excludes_image_bytes(self) -> None:
        result = hwpx_insert_image(
            "C:\\secret\\doc.hwpx", _template(), _request()
        )
        public = result.to_public_dict()
        self.assertEqual(set(public), set(RECEIPT_KEYS))
        projection = str(public)
        for forbidden in (
            "C:\\",
            "secret",
            "Contents/",
            "BinData/",
            "<hp:",
            "mimetype",
            "\\x89PNG",
        ):
            self.assertNotIn(forbidden, projection, forbidden)
        # The encoded image never reaches the receipt or its projection.
        self.assertNotIn(_png().hex(), projection)

    def test_refusal_receipts_carry_no_artifact_metadata(self) -> None:
        result = hwpx_insert_image("doc.hwpx", _template(), _request(section_index=9))
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        public = result.to_public_dict()
        for key in RECEIPT_KEYS - {"status", "capability_id", "reason_code", "note", "validation_status"}:
            self.assertIsNone(public[key], key)
        self.assertIsNone(result.artifact)

    def test_acceptance_block_claims_only_the_bounded_slice(self) -> None:
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_INSERT_IMAGE_FACADE"), "PASS")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("IMAGE_INSERT"), "PASS")
        self.assertEqual(
            hwpx_skill.ACCEPTANCE.get("IMAGE_INSERT_SCOPE"),
            "BOUNDED_PNG_CANONICAL_MANIFEST_PACKAGE",
        )
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("IMAGE_INSERT_UNDER_HWPX_EDIT"), "YES")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("SINGLE_HWPX_IMAGE_INSERTION_AUTHORITY"), "YES")
        for key in (
            "SECOND_HWPX_IMAGE_AUTHORITY",
            "SECOND_IMAGE_DECODER_AUTHORITY",
            "SECOND_HWPX_PARSER_AUTHORITY",
            "SECOND_HWPX_SERIALIZER_AUTHORITY",
            "SECOND_ARCHIVE_GATE_AUTHORITY",
            "SECOND_XML_AUTHORITY",
            "SECOND_SKILL_REGISTRY_AUTHORITY",
            "CALLER_MEMBER_OR_RELATIONSHIP_INPUT",
        ):
            self.assertEqual(hwpx_skill.ACCEPTANCE.get(key), "0", key)
        # Nothing wider than the bounded slice is claimed.
        for key in (
            "IMAGE_EDIT",
            "DIRECT_JPEG_EMBEDDING",
            "STYLE_EDIT",
            "LAYOUT_FIDELITY",
            "TABLE_EDIT",
            "ROW_COLUMN_MUTATION",
        ):
            self.assertEqual(hwpx_skill.ACCEPTANCE.get(key), "NOT_CLAIMED", key)
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_FULL_SPEC_SUPPORT"), "NO")
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("DOCUMENT_EXPORT_HWPX_ENABLED"), "NO")

    def test_facade_adds_no_second_parser_decoder_or_archive_writer(self) -> None:
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
            "from PIL",
            "Image.open",
            "image/jpeg",
            "image/jpg",
            "subprocess",
            "requests",
            "urllib",
            "socket",
            "open(",
        ):
            self.assertNotIn(forbidden, source, forbidden)

    def test_facade_reaches_core_only_through_accepted_modules(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        imported_core_modules = {
            line.split()[1]
            for line in source.splitlines()
            if line.startswith("from padiem_ai_core")
        }
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
        # The image authority is the single byte producer for an insertion.
        self.assertIn("insert_hwpx_image(", source)

    def test_insert_image_writes_no_host_file_and_opens_no_socket(self) -> None:
        with mock.patch(
            "builtins.open", side_effect=AssertionError("host write attempted")
        ):
            result = hwpx_insert_image("doc.hwpx", _template(), _request())
        self.assertEqual(result.receipt.status, STATUS_OK)
        with mock.patch.object(
            socket, "socket", side_effect=AssertionError("network attempted")
        ):
            result = hwpx_insert_image("doc.hwpx", _template(), _request())
        self.assertEqual(result.receipt.status, STATUS_OK)

    def test_request_shape_grants_no_package_authority(self) -> None:
        # The request can only name a section and supply image bytes plus an
        # optional draw extent. Every package-level identifier stays Core's.
        self.assertEqual(
            list(HwpxImageInsertionRequest.__dataclass_fields__),
            ["section_index", "image", "width_hwpunit", "height_hwpunit"],
        )

    def test_ok_receipt_requires_exact_shape_metadata(self) -> None:
        with self.assertRaises(ValueError):
            HwpxInsertImageReceipt(
                status=STATUS_OK,
                capability_id=CAPABILITY_HWPX_EDIT,
                reason_code="ok",
                note=None,
                media_type="application/hwp+zip",
                suggested_filename="doc.hwpx",
                byte_size=1,
                section_count=1,
                paragraph_count=1,
                picture_count=1,
                inserted_image_count=1,
                binary_item_id_ref="not-an-item-id",
                image_media_type="image/png",
                image_source_format="PNG",
                image_bytes=1,
                image_width_hwpunit=1,
                image_height_hwpunit=1,
                image_width_px=1,
                image_height_px=1,
                validation_status=VALIDATION_STATUS_INSERT_IMAGE_OK,
            )

    def test_a_refused_receipt_cannot_claim_a_verified_readback(self) -> None:
        with self.assertRaises(ValueError):
            HwpxInsertImageReceipt(
                status=STATUS_REFUSED,
                capability_id=CAPABILITY_HWPX_EDIT,
                reason_code=REASON_INSERT_IMAGE_GATE_REJECTED,
                note=None,
                media_type=None,
                suggested_filename=None,
                byte_size=None,
                section_count=None,
                paragraph_count=None,
                picture_count=None,
                inserted_image_count=None,
                binary_item_id_ref=None,
                image_media_type=None,
                image_source_format=None,
                image_bytes=None,
                image_width_hwpunit=None,
                image_height_hwpunit=None,
                image_width_px=None,
                image_height_px=None,
                validation_status=VALIDATION_STATUS_INSERT_IMAGE_OK,
            )


if __name__ == "__main__":
    unittest.main()
