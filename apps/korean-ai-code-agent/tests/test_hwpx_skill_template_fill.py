"""#2989: hwpx.template_fill Skill facade contract tests.

The first bounded template-fill facade must compose accepted authorities and add
none. It reuses the single #2979 package-preserving mutation authority, so a
supplied template's unrelated members survive byte-for-byte and the member name
sequence is unchanged; it defines only the smallest deterministic placeholder
grammar; and it reports success only after the common intake gate, the existing
validate and read authorities, and a structured decode of the output all agreed
with the intended filled model.

Nothing here writes to the host filesystem, opens a socket, or mutates
Production.
"""

from __future__ import annotations

import socket
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock
from zipfile import ZIP_STORED, ZipFile

from padiem_ai_core.document_semantics import DocumentNormalizationError
from padiem_ai_core.hwpx_package_mutation import (
    mutate_hwpx_package_preserving_members,
)
from padiem_ai_core.hwpx_package_serializer import (
    HWPX_MEDIA_TYPE,
    MAX_HWPX_PARAGRAPH_CHARS,
    HwpxPackageContent,
    HwpxPackageSection,
    _assemble_hwpx_package_members,
    deserialize_hwpx_package,
    serialize_hwpx_package,
    validate_hwpx_paragraph_text,
)

from kagent import hwpx_skill
from kagent.claw_skill_registry import (
    CAPABILITY_HWPX_TEMPLATE_FILL,
    RESERVED_CAPABILITY_IDS,
)
from kagent.document_parser_contract import is_bounded_reason_code
from kagent.file_intake_safety import DetectedFormat, inspect_file
from kagent.hwpx_skill import (
    MAX_TEMPLATE_FIELD_NAME_CHARS,
    MAX_TEMPLATE_FIELDS,
    PLACEHOLDER_CLOSE,
    PLACEHOLDER_OPEN,
    REASON_TEMPLATE_FIELD_DUPLICATE,
    REASON_TEMPLATE_FIELD_NAME_INVALID,
    REASON_TEMPLATE_FIELD_UNUSED,
    REASON_TEMPLATE_FIELD_VALUE_INVALID,
    REASON_TEMPLATE_FIELD_VALUE_REJECTED,
    REASON_TEMPLATE_FIELDS_INVALID,
    REASON_TEMPLATE_FIELDS_LIMIT,
    REASON_TEMPLATE_GATE_REJECTED,
    REASON_TEMPLATE_SOURCE_NOT_CANONICAL,
    REASON_TEMPLATE_UNFILLED_FIELD,
    STATUS_OK,
    STATUS_REFUSED,
    VALIDATION_STATUS_TEMPLATE_FILL_NOT_RUN,
    VALIDATION_STATUS_TEMPLATE_FILL_OK,
    VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
    VALIDATION_STATUS_TEMPLATE_FILL_SOURCE_REFUSED,
    hwpx_inspect,
    hwpx_read,
    hwpx_template_fill,
    hwpx_validate,
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
        "filled_field_count",
        "validation_status",
    }
)

SECTION_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/section"
PARAGRAPH_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HWPX_MIMETYPE = HWPX_MEDIA_TYPE.encode("ascii")

_UNRELATED_MEMBER_NAME = "version.xml"
_UNRELATED_MEMBER_PAYLOAD = b"<version>1.0</version>"


def _content(*sections: tuple[str, ...]) -> HwpxPackageContent:
    return HwpxPackageContent(
        sections=tuple(HwpxPackageSection(paragraphs=tuple(paragraphs)) for paragraphs in sections)
    )


def _payload(*sections: tuple[str, ...]) -> bytes:
    """A real canonical HWPX package built by the accepted Core serializer."""

    return serialize_hwpx_package(_content(*sections))


def _template(*sections: tuple[str, ...], extra: tuple[str, bytes] | None = None) -> bytes:
    """A canonical package plus one unrelated member the writer does not model.

    Built through the single archive writer, which is the only way Core builds
    a member sequence. This is the template shape ``hwpx.edit`` cannot accept
    and ``hwpx.template_fill`` exists to serve.
    """

    canonical = _payload(*sections)
    with ZipFile(BytesIO(canonical)) as archive:
        members = [(info.filename, archive.read(info)) for info in archive.infolist()]
    if extra is not None:
        members.append(extra)
    return _assemble_hwpx_package_members(tuple(members))


def _member_payloads(payload: bytes) -> dict[str, bytes]:
    with ZipFile(BytesIO(payload)) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def _member_names(payload: bytes) -> list[str]:
    with ZipFile(BytesIO(payload)) as archive:
        return archive.namelist()


def _raw_package(parts: list[tuple[str, bytes]]) -> bytes:
    """Assemble a package by hand so a non-canonical source can be expressed."""

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name, content in parts:
            archive.writestr(name, content)
    return buffer.getvalue()


def _paragraph_xml(text: str) -> str:
    return f"<hp:p><hp:runs><hp:t>{text}</hp:t></hp:runs></hp:p>"


def _part_bytes(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hs:sec xmlns:hs="{SECTION_NAMESPACE}" xmlns:hp="{PARAGRAPH_NAMESPACE}">'
        f"{body}</hs:sec>"
    ).encode()


def _table_template() -> bytes:
    """A gate-admitted HWPX whose structure the editable model cannot represent."""

    body = _paragraph_xml("{{이름}}") + "<hp:tbl><hp:tr><hp:tc>" + _paragraph_xml("셀")
    body += "</hp:tc></hp:tr></hp:tbl>"
    return _raw_package(
        [("mimetype", HWPX_MIMETYPE), ("Contents/section1.xml", _part_bytes(body))]
    )


def _non_canonical_template() -> bytes:
    """A decodable template whose addressed part is not in the canonical shape."""

    canonical = _payload(("{{이름}}",))
    with ZipFile(BytesIO(canonical)) as archive:
        section = archive.read("Contents/section1.xml")
    return _raw_package(
        [
            ("mimetype", HWPX_MIMETYPE),
            ("Contents/section1.xml", section.replace(b"<hs:sec ", b'<hs:sec id="x" ', 1)),
        ]
    )


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


# --------------------------------------------------------------------------- #
# 1. Normal fill
# --------------------------------------------------------------------------- #


class HwpxTemplateFillSuccessTests(unittest.TestCase):
    def test_korean_fields_are_filled(self) -> None:
        payload = _template(("{{성명}} 님", "소속: {{소속}}"))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원", "소속": "파디엠"})
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(result.receipt.reason_code, "ok")
        self.assertEqual(result.receipt.capability_id, CAPABILITY_HWPX_TEMPLATE_FILL)
        self.assertEqual(result.receipt.validation_status, VALIDATION_STATUS_TEMPLATE_FILL_OK)
        self.assertIsNone(result.receipt.note)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("강철원 님", "소속: 파디엠"))

    def test_fill_across_multiple_sections(self) -> None:
        payload = _template(("{{이름}}",), ("{{부서}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"이름": "김진수", "부서": "개발"})
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(result.receipt.filled_field_count, 2)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("김진수",))
        self.assertEqual(decoded.sections[1].paragraphs, ("개발",))

    def test_repeated_placeholder_is_filled_deterministically(self) -> None:
        """The same field twice is not ambiguous: both resolve to one value."""

        payload = _template(("{{이름}} / {{이름}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"이름": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(result.receipt.filled_field_count, 1)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("강철원 / 강철원",))

    def test_decoration_is_copied_verbatim(self) -> None:
        """A ``{{`` that is not a placeholder is never touched."""

        payload = _template(("{{ spaced }} and {{unclosed and {{ok}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"ok": "K"})
        self.assertEqual(result.receipt.status, STATUS_OK)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("{{ spaced }} and {{unclosed and K",))

    def test_non_placeholder_paragraphs_are_untouched(self) -> None:
        payload = _template(("보존1", "{{이름}}", "보존3"))
        result = hwpx_template_fill("tpl.hwpx", payload, {"이름": "강철원"})
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("보존1", "강철원", "보존3"))

    def test_section_and_paragraph_counts_are_preserved(self) -> None:
        payload = _template(("{{a}}", "{{b}}"), ("{{c}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"a": "1", "b": "2", "c": "3"})
        self.assertEqual(result.receipt.section_count, 2)
        self.assertEqual(result.receipt.paragraph_count, 3)

    def test_xml_metacharacters_in_values_round_trip(self) -> None:
        payload = _template(("{{값}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"값": "<a> & </a>"})
        self.assertEqual(result.receipt.status, STATUS_OK)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("<a> & </a>",))

    def test_grammar_delimiters_are_the_canonical_ones(self) -> None:
        self.assertEqual(PLACEHOLDER_OPEN, "{{")
        self.assertEqual(PLACEHOLDER_CLOSE, "}}")

    def test_a_value_is_not_recursively_expanded(self) -> None:
        """No nesting: a value that looks like a placeholder is literal."""

        payload = _template(("{{아이디}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"아이디": "{{이름}}"})
        self.assertEqual(result.receipt.status, STATUS_OK)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("{{이름}}",))

    def test_an_empty_value_fails_closed(self) -> None:
        """A value that would leave the document unreadable is refused."""

        payload = _template(("{{이름}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"이름": ""})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_VALUE_REJECTED)
        self.assertIsNone(result.artifact)


# --------------------------------------------------------------------------- #
# 2. Missing field
# --------------------------------------------------------------------------- #


class HwpxTemplateFillMissingFieldTests(unittest.TestCase):
    def test_template_field_with_no_value_is_refused(self) -> None:
        payload = _template(("{{성명}}/{{소속}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_UNFILLED_FIELD)
        self.assertIsNone(result.artifact)

    def test_empty_mapping_is_refused(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELDS_INVALID)

    def test_unused_supplied_field_is_refused(self) -> None:
        """A field the template does not name is a caller mistake, not a no-op."""

        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원", "없는필드": "x"})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_UNUSED)
        self.assertIsNone(result.artifact)

    def test_there_is_no_partial_fill(self) -> None:
        """A refused fill leaves no artifact, so no half-filled document exists."""

        payload = _template(("{{성명}} {{소속}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertIsNone(result.artifact)


# --------------------------------------------------------------------------- #
# 3. Duplicate / ambiguous field
# --------------------------------------------------------------------------- #


class HwpxTemplateFillDuplicateTests(unittest.TestCase):
    def test_duplicate_key_in_the_mapping_is_refused(self) -> None:
        """A repeated name is refused rather than resolved by request order."""

        payload = _template(("{{성명}}",))
        result = hwpx_template_fill(
            "tpl.hwpx", payload, (("성명", "첫번째"), ("성명", "두번째"))
        )
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_DUPLICATE)
        self.assertIsNone(result.artifact)

    def test_repeated_placeholder_is_not_ambiguous(self) -> None:
        """One field name appearing twice in the template is one field."""

        payload = _template(("{{성명}}", "{{성명}}"))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(result.receipt.filled_field_count, 1)
        decoded = deserialize_hwpx_package(result.artifact.payload)
        self.assertEqual(decoded.sections[0].paragraphs, ("강철원", "강철원"))

    def test_tuple_of_pairs_is_an_accepted_container(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, (("성명", "강철원"),))
        self.assertEqual(result.receipt.status, STATUS_OK)


# --------------------------------------------------------------------------- #
# 4. Invalid field name
# --------------------------------------------------------------------------- #


class HwpxTemplateFillFieldNameTests(unittest.TestCase):
    def test_field_name_with_whitespace_is_refused(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"bad name": "x", "성명": "강철원"})
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_NAME_INVALID)

    def test_empty_field_name_is_refused(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"": "x", "성명": "강철원"})
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_NAME_INVALID)

    def test_field_name_with_a_delimiter_is_refused(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"a}b": "x", "성명": "강철원"})
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_NAME_INVALID)

    def test_field_name_with_a_control_character_is_refused(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"a\nb": "x", "성명": "강철원"})
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_NAME_INVALID)

    def test_oversized_field_name_is_refused(self) -> None:
        payload = _template(("{{성명}}",))
        long_name = "a" * (MAX_TEMPLATE_FIELD_NAME_CHARS + 1)
        result = hwpx_template_fill("tpl.hwpx", payload, {long_name: "x", "성명": "강철원"})
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_NAME_INVALID)

    def test_allowed_punctuation_field_names_are_accepted(self) -> None:
        payload = _template(("{{user_name}} {{user.id}} {{user-id}} {{도트.필드}}",))
        result = hwpx_template_fill(
            "tpl.hwpx",
            payload,
            {"user_name": "a", "user.id": "b", "user-id": "c", "도트.필드": "d"},
        )
        self.assertEqual(result.receipt.status, STATUS_OK)

    def test_a_placeholder_is_never_a_templating_language(self) -> None:
        """No Jinja-style conditional, comment or loop marker exists anywhere.

        The check is on the delimiter tokens that would make this a templating
        language, not on English prose in the docstring.
        """

        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ("{%", "%}", "{#", "#}", "{{%", "{{#", "endif", "endfor"):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertEqual(PLACEHOLDER_OPEN, "{{")
        self.assertEqual(PLACEHOLDER_CLOSE, "}}")


# --------------------------------------------------------------------------- #
# 5. Invalid / oversized value
# --------------------------------------------------------------------------- #


class HwpxTemplateFillValueTests(unittest.TestCase):
    def test_non_string_value_is_refused(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": 123})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_VALUE_INVALID)
        self.assertIsNone(result.artifact)

    def test_none_value_is_refused(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": None})
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_VALUE_INVALID)

    def test_oversized_value_is_refused(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "x" * (MAX_HWPX_PARAGRAPH_CHARS + 1)})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_VALUE_REJECTED)
        self.assertIsNone(result.artifact)

    def test_control_character_value_is_refused(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강\x00철원"})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELD_VALUE_REJECTED)

    def test_value_bound_is_the_canonical_paragraph_bound(self) -> None:
        """The value bound is the Core paragraph bound, not a private copy."""

        payload = _template(("{{성명}}",))
        at_bound = hwpx_template_fill("tpl.hwpx", payload, {"성명": "x" * MAX_HWPX_PARAGRAPH_CHARS})
        self.assertEqual(at_bound.receipt.status, STATUS_OK)


# --------------------------------------------------------------------------- #
# 6. Field count bound
# --------------------------------------------------------------------------- #


class HwpxTemplateFillCountBoundTests(unittest.TestCase):
    def _many(self, count: int) -> tuple[bytes, dict[str, str]]:
        names = [f"f{index}" for index in range(count)]
        text = " ".join(f"{{{{{name}}}}}" for name in names)
        return _template((text,)), {name: "v" for name in names}

    def test_at_the_bound_is_accepted(self) -> None:
        payload, fields = self._many(MAX_TEMPLATE_FIELDS)
        result = hwpx_template_fill("tpl.hwpx", payload, fields)
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(result.receipt.filled_field_count, MAX_TEMPLATE_FIELDS)

    def test_over_the_bound_is_refused(self) -> None:
        payload, fields = self._many(MAX_TEMPLATE_FIELDS + 1)
        result = hwpx_template_fill("tpl.hwpx", payload, fields)
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELDS_LIMIT)
        self.assertIsNone(result.artifact)

    def test_bound_is_explicit_and_small(self) -> None:
        self.assertEqual(MAX_TEMPLATE_FIELDS, 64)


# --------------------------------------------------------------------------- #
# 7. Unsupported paragraph structure
# --------------------------------------------------------------------------- #


class HwpxTemplateFillUnsupportedTests(unittest.TestCase):
    def test_noncanonical_table_template_is_refused_not_filled_around(self) -> None:
        result = hwpx_template_fill("tb.hwpx", _table_template(), {"이름": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_SOURCE_NOT_CANONICAL)
        self.assertEqual(result.receipt.note, "hwpx_mutation_target_not_canonical")
        self.assertIsNone(result.artifact)

    def test_non_canonical_addressed_part_is_refused(self) -> None:
        """Canonicality is the mutator's judgement, reached through the mutator."""

        result = hwpx_template_fill("nc.hwpx", _non_canonical_template(), {"이름": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_SOURCE_NOT_CANONICAL)
        self.assertIsNone(result.artifact)

    def test_non_hwpx_content_is_refused_at_the_common_gate(self) -> None:
        result = hwpx_template_fill("fake.hwpx", _png_bytes(), {"이름": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_REFUSED)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_GATE_REJECTED)
        self.assertEqual(
            result.receipt.validation_status, VALIDATION_STATUS_TEMPLATE_FILL_SOURCE_REFUSED
        )


# --------------------------------------------------------------------------- #
# 8 and 9. Non-target member byte identity and member-name set preservation
# --------------------------------------------------------------------------- #


class HwpxTemplateFillPreservationTests(unittest.TestCase):
    def test_unrelated_member_is_byte_identical(self) -> None:
        payload = _template(("{{성명}} 님",), extra=(_UNRELATED_MEMBER_NAME, _UNRELATED_MEMBER_PAYLOAD))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_OK)
        before = _member_payloads(payload)
        after = _member_payloads(result.artifact.payload)
        self.assertEqual(before[_UNRELATED_MEMBER_NAME], _UNRELATED_MEMBER_PAYLOAD)
        self.assertEqual(after[_UNRELATED_MEMBER_NAME], _UNRELATED_MEMBER_PAYLOAD)
        self.assertEqual(before[_UNRELATED_MEMBER_NAME], after[_UNRELATED_MEMBER_NAME])

    def test_member_name_set_is_unchanged(self) -> None:
        payload = _template(
            ("{{성명}} 님", "소속: {{소속}}"),
            extra=(_UNRELATED_MEMBER_NAME, _UNRELATED_MEMBER_PAYLOAD),
        )
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원", "소속": "파디엠"})
        self.assertEqual(_member_names(result.artifact.payload), _member_names(payload))

    def test_untouched_section_keeps_its_payload(self) -> None:
        """A section with no placeholder is not rewritten at all."""

        payload = _template(("{{성명}}",), ("보존섹션",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        before = _member_payloads(payload)
        after = _member_payloads(result.artifact.payload)
        self.assertEqual(before["Contents/section2.xml"], after["Contents/section2.xml"])

    def test_only_the_addressed_member_changes(self) -> None:
        payload = _template(("{{성명}}",), ("보존섹션",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        before = _member_payloads(payload)
        after = _member_payloads(result.artifact.payload)
        changed = {name for name in before if before[name] != after[name]}
        self.assertEqual(changed, {"Contents/section1.xml"})

    def test_the_mutation_authority_is_the_one_that_proves_preservation(self) -> None:
        """Preservation is the mutator's contract; the facade composes it."""

        payload = _template(("{{성명}}",), extra=(_UNRELATED_MEMBER_NAME, _UNRELATED_MEMBER_PAYLOAD))
        with mock.patch(
            "kagent.hwpx_skill.mutate_hwpx_package_preserving_members",
            wraps=mutate_hwpx_package_preserving_members,
        ) as mutator:
            result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(mutator.call_count, 1)


# --------------------------------------------------------------------------- #
# 10. Deterministic output
# --------------------------------------------------------------------------- #


class HwpxTemplateFillDeterminismTests(unittest.TestCase):
    def test_same_request_produces_identical_bytes(self) -> None:
        payload = _template(("{{성명}} 님", "소속: {{소속}}"))
        fields = {"성명": "강철원", "소속": "파디엠"}
        first = hwpx_template_fill("tpl.hwpx", payload, fields)
        second = hwpx_template_fill("tpl.hwpx", payload, fields)
        self.assertEqual(first.receipt.status, STATUS_OK)
        self.assertEqual(first.artifact.payload, second.artifact.payload)

    def test_same_request_produces_an_identical_receipt(self) -> None:
        payload = _template(("{{성명}}",))
        fields = {"성명": "강철원"}
        first = hwpx_template_fill("tpl.hwpx", payload, fields)
        second = hwpx_template_fill("tpl.hwpx", payload, fields)
        self.assertEqual(first.receipt.to_public_dict(), second.receipt.to_public_dict())

    def test_two_runs_produce_the_same_byte_size(self) -> None:
        payload = _template(("{{성명}}",))
        fields = {"성명": "강철원"}
        first = hwpx_template_fill("tpl.hwpx", payload, fields)
        second = hwpx_template_fill("tpl.hwpx", payload, fields)
        self.assertEqual(first.receipt.byte_size, second.receipt.byte_size)
        self.assertEqual(first.receipt.byte_size, len(first.artifact.payload))


# --------------------------------------------------------------------------- #
# 11. Existing inspect / validate / read re-entry
# --------------------------------------------------------------------------- #


class HwpxTemplateFillReentryTests(unittest.TestCase):
    def test_output_passes_the_common_gate(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        gate = inspect_file("out.hwpx", result.artifact.payload)
        self.assertIs(gate.detected_format, DetectedFormat.HWPX_CANDIDATE)

    def test_output_passes_inspect_validate_and_read(self) -> None:
        payload = _template(("{{성명}} 님", "소속: {{소속}}"))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원", "소속": "파디엠"})

        inspect_receipt = hwpx_inspect("out.hwpx", result.artifact.payload)
        self.assertEqual(inspect_receipt.status, STATUS_OK)
        self.assertEqual(inspect_receipt.reason_code, "ok")

        validate_receipt = hwpx_validate("out.hwpx", result.artifact.payload)
        self.assertEqual(validate_receipt.status, STATUS_OK)
        self.assertTrue(validate_receipt.text_present)
        self.assertFalse(validate_receipt.full_spec_support_claimed)

        read_receipt = hwpx_read("out.hwpx", result.artifact.payload)
        self.assertEqual(read_receipt.status, STATUS_OK)
        self.assertEqual(read_receipt.text, "강철원 님\n소속: 파디엠")

    def test_output_decodes_to_the_intended_filled_model(self) -> None:
        payload = _template(("{{성명}}", "보존"), ("{{부서}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원", "부서": "개발"})
        self.assertEqual(
            deserialize_hwpx_package(result.artifact.payload),
            _content(("강철원", "보존"), ("개발",)),
        )

    def test_no_placeholder_survives_in_the_output(self) -> None:
        payload = _template(("{{성명}} 님",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        read_receipt = hwpx_read("out.hwpx", result.artifact.payload)
        self.assertNotIn("{{", read_receipt.text or "")
        self.assertNotIn("}}", read_receipt.text or "")


# --------------------------------------------------------------------------- #
# Authority and projection contracts
# --------------------------------------------------------------------------- #


class HwpxTemplateFillAuthorityTests(unittest.TestCase):
    def test_capability_id_is_an_existing_reserved_id(self) -> None:
        self.assertIn(CAPABILITY_HWPX_TEMPLATE_FILL, RESERVED_CAPABILITY_IDS)
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        self.assertEqual(result.receipt.capability_id, CAPABILITY_HWPX_TEMPLATE_FILL)

    def test_facade_reaches_core_only_through_accepted_modules(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        imported_core_modules = {
            line.split()[1] for line in source.splitlines() if line.startswith("from padiem_ai_core")
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
            "Contents/",
            "parse_hwpx_sections(",
            "extract_hwpx_text(",
        ):
            self.assertNotIn(forbidden, source, forbidden)
        # #2825's insert_image facade reads member payloads back through Core's
        # existing accessor to prove non-target preservation. That is a read of
        # the single Core accessor, not a second one: both reads happen inside
        # the one preservation helper, it opens no archive of its own, and no
        # caller-supplied member name or path reaches it.
        self.assertEqual(source.count("read_hwpx_package_members("), 2)
        self.assertIn("def _verify_insert_image_preservation(", source)

    def test_facade_reuses_the_single_mutation_authority(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("HwpxParagraphMutation(", source)
        # Exactly one call site: the single place the fill is applied. Counted
        # on the assignment, so the docstring's own references do not inflate it.
        self.assertEqual(
            source.count("filled = mutate_hwpx_package_preserving_members("), 1
        )

    def test_facade_owns_no_archive_gate_of_its_own(self) -> None:
        """#2825: no second archive gate, so the facade must not validate one."""

        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ("validate_ooxml_archive", "parse_hwpx_sections", "extract_hwpx_text("):
            self.assertNotIn(forbidden, source, forbidden)

    def test_fill_path_writes_nothing_to_the_host_filesystem(self) -> None:
        payload = _template(("{{성명}}",))
        with mock.patch("builtins.open", side_effect=AssertionError("host write attempted")):
            result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertIsInstance(result.artifact.payload, bytes)

    def test_fill_path_opens_no_network_socket(self) -> None:
        def _forbidden_socket(*args: object, **kwargs: object) -> None:
            raise AssertionError("network access attempted")

        payload = _template(("{{성명}}",))
        with mock.patch.object(socket, "socket", side_effect=_forbidden_socket):
            result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        self.assertEqual(result.receipt.status, STATUS_OK)

    def test_acceptance_block_matches_issue_2989(self) -> None:
        expected = {
            "HWPX_TEMPLATE_FILL_FOUNDATION": "PASS",
            "HWPX_TEMPLATE_FILL": "PASS",
            "HWPX_TEMPLATE_FILL_SCOPE": "BOUNDED_FOUNDATION",
            "PLACEHOLDER_GRAMMAR_CANONICAL": "SMALLEST_DETERMINISTIC",
            "PACKAGE_PRESERVATION_AUTHORITY_REUSED": "YES",
            "SINGLE_HWPX_MUTATOR_AUTHORITY": "YES",
            "SECOND_HWPX_MUTATOR_AUTHORITY": "0",
            "ALL_NON_TARGET_MEMBERS_BYTE_IDENTICAL": "YES",
            "MEMBER_NAME_SET_UNCHANGED": "YES",
            "UNRELATED_PACKAGE_PART_LOSS": "0",
            "TEMPLATE_FILL_SUCCESS_REQUIRES_PRESERVATION": "YES",
            "SECOND_HWPX_PARSER_AUTHORITY": "0",
            "SECOND_HWPX_SERIALIZER_AUTHORITY": "0",
            "SECOND_XML_AUTHORITY": "0",
            "SECOND_ARCHIVE_GATE_AUTHORITY": "0",
            "COMMON_FILE_INTAKE_GATE_REUSED": "YES",
            "PRODUCTION_MUTATION": "0",
        }
        for key, value in expected.items():
            self.assertEqual(hwpx_skill.ACCEPTANCE.get(key), value, key)

    def test_template_fill_never_claims_a_wider_capability(self) -> None:
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("TABLE_INSERT"), "PASS")
        self.assertEqual(
            hwpx_skill.ACCEPTANCE.get("TABLE_INSERT_SCOPE"),
            "BOUNDED_CANONICAL_BLOCK_SUBSET",
        )
        # #2825 bounded image insertion is a separate facade over its own
        # reserved edit capability, so template fill still claims no image work.
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
        self.assertEqual(hwpx_skill.ACCEPTANCE.get("HWPX_TEMPLATE_FILL"), "PASS")
        self.assertEqual(
            hwpx_skill.ACCEPTANCE.get("HWPX_TEMPLATE_FILL_SCOPE"),
            "BOUNDED_FOUNDATION",
        )


class HwpxTemplateFillProjectionTests(unittest.TestCase):
    def test_public_receipt_is_exactly_the_bounded_key_set(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        self.assertEqual(set(result.receipt.to_public_dict()), set(RECEIPT_KEYS))

    def test_public_receipt_excludes_the_payload(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        self.assertNotIn("payload", result.to_public_dict())
        self.assertNotIn(result.artifact.payload, str(result.to_public_dict()).encode("utf-8"))

    def test_public_receipt_excludes_field_values_and_template_text(self) -> None:
        payload = _template(("{{성명}} 님",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        public = str(result.to_public_dict())
        self.assertNotIn("강철원", public)
        self.assertNotIn("성명", public)

    def test_public_receipt_excludes_raw_xml_and_member_names(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        public = str(result.to_public_dict())
        self.assertNotIn("<hp:", public)
        self.assertNotIn("Contents/", public)
        self.assertNotIn(_UNRELATED_MEMBER_NAME, public)

    def test_public_receipt_excludes_host_paths(self) -> None:
        payload = _template(("{{성명}}",))
        result = hwpx_template_fill(r"C:\secret\tpl.hwpx", payload, {"성명": "강철원"})
        public = str(result.to_public_dict())
        self.assertNotIn("secret", public)
        self.assertNotIn("C:", public)

    def test_public_receipt_key_set_is_identical_on_refusal(self) -> None:
        payload = _template(("{{성명}}",))
        refused = hwpx_template_fill("tpl.hwpx", payload, {"다른필드": "x"})
        self.assertEqual(refused.receipt.status, STATUS_REFUSED)
        self.assertEqual(set(refused.receipt.to_public_dict()), set(RECEIPT_KEYS))

    def test_refusal_reason_codes_are_bounded(self) -> None:
        payload = _template(("{{성명}}",))
        for fields in (
            {},
            {"성명": 1},
            {"bad name": "x", "성명": "y"},
            {"성명": "y", "unused": "z"},
        ):
            with self.subTest(fields=fields):
                result = hwpx_template_fill("tpl.hwpx", payload, fields)
                self.assertEqual(result.receipt.status, STATUS_REFUSED)
                self.assertTrue(is_bounded_reason_code(result.receipt.reason_code))
                self.assertIsNone(result.receipt.note)


class HwpxTemplateFillReceiptContractTests(unittest.TestCase):
    def test_ok_receipt_cannot_skip_the_preservation_contract(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxTemplateFillReceipt(
                status=STATUS_OK,
                capability_id=CAPABILITY_HWPX_TEMPLATE_FILL,
                reason_code="ok",
                note=None,
                media_type=HWPX_MEDIA_TYPE,
                suggested_filename="doc.hwpx",
                byte_size=1,
                section_count=1,
                paragraph_count=1,
                filled_field_count=1,
                validation_status=VALIDATION_STATUS_TEMPLATE_FILL_NOT_RUN,
            )

    def test_refused_receipt_cannot_claim_a_verified_fill(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxTemplateFillReceipt(
                status=STATUS_REFUSED,
                capability_id=CAPABILITY_HWPX_TEMPLATE_FILL,
                reason_code=REASON_TEMPLATE_UNFILLED_FIELD,
                note=None,
                media_type=None,
                suggested_filename=None,
                byte_size=None,
                section_count=None,
                paragraph_count=None,
                filled_field_count=None,
                validation_status=VALIDATION_STATUS_TEMPLATE_FILL_OK,
            )

    def test_refused_receipt_cannot_carry_artifact_metadata(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxTemplateFillReceipt(
                status=STATUS_REFUSED,
                capability_id=CAPABILITY_HWPX_TEMPLATE_FILL,
                reason_code=REASON_TEMPLATE_UNFILLED_FIELD,
                note=None,
                media_type=HWPX_MEDIA_TYPE,
                suggested_filename="doc.hwpx",
                byte_size=1,
                section_count=1,
                paragraph_count=1,
                filled_field_count=1,
                validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
            )

    def test_ok_result_requires_its_artifact(self) -> None:
        receipt = hwpx_skill.HwpxTemplateFillReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_HWPX_TEMPLATE_FILL,
            reason_code="ok",
            note=None,
            media_type=HWPX_MEDIA_TYPE,
            suggested_filename="doc.hwpx",
            byte_size=1,
            section_count=1,
            paragraph_count=1,
            filled_field_count=1,
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_OK,
        )
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxTemplateFillResult(receipt=receipt, artifact=None)

    def test_refused_result_cannot_carry_an_artifact(self) -> None:
        receipt = hwpx_skill.HwpxTemplateFillReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_TEMPLATE_FILL,
            reason_code=REASON_TEMPLATE_UNFILLED_FIELD,
            note=None,
            media_type=None,
            suggested_filename=None,
            byte_size=None,
            section_count=None,
            paragraph_count=None,
            filled_field_count=None,
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
        )
        artifact = hwpx_skill.HwpxTemplateFillArtifact(
            payload=b"x",
            media_type=HWPX_MEDIA_TYPE,
            suggested_filename="doc.hwpx",
            byte_size=1,
            section_count=1,
            paragraph_count=1,
            filled_field_count=1,
        )
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxTemplateFillResult(receipt=receipt, artifact=artifact)

    def test_receipt_rejects_unbounded_note(self) -> None:
        with self.assertRaises(ValueError):
            hwpx_skill.HwpxTemplateFillReceipt(
                status=STATUS_REFUSED,
                capability_id=CAPABILITY_HWPX_TEMPLATE_FILL,
                reason_code=REASON_TEMPLATE_UNFILLED_FIELD,
                note="leak:secret/path",
                media_type=None,
                suggested_filename=None,
                byte_size=None,
                section_count=None,
                paragraph_count=None,
                filled_field_count=None,
                validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
            )


class HwpxTemplateFillAuthorityOrderTests(unittest.TestCase):
    """The common gate decides before the request is judged."""

    def test_common_gate_precedes_the_field_mapping(self) -> None:
        payload = _png_bytes()
        result = hwpx_template_fill("tpl.hwpx", payload, {})
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_GATE_REJECTED)
        self.assertNotEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELDS_INVALID)

    def test_common_gate_precedes_the_field_count_bound(self) -> None:
        fields = {f"f{index}": "v" for index in range(MAX_TEMPLATE_FIELDS + 1)}
        result = hwpx_template_fill("tpl.hwpx", _png_bytes(), fields)
        self.assertEqual(result.receipt.reason_code, REASON_TEMPLATE_GATE_REJECTED)
        self.assertNotEqual(result.receipt.reason_code, REASON_TEMPLATE_FIELDS_LIMIT)

    def test_common_gate_is_the_first_authority_call(self) -> None:
        order: list[str] = []
        real_gate = hwpx_skill.inspect_file
        real_mutator = hwpx_skill.mutate_hwpx_package_preserving_members

        def gate(*args: object, **kwargs: object) -> object:
            order.append("inspect_file")
            return real_gate(*args, **kwargs)  # type: ignore[arg-type]

        def mutator(*args: object, **kwargs: object) -> object:
            order.append("mutate_hwpx_package_preserving_members")
            return real_mutator(*args, **kwargs)  # type: ignore[arg-type]

        payload = _template(("{{성명}}",))
        with mock.patch("kagent.hwpx_skill.inspect_file", side_effect=gate), mock.patch(
            "kagent.hwpx_skill.mutate_hwpx_package_preserving_members", side_effect=mutator
        ):
            result = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})

        self.assertEqual(result.receipt.status, STATUS_OK)
        self.assertEqual(order[0], "inspect_file")
        self.assertIn("mutate_hwpx_package_preserving_members", order)


class HwpxTemplateFillRegressionTests(unittest.TestCase):
    def test_edit_surface_still_works(self) -> None:
        """#2972: the edit foundation is untouched by this child."""

        payload = _payload(("본문",))
        edited = hwpx_skill.hwpx_edit(
            "doc.hwpx", payload, (hwpx_skill.HwpxParagraphReplacement(0, 0, "수정"),)
        )
        self.assertEqual(edited.receipt.status, STATUS_OK)

    def test_create_surface_still_works(self) -> None:
        """#2962: the create foundation is untouched by this child."""

        result = hwpx_skill.hwpx_create(_content(("견적서",)))
        self.assertEqual(result.receipt.status, STATUS_OK)

    def test_a_created_package_is_a_usable_template(self) -> None:
        """Create and template_fill compose: a created package can be filled."""

        created = hwpx_skill.hwpx_create(_content(("{{성명}} 님",)))
        filled = hwpx_template_fill("created.hwpx", created.artifact.payload, {"성명": "강철원"})
        self.assertEqual(filled.receipt.status, STATUS_OK)
        self.assertEqual(
            deserialize_hwpx_package(filled.artifact.payload).sections[0].paragraphs,
            ("강철원 님",),
        )

    def test_a_filled_package_is_a_valid_edit_source(self) -> None:
        """Template fill composes into the accepted edit pipeline."""

        payload = _template(("{{성명}} 님", "보존"))
        filled = hwpx_template_fill("tpl.hwpx", payload, {"성명": "강철원"})
        edited = hwpx_skill.hwpx_edit(
            "filled.hwpx",
            filled.artifact.payload,
            (hwpx_skill.HwpxParagraphReplacement(0, 1, "수정"),),
        )
        self.assertEqual(edited.receipt.status, STATUS_OK)
        self.assertEqual(
            deserialize_hwpx_package(edited.artifact.payload).sections[0].paragraphs,
            ("강철원 님", "수정"),
        )

    def test_mutation_authority_is_unchanged_by_this_child(self) -> None:
        """#2979: the authority this facade reuses behaves the same."""

        payload = _template(("{{성명}}",), extra=(_UNRELATED_MEMBER_NAME, _UNRELATED_MEMBER_PAYLOAD))
        mutated = mutate_hwpx_package_preserving_members(
            payload, (hwpx_skill.HwpxParagraphMutation(0, 0, "강철원"),)
        )
        self.assertEqual(
            _member_payloads(mutated)[_UNRELATED_MEMBER_NAME], _UNRELATED_MEMBER_PAYLOAD
        )

    def test_oversized_value_refusal_reaches_the_canonical_text_rule(self) -> None:
        """The value rule is the Core paragraph-text rule, not a private copy."""

        with self.assertRaises(DocumentNormalizationError):
            validate_hwpx_paragraph_text("x" * (MAX_HWPX_PARAGRAPH_CHARS + 1))


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
