"""#2979 package-preserving paragraph mutation foundation.

The authority under test lets one addressed paragraph change while every other
archive member keeps its exact payload. These tests prove that contract, the
refusals that keep it honest, and the fact that the mutator owns no parsing,
archiving or gate primitive of its own.
"""

from __future__ import annotations

import hashlib
import inspect
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

import padiem_ai_core.document_normalization as document_normalization
import padiem_ai_core.hwpx_package_mutation as hwpx_package_mutation
from padiem_ai_core.document_normalization import (
    MAX_OOXML_ENTRIES,
    MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES,
    DocumentNormalizationError,
    extract_hwpx_text,
    parse_hwpx_sections,
    validate_ooxml_archive,
)
from padiem_ai_core.hwpx_package_mutation import (
    MAX_HWPX_MUTATIONS,
    HwpxParagraphMutation,
    mutate_hwpx_package_preserving_members,
)
from padiem_ai_core.hwpx_package_serializer import (
    HWPX_MEDIA_TYPE,
    HwpxPackageContent,
    HwpxPackageSection,
    deserialize_hwpx_package,
    serialize_hwpx_package,
    serialize_hwpx_section_part,
)

_SECTION_NS = 'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
_PARA_NS = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'

_MIMETYPE = HWPX_MEDIA_TYPE.encode("ascii")


def _section_xml(body: str) -> bytes:
    return f"{_DECLARATION}<hs:sec {_SECTION_NS} {_PARA_NS}>{body}</hs:sec>".encode()


def _para(text: str) -> str:
    return f"<hp:p><hp:runs><hp:t>{text}</hp:t></hp:runs></hp:p>"


def _archive(members: list[tuple[str, bytes]], *, compression: int = ZIP_DEFLATED) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=compression) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _plain_archive(section_bodies: list[bytes], *, with_mimetype: bool = True) -> bytes:
    members = [("mimetype", _MIMETYPE)] if with_mimetype else []
    members += [
        (f"Contents/section{index}.xml", body)
        for index, body in enumerate(section_bodies, start=1)
    ]
    return _archive(members)


def _members(payload: bytes) -> dict[str, bytes]:
    with ZipFile(BytesIO(payload)) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def _names(payload: bytes) -> list[str]:
    with ZipFile(BytesIO(payload)) as archive:
        return archive.namelist()


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(*sections: tuple[str, ...]) -> bytes:
    return serialize_hwpx_package(
        HwpxPackageContent(
            sections=tuple(HwpxPackageSection(paragraphs=section) for section in sections)
        )
    )


def _refusal(payload: bytes, mutations: object) -> str:
    with pytest.raises(DocumentNormalizationError) as exc:
        mutate_hwpx_package_preserving_members(payload, mutations)  # type: ignore[arg-type]
    return exc.value.code


_TABLE_BODY = (
    _para("intro")
    + "<hp:p><hp:tbl><hp:tr>"
    + f"<hp:tc>{_para('cell-a')}</hp:tc>"
    + f"<hp:tc>{_para('cell-b')}</hp:tc>"
    + "</hp:tr></hp:tbl></hp:p>"
)


# --------------------------------------------------------------------------- #
# 1. Success on a canonical package
# --------------------------------------------------------------------------- #


class TestMutationSuccess:
    def test_canonical_plain_text_package_mutates_the_addressed_paragraph(self) -> None:
        payload = _canonical(("첫 문단", "둘째 문단", "셋째 문단"))
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 1, "치환된 문단"),)
        )
        decoded = deserialize_hwpx_package(output)
        assert decoded.sections[0].paragraphs == ("첫 문단", "치환된 문단", "셋째 문단")

    def test_output_reenters_the_same_gate_and_reader(self) -> None:
        payload = _canonical(("하나",))
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, "둘"),)
        )
        assert validate_ooxml_archive(output) is None
        assert extract_hwpx_text(output) == "둘"
        assert parse_hwpx_sections(output)[0].paragraphs[0].text == "둘"

    def test_multiple_addresses_in_one_section_apply_atomically(self) -> None:
        payload = _canonical(("a", "b", "c"))
        output = mutate_hwpx_package_preserving_members(
            payload,
            (HwpxParagraphMutation(0, 0, "A"), HwpxParagraphMutation(0, 2, "C")),
        )
        assert deserialize_hwpx_package(output).sections[0].paragraphs == ("A", "b", "C")

    def test_empty_replacement_is_allowed_while_the_document_stays_readable(self) -> None:
        payload = _canonical(("남길 문단", "지울 문단"))
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 1, ""),)
        )
        assert deserialize_hwpx_package(output).sections[0].paragraphs == ("남길 문단", "")

    def test_mutation_is_deterministic(self) -> None:
        payload = _canonical(("결정적",))
        first = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, "동일"),)
        )
        second = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, "동일"),)
        )
        assert _digest(first) == _digest(second)

    def test_output_is_a_valid_mutation_source_again(self) -> None:
        payload = _canonical(("one", "two"))
        once = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, "ONE"),)
        )
        twice = mutate_hwpx_package_preserving_members(
            once, (HwpxParagraphMutation(0, 1, "TWO"),)
        )
        assert deserialize_hwpx_package(twice).sections[0].paragraphs == ("ONE", "TWO")

    def test_xml_metacharacter_replacement_does_not_inject_structure(self) -> None:
        payload = _canonical(("안전",))
        hostile = '</t><evil xmlns:x="x"/>text&amp;<tag>'
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, hostile),)
        )
        part = _members(output)["Contents/section1.xml"]
        assert b"<evil" not in part
        assert extract_hwpx_text(output) == hostile


# --------------------------------------------------------------------------- #
# 2-3. Preservation of non-target members
# --------------------------------------------------------------------------- #


class TestMutationPreservation:
    def test_unrelated_extra_member_is_preserved_byte_for_byte(self) -> None:
        extra = b"<version>1.0</version>"
        payload = _archive(
            [
                ("mimetype", _MIMETYPE),
                ("version.xml", extra),
                ("Contents/section1.xml", _section_xml(_para("본문"))),
            ]
        )
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, "치환"),)
        )
        assert _names(output) == ["mimetype", "version.xml", "Contents/section1.xml"]
        assert _members(output)["version.xml"] == extra
        assert _digest(_members(output)["version.xml"]) == _digest(extra)

    def test_multiple_sections_change_only_the_addressed_member(self) -> None:
        payload = _plain_archive(
            [_section_xml(_para("섹션A 문단")), _section_xml(_para("섹션B 문단"))]
        )
        before = _members(payload)
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, "섹션A 치환"),)
        )
        after = _members(output)
        assert after["Contents/section1.xml"] != before["Contents/section1.xml"]
        assert after["Contents/section2.xml"] == before["Contents/section2.xml"]
        assert _digest(after["Contents/section2.xml"]) == _digest(
            before["Contents/section2.xml"]
        )

    def test_non_target_paragraphs_in_the_target_section_are_unchanged(self) -> None:
        payload = _canonical(("보존1", "치환대상", "보존2"))
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 1, "치환됨"),)
        )
        paragraphs = deserialize_hwpx_package(output).sections[0].paragraphs
        assert paragraphs[0] == "보존1"
        assert paragraphs[2] == "보존2"

    def test_non_target_section_holding_unsupported_structure_is_preserved(self) -> None:
        """The whole point: a template part this model cannot decode survives."""

        table_part = _section_xml(_TABLE_BODY)
        payload = _archive(
            [
                ("mimetype", _MIMETYPE),
                ("Contents/section1.xml", _section_xml(_para("편집 대상"))),
                ("Contents/section2.xml", table_part),
            ]
        )
        # The accepted decoder refuses this package outright.
        with pytest.raises(DocumentNormalizationError) as exc:
            deserialize_hwpx_package(payload)
        assert exc.value.code == "hwpx_unsupported_structure"

        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, "편집 완료"),)
        )
        assert _members(output)["Contents/section2.xml"] == table_part
        assert _digest(_members(output)["Contents/section2.xml"]) == _digest(table_part)
        assert _names(output) == [
            "mimetype",
            "Contents/section1.xml",
            "Contents/section2.xml",
        ]

    def test_member_name_sequence_and_count_are_preserved(self) -> None:
        payload = _plain_archive(
            [_section_xml(_para("A")), _section_xml(_para("B")), _section_xml(_para("C"))]
        )
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(1, 0, "B2"),)
        )
        assert _names(output) == _names(payload)

    def test_whole_archive_byte_identity_is_not_claimed(self) -> None:
        """Only member payloads are preserved; the container is rebuilt."""

        payload = _plain_archive([_section_xml(_para("동일 본문"))])
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, "동일 본문"),)
        )
        assert _members(output)["Contents/section1.xml"] == _members(payload)[
            "Contents/section1.xml"
        ]
        # Same member payloads, different container bytes.
        assert output != payload

    def test_address_is_a_zero_based_position_not_a_file_number(self) -> None:
        """``section1.xml`` + ``section3.xml``: position 1 is the third-numbered part."""

        payload = _archive(
            [
                ("mimetype", _MIMETYPE),
                ("Contents/section1.xml", _section_xml(_para("S1"))),
                ("Contents/section3.xml", _section_xml(_para("S3"))),
            ]
        )
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(1, 0, "S3-치환"),)
        )
        members = _members(output)
        assert members["Contents/section1.xml"] == _section_xml(_para("S1"))
        assert members["Contents/section3.xml"] == _section_xml(_para("S3-치환"))


# --------------------------------------------------------------------------- #
# 4-7. Source admission refusals come first
# --------------------------------------------------------------------------- #


class TestMutationGateRefusal:
    def test_malformed_archive_is_refused_by_the_gate(self) -> None:
        assert _refusal(b"PK\x03\x04not an archive", (HwpxParagraphMutation(0, 0, "x"),)) == (
            "ooxml_malformed"
        )

    def test_non_zip_payload_is_refused_by_the_gate(self) -> None:
        assert _refusal(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, (HwpxParagraphMutation(0, 0, "x"),)) == (
            "ooxml_malformed"
        )

    def test_path_traversal_member_is_refused_by_the_gate(self) -> None:
        payload = _archive(
            [
                ("mimetype", _MIMETYPE),
                ("../escape.xml", b"x"),
                ("Contents/section1.xml", _section_xml(_para("A"))),
            ]
        )
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == "ooxml_unsafe_path"

    def test_absolute_path_member_is_refused_by_the_gate(self) -> None:
        payload = _archive(
            [
                ("mimetype", _MIMETYPE),
                ("/abs.xml", b"x"),
                ("Contents/section1.xml", _section_xml(_para("A"))),
            ]
        )
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == "ooxml_unsafe_path"

    def test_oversized_entry_is_refused_by_the_gate(self) -> None:
        payload = _archive(
            [
                ("mimetype", _MIMETYPE),
                ("big.bin", b"\x00" * (MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES + 1)),
                ("Contents/section1.xml", _section_xml(_para("A"))),
            ]
        )
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == "ooxml_entry_size"

    def test_excessive_entry_count_is_refused_by_the_gate(self) -> None:
        members = [("mimetype", _MIMETYPE), ("Contents/section1.xml", _section_xml(_para("A")))]
        members += [(f"filler/{index}.bin", b"x") for index in range(MAX_OOXML_ENTRIES)]
        assert _refusal(_archive(members), (HwpxParagraphMutation(0, 0, "Z"),)) == (
            "ooxml_entry_count"
        )

    def test_dtd_carrying_part_is_refused_by_the_gate(self) -> None:
        body = b'<!DOCTYPE hs:sec [<!ENTITY x "y">]><hs:sec><hp:p>text</hp:p></hs:sec>'
        assert _refusal(_plain_archive([body]), (HwpxParagraphMutation(0, 0, "Z"),)) == (
            "ooxml_dtd_rejected"
        )

    def test_source_is_admitted_before_the_instruction_is_judged(self) -> None:
        """The #2972 principle: a bad instruction cannot pre-empt the gate."""

        for label, mutations in (
            ("empty", ()),
            ("non-tuple", [HwpxParagraphMutation(0, 0, "x")]),
            ("bool index", (HwpxParagraphMutation(True, 0, "x"),)),
            ("negative index", (HwpxParagraphMutation(0, -1, "x"),)),
            ("over limit", tuple(HwpxParagraphMutation(0, 0, f"x{i}") for i in range(MAX_HWPX_MUTATIONS + 1))),
        ):
            code = _refusal(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, mutations)
            assert code == "ooxml_malformed", label

    def test_structural_parse_precedes_the_instruction_judgement(self) -> None:
        """A gate-admitted but unparsable source outranks a malformed instruction."""

        payload = _plain_archive([b"<hs:sec unclosed"])
        assert _refusal(payload, ()) == "ooxml_invalid_xml"

    def test_duplicate_member_name_is_refused_before_any_mutation(self) -> None:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            payload = _archive(
                [
                    ("mimetype", _MIMETYPE),
                    ("version.xml", b"<v>1</v>"),
                    ("version.xml", b"<v>2</v>"),
                    ("Contents/section1.xml", _section_xml(_para("A"))),
                ]
            )
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == (
            "hwpx_mutation_duplicate_member"
        )


# --------------------------------------------------------------------------- #
# 4. Target capability refusals
# --------------------------------------------------------------------------- #


class TestMutationTargetRefusal:
    def test_unsupported_target_structure_fails_closed_with_no_output(self) -> None:
        payload = _plain_archive([_section_xml(_TABLE_BODY)])
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == (
            "hwpx_unsupported_structure"
        )

    def test_image_and_shape_targets_fail_closed(self) -> None:
        for label, body in (
            ("image", "<hp:p><hp:runs><hp:img href=" '"rId1"' "/></hp:runs></hp:p>"),
            ("shape", "<hp:p><hp:runs><hp:gm><hp:pts/></hp:gm></hp:runs></hp:p>"),
        ):
            payload = _plain_archive([_section_xml(body)])
            assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == (
                "hwpx_unsupported_structure"
            ), label

    def test_foreign_section_root_fails_closed(self) -> None:
        body = (
            f'{_DECLARATION}<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            + _PARA_NS
            + ">"
            + _para("docx-shaped")
            + "</w:document>"
        )
        payload = _plain_archive([body.encode()])
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == (
            "hwpx_unsupported_section_root"
        )

    def test_carriage_return_target_fails_closed(self) -> None:
        payload = _plain_archive([_section_xml(_para("이\r경"))])
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == (
            "hwpx_unsupported_control_character"
        )

    def test_structurally_representable_but_non_canonical_target_fails_closed(self) -> None:
        """A part carrying shape the model omits must not be silently normalized.

        The fixture is the canonical part with one extra attribute injected: the
        decoder judges elements, not attributes, so the part decodes, but it is
        not the byte shape the single section producer emits. Rewriting it would
        drop the attribute, so the mutator refuses instead.
        """

        canonical_part = serialize_hwpx_section_part(("A",))
        shaped_part = canonical_part.replace(b"<hp:p>", b'<hp:p id="7">', 1)
        assert shaped_part != canonical_part
        payload = _archive(
            [
                ("mimetype", _MIMETYPE),
                ("Contents/section1.xml", shaped_part),
            ]
        )
        # It decodes: an attribute is not a node the model judges.
        assert deserialize_hwpx_package(payload).sections[0].paragraphs == ("A",)
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == (
            "hwpx_mutation_target_not_canonical"
        )

    def test_target_part_missing_the_canonical_declaration_fails_closed(self) -> None:
        payload = _archive(
            [
                ("mimetype", _MIMETYPE),
                ("Contents/section1.xml", f"<hs:sec {_SECTION_NS} {_PARA_NS}>{_para('A')}</hs:sec>".encode()),
            ]
        )
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == (
            "hwpx_mutation_target_not_canonical"
        )

    def test_addressed_section_with_no_readable_text_is_still_addressable(self) -> None:
        """The decoder's readable-text rule is a package rule, not a part rule.

        The single writer produces packages whose first section is entirely
        blank, and the single decoder accepts them, so an address inside such a
        section is a legitimate address. A probe that carried only the addressed
        part would apply the package rule as if it were a part rule and refuse
        a package Core itself can create.
        """

        payload = _canonical(("", ""), ("본문",))
        assert deserialize_hwpx_package(payload).sections[0].paragraphs == ("", "")
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, "채움"),)
        )
        assert extract_hwpx_text(output) == "채움\n본문"
        # The probe's companion section never reaches the output.
        assert _names(output) == ["mimetype", "Contents/section1.xml", "Contents/section2.xml"]

    def test_probe_companion_never_appears_in_a_single_section_output(self) -> None:
        payload = _canonical(("본문",))
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, "교체"),)
        )
        assert _names(output) == ["mimetype", "Contents/section1.xml"]

    def test_mutation_may_not_leave_the_document_unreadable(self) -> None:
        """An output no accepted authority can read is a refusal, not a success.

        Blanking the only paragraph of the only section leaves a package whose
        text is entirely unreadable, so the readability check that runs over the
        assembled output refuses it. The failure is reported at the output, not
        at the instruction, because an empty replacement text is itself legal.
        """

        payload = _canonical(("유일한 본문",))
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, ""),)) == (
            "hwpx_mutation_output_unreadable"
        )


# --------------------------------------------------------------------------- #
# 8-11. Instruction refusals
# --------------------------------------------------------------------------- #


class TestMutationInstructionRefusal:
    def test_empty_and_non_tuple_instructions_are_refused(self) -> None:
        payload = _canonical(("본문",))
        assert _refusal(payload, ()) == "hwpx_mutation_request"
        assert _refusal(payload, [HwpxParagraphMutation(0, 0, "x")]) == "hwpx_mutation_request"

    def test_operation_count_bound_is_enforced(self) -> None:
        payload = _canonical(("본문",))
        accepted = tuple(HwpxParagraphMutation(0, 0, f"v{i}") for i in range(MAX_HWPX_MUTATIONS))
        # The same address repeated is a duplicate, so the bound is proven with
        # distinct addresses over a long enough section.
        long_payload = _canonical(tuple(f"p{index}" for index in range(MAX_HWPX_MUTATIONS)))
        distinct = tuple(
            HwpxParagraphMutation(0, index, f"v{index}") for index in range(MAX_HWPX_MUTATIONS)
        )
        output = mutate_hwpx_package_preserving_members(long_payload, distinct)
        assert deserialize_hwpx_package(output).sections[0].paragraphs[0] == "v0"
        assert len(accepted) == MAX_HWPX_MUTATIONS
        over = distinct + (HwpxParagraphMutation(1, 0, "extra"),)
        assert _refusal(long_payload, over) == "hwpx_mutation_limit"
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "x"),) * 0) == (
            "hwpx_mutation_request"
        )

    def test_non_operation_values_are_refused(self) -> None:
        payload = _canonical(("본문",))
        assert _refusal(payload, ("not-a-mutation",)) == "hwpx_mutation_request"

    def test_bool_indexes_are_refused_even_though_bool_is_an_int(self) -> None:
        payload = _canonical(("본문",))
        assert _refusal(payload, (HwpxParagraphMutation(True, 0, "x"),)) == (
            "hwpx_mutation_index_type"
        )
        assert _refusal(payload, (HwpxParagraphMutation(0, False, "x"),)) == (
            "hwpx_mutation_index_type"
        )

    def test_non_integer_indexes_are_refused(self) -> None:
        payload = _canonical(("본문",))
        assert _refusal(payload, (HwpxParagraphMutation("0", 0, "x"),)) == (
            "hwpx_mutation_index_type"
        )
        assert _refusal(payload, (HwpxParagraphMutation(0, 0.0, "x"),)) == (
            "hwpx_mutation_index_type"
        )

    def test_negative_indexes_are_refused(self) -> None:
        payload = _canonical(("본문",))
        assert _refusal(payload, (HwpxParagraphMutation(0, -1, "x"),)) == (
            "hwpx_mutation_index_negative"
        )
        assert _refusal(payload, (HwpxParagraphMutation(-1, 0, "x"),)) == (
            "hwpx_mutation_index_negative"
        )

    def test_out_of_range_section_is_refused(self) -> None:
        payload = _canonical(("본문",))
        assert _refusal(payload, (HwpxParagraphMutation(1, 0, "x"),)) == (
            "hwpx_mutation_section_missing"
        )

    def test_out_of_range_paragraph_is_refused(self) -> None:
        payload = _canonical(("본문",))
        assert _refusal(payload, (HwpxParagraphMutation(0, 1, "x"),)) == (
            "hwpx_mutation_paragraph_missing"
        )

    def test_duplicate_target_is_refused_rather_than_resolved_by_order(self) -> None:
        payload = _canonical(("본문",))
        assert _refusal(
            payload,
            (HwpxParagraphMutation(0, 0, "first"), HwpxParagraphMutation(0, 0, "second")),
        ) == "hwpx_mutation_duplicate_target"

    def test_non_string_replacement_is_refused(self) -> None:
        payload = _canonical(("본문",))
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, 7),)) == "hwpx_mutation_request"

    def test_oversized_replacement_is_refused_by_the_single_text_rule(self) -> None:
        from padiem_ai_core.hwpx_package_serializer import MAX_HWPX_PARAGRAPH_CHARS

        payload = _canonical(("본문",))
        assert _refusal(
            payload, (HwpxParagraphMutation(0, 0, "가" * (MAX_HWPX_PARAGRAPH_CHARS + 1)),)
        ) == "hwpx_serialize_paragraph_text_limit"

    def test_control_character_replacement_is_refused_by_the_single_text_rule(self) -> None:
        payload = _canonical(("본문",))
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "ok\x00bad"),)) == (
            "hwpx_serialize_control_char"
        )

    def test_address_is_judged_before_the_section_must_be_writable(self) -> None:
        """An out-of-range address on an unsupported section reports the address."""

        payload = _plain_archive([_section_xml(_TABLE_BODY)])
        assert _refusal(payload, (HwpxParagraphMutation(0, 99, "x"),)) == (
            "hwpx_mutation_paragraph_missing"
        )


# --------------------------------------------------------------------------- #
# 17. Public projection carries no document content
# --------------------------------------------------------------------------- #


class TestMutationProjection:
    def test_refusal_messages_carry_no_member_name_xml_or_document_text(self) -> None:
        secret = "비밀문서본문"
        payload = _archive(
            [
                ("mimetype", _MIMETYPE),
                ("version.xml", b"<v>1</v>"),
                ("Contents/section1.xml", _section_xml("<hp:p >" + _para(secret) + "</hp:p >")),
            ]
        )
        with pytest.raises(DocumentNormalizationError) as exc:
            mutate_hwpx_package_preserving_members(
                payload, (HwpxParagraphMutation(0, 0, "치환"),)
            )
        message = str(exc.value) + exc.value.code
        for forbidden in (
            secret,
            "<hp:",
            "</hs:sec>",
            "Contents/",
            "section1.xml",
            "version.xml",
            "C:\\",
            "/tmp/",
        ):
            assert forbidden not in message, forbidden

    def test_every_refusal_code_is_a_bounded_identifier(self) -> None:
        import re

        payload = _canonical(("본문",))
        codes = {
            _refusal(payload, ()),
            _refusal(payload, (HwpxParagraphMutation(True, 0, "x"),)),
            _refusal(payload, (HwpxParagraphMutation(0, -1, "x"),)),
            _refusal(payload, (HwpxParagraphMutation(9, 0, "x"),)),
            _refusal(payload, (HwpxParagraphMutation(0, 9, "x"),)),
            _refusal(payload, (HwpxParagraphMutation(0, 0, "x"),) * 2),
            _refusal(payload, (HwpxParagraphMutation(0, 0, "ok\x00"),)),
            _refusal(b"PK\x03\x04nope", (HwpxParagraphMutation(0, 0, "x"),)),
        }
        assert len(codes) == 8
        for code in codes:
            assert re.fullmatch(r"[a-z][a-z0-9_]{2,63}", code), code

    def test_public_surface_has_no_raw_authority_parameters(self) -> None:
        signature = inspect.signature(mutate_hwpx_package_preserving_members)
        assert list(signature.parameters) == ["payload", "mutations"]

    def test_mutation_value_exposes_only_an_address_and_text(self) -> None:
        assert [field for field in HwpxParagraphMutation.__dataclass_fields__] == [
            "section_index",
            "paragraph_index",
            "text",
        ]


# --------------------------------------------------------------------------- #
# Authority: this module owns no primitive of its own
# --------------------------------------------------------------------------- #


class TestMutationAuthority:
    def test_source_scan_finds_no_archive_xml_or_host_primitive(self) -> None:
        source = inspect.getsource(hwpx_package_mutation)
        for forbidden in (
            "ZipFile(",
            "writestr(",
            "namelist(",
            "infolist(",
            "ElementTree",
            "fromstring(",
            "open(",
            "pathlib",
            "shutil",
            "subprocess",
            "socket",
            "urllib",
            "httpx",
            "tempfile",
            "os.system",
            # Core must not reach for the Skill-level intake or gate authority:
            # the mutator composes Core authorities only.
            "inspect_file",
            "intake_document",
        ):
            assert forbidden not in source, forbidden

    def test_module_reuses_the_single_reader_gate_and_writer(self) -> None:
        source = inspect.getsource(hwpx_package_mutation)
        assert source.count("read_hwpx_package_members(") == 2
        assert source.count("parse_hwpx_sections(") == 1
        assert source.count("serialize_hwpx_section_part(") == 4
        assert source.count("assemble_hwpx_package_members(") == 2
        assert source.count("deserialize_hwpx_package(") == 1
        assert source.count("validate_ooxml_archive(") == 1
        assert source.count("hwpx_section_index(") == 1
        assert source.count("validate_hwpx_paragraph_text(") == 1
        assert source.count("extract_hwpx_text(") == 1

    def test_section_lookup_uses_the_readers_own_predicate(self) -> None:
        assert document_normalization.hwpx_section_index("Contents/section2.xml") == 2
        assert document_normalization.hwpx_section_index("version.xml") is None

    def test_reader_gate_is_reached_through_the_accessor_not_reimplemented(self) -> None:
        """A traversal archive is refused even when the instruction is valid."""

        payload = _archive(
            [
                ("mimetype", _MIMETYPE),
                ("a/../../b.xml", b"x"),
                ("Contents/section1.xml", _section_xml(_para("A"))),
            ]
        )
        assert _refusal(payload, (HwpxParagraphMutation(0, 0, "Z"),)) == "ooxml_unsafe_path"

    def test_canonical_creator_is_unchanged_by_this_child(self) -> None:
        content = HwpxPackageContent(
            sections=(HwpxPackageSection(paragraphs=("회귀", "검사")),)
        )
        payload = serialize_hwpx_package(content)
        assert deserialize_hwpx_package(payload) == content
        assert serialize_hwpx_section_part(content.sections[0].paragraphs) == _members(payload)[
            "Contents/section1.xml"
        ]

    def test_serializer_keeps_a_single_archive_writer(self) -> None:
        import padiem_ai_core.hwpx_package_serializer as serializer

        source = inspect.getsource(serializer)
        assert source.count("ZipFile(") == 1
        assert source.count("writestr(") == 1


class TestMutationAssemblerRefusal:
    def test_assembler_refuses_unsafe_duplicate_and_empty_members(self) -> None:
        from padiem_ai_core.hwpx_package_serializer import assemble_hwpx_package_members

        for label, members, code in (
            ("empty sequence", (), "hwpx_assemble_model"),
            ("not a tuple", [("mimetype", b"x")], "hwpx_assemble_model"),
            ("unsafe name", (("mimetype", b"x"), ("../e.xml", b"y")), "ooxml_unsafe_path"),
            ("duplicate name", (("mimetype", b"x"), ("mimetype", b"y")), "hwpx_assemble_member_name"),
            ("empty payload", (("mimetype", b""),), "hwpx_assemble_payload"),
            ("wrong shape", (("mimetype",),), "hwpx_assemble_model"),
        ):
            with pytest.raises(DocumentNormalizationError) as exc:
                assemble_hwpx_package_members(members)  # type: ignore[arg-type]
            assert exc.value.code == code, label

    def test_assembler_output_always_passes_the_archive_gate(self) -> None:
        from padiem_ai_core.hwpx_package_serializer import assemble_hwpx_package_members

        payload = assemble_hwpx_package_members(
            (("mimetype", _MIMETYPE), ("Contents/section1.xml", _section_xml(_para("x"))))
        )
        assert validate_ooxml_archive(payload) is None

    def test_assembler_uses_stored_compression_and_a_fixed_timestamp(self) -> None:
        from padiem_ai_core.hwpx_package_serializer import assemble_hwpx_package_members

        payload = assemble_hwpx_package_members((("mimetype", _MIMETYPE),))
        with ZipFile(BytesIO(payload)) as archive:
            info = archive.infolist()[0]
        assert info.compress_type == ZIP_STORED
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
        assert info.create_system == 0
        # The member permission bits are assigned by the standard library's
        # member writer, which overwrites whatever the factory set, so they are
        # not part of this authority's policy and are not asserted here.
        # Determinism is: the same member sequence must produce the same bytes.
        assert assemble_hwpx_package_members((("mimetype", _MIMETYPE),)) == payload
        assert assemble_hwpx_package_members(
            (("mimetype", _MIMETYPE), ("a.xml", b"<x/>"))
        ) == assemble_hwpx_package_members(
            (("mimetype", _MIMETYPE), ("a.xml", b"<x/>"))
        )
