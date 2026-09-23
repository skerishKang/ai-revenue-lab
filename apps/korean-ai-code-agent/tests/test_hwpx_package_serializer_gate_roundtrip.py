from __future__ import annotations

import unittest

from padiem_ai_core.hwpx_package_serializer import (
    HwpxPackageContent,
    HwpxPackageSection,
    serialize_hwpx_package,
)

from kagent.document_intake import intake_document
from kagent.file_intake_safety import (
    DetectedFormat,
    IntakeDecision,
    inspect_file,
)


def _content(*sections: tuple[str, ...]) -> HwpxPackageContent:
    return HwpxPackageContent(
        sections=tuple(HwpxPackageSection(paragraphs=tuple(section)) for section in sections)
    )


class HwpxSerializerGateRoundTripTests(unittest.TestCase):
    def test_serialized_bytes_are_truthful_hwpx_candidate_at_gate(self) -> None:
        payload = serialize_hwpx_package(_content(("견적서 생성 검증", "합계 1,000원")))
        gate = inspect_file("out.hwpx", payload)
        self.assertEqual(gate.decision, IntakeDecision.SAFE_CANDIDATE)
        self.assertEqual(gate.detected_format, DetectedFormat.HWPX_CANDIDATE)
        self.assertTrue(gate.safe_to_parse)
        self.assertFalse(gate.mismatch)

    def test_content_decides_candidate_even_without_hwpx_extension(self) -> None:
        payload = serialize_hwpx_package(_one_paragraph())
        gate = inspect_file("artifact.bin", payload)
        self.assertEqual(gate.detected_format, DetectedFormat.HWPX_CANDIDATE)
        self.assertTrue(gate.mismatch)

    def test_gate_then_core_reader_returns_original_text(self) -> None:
        expected = "안녕하세요 <PADIEM> & \"AI\""
        payload = serialize_hwpx_package(_content((expected,), ("두번째 문단",)))
        gate = inspect_file("note.hwpx", payload)
        self.assertEqual(gate.detected_format, DetectedFormat.HWPX_CANDIDATE)
        result = intake_document("note.hwpx", payload)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNone(result.note)
        self.assertEqual(result.text, f"{expected}\n두번째 문단")

    def test_korean_multisection_round_trip_through_intake(self) -> None:
        content = _content(("발주서", "품목 A 수량 2"), ("검수", "합격"))
        payload = serialize_hwpx_package(content)
        result = intake_document("order.hwpx", payload)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.text, "발주서\n품목 A 수량 2\n검수\n합격")

    def test_serializer_source_has_no_gate_or_parser_widening(self) -> None:
        import inspect as inspect_mod

        import padiem_ai_core.hwpx_package_serializer as module

        source = inspect_mod.getsource(module)
        self.assertNotIn("from kagent", source)
        self.assertNotIn("file_intake_safety", source)
        self.assertNotIn("document_intake", source)
        self.assertNotIn("extract_hwpx_text(", source)


def _one_paragraph() -> HwpxPackageContent:
    return _content(("경로가 아닌 고정 멤버 이름",))


if __name__ == "__main__":
    unittest.main()
