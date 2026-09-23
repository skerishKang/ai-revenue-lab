"""#2979: package-preserving mutation output re-enters the accepted authorities.

The Core mutation authority changes one addressed paragraph and preserves every
other archive member byte-for-byte. This module proves the bytes it returns are
accepted by the Skill-level authorities that already exist — the common intake
gate, ``hwpx.inspect``, ``hwpx.validate`` and ``hwpx.read`` — so the new
foundation is a real handoff into the accepted pipeline and not a private
format.

It also records the gap the foundation closes. ``hwpx.edit`` proves source
fidelity by requiring ``serialize(deserialize(payload)) == payload``, so a
package carrying an unrelated member can never satisfy it. That is the right
rule for an editor that owns the whole package, and exactly why a
template-shaped source needs a mutator that copies the members it does not
model instead of refusing them.

Nothing here writes to the host filesystem, opens a socket, or mutates
Production.
"""

from __future__ import annotations

import unittest
from io import BytesIO
from zipfile import ZipFile

from padiem_ai_core.hwpx_package_mutation import (
    HwpxParagraphMutation,
    mutate_hwpx_package_preserving_members,
)
from padiem_ai_core.hwpx_package_serializer import (
    HwpxPackageContent,
    HwpxPackageSection,
    assemble_hwpx_package_members,
    serialize_hwpx_package,
)

from kagent.file_intake_safety import DetectedFormat, inspect_file
from kagent.hwpx_skill import (
    REASON_EDIT_SOURCE_NOT_CANONICAL,
    STATUS_OK,
    STATUS_REFUSED,
    HwpxParagraphReplacement,
    hwpx_edit,
    hwpx_inspect,
    hwpx_read,
    hwpx_validate,
)

_FILENAME = "template.hwpx"
_UNRELATED_MEMBER_NAME = "version.xml"
_UNRELATED_MEMBER_PAYLOAD = b"<version>1.0</version>"
_ADDRESSED_TEXT = "성명: 김철수"


def _member_payloads(payload: bytes) -> dict[str, bytes]:
    with ZipFile(BytesIO(payload)) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def _member_names(payload: bytes) -> list[str]:
    with ZipFile(BytesIO(payload)) as archive:
        return archive.namelist()


def _template_with_unrelated_member() -> bytes:
    """A canonical two-section package plus one unrelated safe member.

    The package is produced by the single Core writer, so the section parts are
    in the canonical byte shape; the unrelated member is then appended through
    the same single archive writer, which is the only way Core builds a member
    sequence.
    """

    canonical = serialize_hwpx_package(
        HwpxPackageContent(
            sections=(
                HwpxPackageSection(paragraphs=("성명: 홍길동", "소속: 파디엠")),
                HwpxPackageSection(paragraphs=("비고",)),
            )
        )
    )
    with ZipFile(BytesIO(canonical)) as archive:
        members = [(info.filename, archive.read(info)) for info in archive.infolist()]
    members.append((_UNRELATED_MEMBER_NAME, _UNRELATED_MEMBER_PAYLOAD))
    return assemble_hwpx_package_members(tuple(members))


class HwpxMutationCompositionTests(unittest.TestCase):
    def test_hwpx_edit_refuses_the_source_this_foundation_accepts(self) -> None:
        """The closed gap, recorded as a contract rather than a comment.

        ``hwpx.edit`` is not wrong here: whole-package byte canonicality is what
        makes its proof lossless. The point is that a template-shaped source
        needs the member-preserving path instead.
        """

        payload = _template_with_unrelated_member()

        edit = hwpx_edit(
            _FILENAME, payload, (HwpxParagraphReplacement(0, 0, _ADDRESSED_TEXT),)
        )
        self.assertEqual(edit.receipt.status, STATUS_REFUSED)
        self.assertEqual(edit.receipt.reason_code, REASON_EDIT_SOURCE_NOT_CANONICAL)
        self.assertIsNone(edit.artifact)

        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, _ADDRESSED_TEXT),)
        )
        self.assertNotEqual(output, payload)

    def test_mutation_output_is_admitted_by_the_common_gate(self) -> None:
        payload = _template_with_unrelated_member()
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, _ADDRESSED_TEXT),)
        )

        gate = inspect_file(_FILENAME, output)
        self.assertTrue(gate.safe_to_parse)
        self.assertIs(gate.detected_format, DetectedFormat.HWPX_CANDIDATE)

    def test_mutation_output_passes_inspect_validate_and_read(self) -> None:
        payload = _template_with_unrelated_member()
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, _ADDRESSED_TEXT),)
        )

        inspect = hwpx_inspect(_FILENAME, output)
        self.assertEqual(inspect.status, STATUS_OK)
        self.assertEqual(inspect.reason_code, "ok")

        validate = hwpx_validate(_FILENAME, output)
        self.assertEqual(validate.status, STATUS_OK)
        self.assertTrue(validate.text_present)
        self.assertFalse(validate.full_spec_support_claimed)

        read = hwpx_read(_FILENAME, output)
        self.assertEqual(read.status, STATUS_OK)
        self.assertIn(_ADDRESSED_TEXT, read.text or "")

    def test_mutation_output_preserves_the_unrelated_member_payload(self) -> None:
        payload = _template_with_unrelated_member()
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, _ADDRESSED_TEXT),)
        )

        before = _member_payloads(payload)
        after = _member_payloads(output)
        self.assertEqual(before[_UNRELATED_MEMBER_NAME], _UNRELATED_MEMBER_PAYLOAD)
        self.assertEqual(after[_UNRELATED_MEMBER_NAME], _UNRELATED_MEMBER_PAYLOAD)
        self.assertEqual(before[_UNRELATED_MEMBER_NAME], after[_UNRELATED_MEMBER_NAME])

    def test_mutation_output_keeps_the_member_name_sequence(self) -> None:
        payload = _template_with_unrelated_member()
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, _ADDRESSED_TEXT),)
        )

        self.assertEqual(_member_names(output), _member_names(payload))

    def test_unchanged_sections_keep_their_payloads_and_their_text(self) -> None:
        payload = _template_with_unrelated_member()
        output = mutate_hwpx_package_preserving_members(
            payload, (HwpxParagraphMutation(0, 0, _ADDRESSED_TEXT),)
        )

        before = _member_payloads(payload)
        after = _member_payloads(output)
        self.assertEqual(
            before["Contents/section2.xml"], after["Contents/section2.xml"]
        )

        read = hwpx_read(_FILENAME, output)
        self.assertEqual(read.status, STATUS_OK)
        self.assertIn("소속: 파디엠", read.text or "")
        self.assertIn("비고", read.text or "")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
