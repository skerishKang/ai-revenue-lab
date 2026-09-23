from __future__ import annotations

import hashlib
import inspect
from io import BytesIO
from zipfile import ZipFile

import pytest

from padiem_ai_core.document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    DocumentNormalizationError,
    extract_hwpx_text,
    validate_ooxml_archive,
)
from padiem_ai_core.document_semantics import MAX_DOCUMENT_SEGMENTS
from padiem_ai_core.hwpx_package_serializer import (
    HWPX_MEDIA_TYPE,
    MAX_HWPX_PACKAGE_TEXT_CHARS,
    MAX_HWPX_PARAGRAPH_CHARS,
    MAX_HWPX_PARAGRAPHS,
    MAX_HWPX_SECTIONS,
    HwpxPackageContent,
    HwpxPackageSection,
    serialize_hwpx_package,
)


def _content(*sections: tuple[str, ...]) -> HwpxPackageContent:
    return HwpxPackageContent(
        sections=tuple(HwpxPackageSection(paragraphs=tuple(section)) for section in sections)
    )


def _one(text: str) -> HwpxPackageContent:
    return _content((text,))


def _member_names(payload: bytes) -> list[str]:
    with ZipFile(BytesIO(payload)) as archive:
        return archive.namelist()


def test_deterministic_bytes_for_identical_input() -> None:
    content = _content(("견적서", "합계 1,000원"), ("발주서", "품목 A"))
    first = serialize_hwpx_package(content)
    second = serialize_hwpx_package(content)
    assert first == second
    assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest()


def test_canonical_member_names_and_mimetype() -> None:
    payload = serialize_hwpx_package(_content(("한글",), ("두번째 섹션", "문단")))
    assert _member_names(payload) == [
        "mimetype",
        "Contents/section1.xml",
        "Contents/section2.xml",
    ]
    with ZipFile(BytesIO(payload)) as archive:
        declared = archive.read("mimetype").decode("ascii")
    assert declared == HWPX_MEDIA_TYPE
    assert validate_ooxml_archive(payload) is None


def test_korean_text_round_trip_through_existing_reader() -> None:
    content = _content(("안녕하세요, PADIEM AI.", "두 번째 문단입니다."))
    text = extract_hwpx_package_text(content)
    assert text == "안녕하세요, PADIEM AI.\n두 번째 문단입니다."
    assert extract_hwpx_text(serialize_hwpx_package(content)) == text


def test_xml_metacharacter_round_trip_without_injection() -> None:
    hostile = '</t><evil xmlns:x="x"/>text&amp;<tag>'
    content = _one(hostile)
    payload = serialize_hwpx_package(content)
    section_xml = ZipFile(BytesIO(payload)).read("Contents/section1.xml")
    assert b"<evil" not in section_xml
    assert b"</t>" not in section_xml
    assert extract_hwpx_text(payload) == hostile


def test_single_section_multiple_paragraph_reader_projection() -> None:
    content = _content(("r1", "", "r2"))
    assert extract_hwpx_text(serialize_hwpx_package(content)) == extract_hwpx_package_text(content)


def test_exactly_at_paragraph_char_bound_is_accepted() -> None:
    text = "가" * MAX_HWPX_PARAGRAPH_CHARS
    assert extract_hwpx_text(serialize_hwpx_package(_one(text))) == text


def test_oversized_paragraph_text_is_refused() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        serialize_hwpx_package(_one("가" * (MAX_HWPX_PARAGRAPH_CHARS + 1)))
    assert exc.value.code == "hwpx_serialize_paragraph_text_limit"


def test_excessive_paragraph_count_is_refused() -> None:
    paragraphs = tuple("p" for _ in range(MAX_HWPX_PARAGRAPHS + 1))
    with pytest.raises(DocumentNormalizationError) as exc:
        serialize_hwpx_package(_content(paragraphs))
    assert exc.value.code == "hwpx_serialize_paragraph_limit"
    assert MAX_HWPX_PARAGRAPHS == MAX_DOCUMENT_SEGMENTS


def test_excessive_section_count_is_refused() -> None:
    sections = tuple(("x",) for _ in range(MAX_HWPX_SECTIONS + 1))
    with pytest.raises(DocumentNormalizationError) as exc:
        serialize_hwpx_package(HwpxPackageContent(sections=sections))
    assert exc.value.code == "hwpx_serialize_section_limit"


def test_total_text_over_bound_is_refused() -> None:
    chunk = "가" * MAX_HWPX_PARAGRAPH_CHARS
    repeat = MAX_HWPX_PACKAGE_TEXT_CHARS // MAX_HWPX_PARAGRAPH_CHARS + 1
    with pytest.raises(DocumentNormalizationError) as exc:
        serialize_hwpx_package(_content(tuple(chunk for _ in range(repeat))))
    assert exc.value.code in {"hwpx_serialize_text_limit", "hwpx_serialize_paragraph_text_limit"}


def test_empty_and_whitespace_only_models_fail_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as empty:
        serialize_hwpx_package(HwpxPackageContent(sections=()))
    assert empty.value.code == "hwpx_serialize_model"
    with pytest.raises(DocumentNormalizationError) as blank:
        serialize_hwpx_package(_content(("", "")))
    assert blank.value.code == "hwpx_serialize_empty"
    with pytest.raises(DocumentNormalizationError) as space:
        serialize_hwpx_package(_one("   "))
    assert space.value.code == "hwpx_serialize_empty"


def test_malformed_caller_structures_fail_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as wrong_root:
        serialize_hwpx_package({"sections": ()})  # type: ignore[arg-type]
    assert wrong_root.value.code == "hwpx_serialize_model"
    with pytest.raises(DocumentNormalizationError) as list_sections:
        serialize_hwpx_package(HwpxPackageContent(sections=[HwpxPackageSection(paragraphs=("x",))]))  # type: ignore[arg-type]
    assert list_sections.value.code == "hwpx_serialize_model"
    with pytest.raises(DocumentNormalizationError) as list_paragraphs:
        serialize_hwpx_package(_content((["not-a-tuple"],)))  # type: ignore[arg-type]
    assert list_paragraphs.value.code == "hwpx_serialize_model"
    with pytest.raises(DocumentNormalizationError) as non_str:
        serialize_hwpx_package(HwpxPackageContent(sections=(HwpxPackageSection(paragraphs=(1,)),)))  # type: ignore[arg-type]
    assert non_str.value.code == "hwpx_serialize_model"
    with pytest.raises(DocumentNormalizationError) as control:
        serialize_hwpx_package(_one("ok\x00bad"))
    assert control.value.code == "hwpx_serialize_control_char"


def test_public_surface_has_no_raw_authority_parameters() -> None:
    signature = inspect.signature(serialize_hwpx_package)
    assert list(signature.parameters) == ["content"]
    annotation = signature.parameters["content"].annotation
    assert annotation in {HwpxPackageContent, "HwpxPackageContent"}


def test_source_scan_rejects_host_network_and_second_authority() -> None:
    import padiem_ai_core.hwpx_package_serializer as module

    source = inspect.getsource(module)
    for forbidden in (
        "import socket",
        "urllib",
        "subprocess",
        "requests",
        "httpx",
        "open(",
        "pathlib",
        "os.system",
        "NamedTemporaryFile",
        "mkstemp",
        "shutil",
        "extract_hwpx_text",
        "inspect_file",
        "intake_document",
    ):
        assert forbidden not in source, forbidden
    assert source.count("ZipFile(") == 1
    assert source.count("writestr(") == 2
    assert 'writestr(_fixed_member("mimetype")' in source
    assert 'archive.writestr(_fixed_member(f"Contents/section' in source


def test_member_names_are_fixed_not_caller_supplied() -> None:
    payload = serialize_hwpx_package(_one("고정 멤버"))
    names = _member_names(payload)
    assert names == ["mimetype", "Contents/section1.xml"]
    assert not any(name.startswith("/") or "\\" in name or ".." in name for name in names)


def test_no_host_path_leakage_in_bytes_or_errors() -> None:
    payload = serialize_hwpx_package(_one("경로 유출 없음"))
    text = payload.decode("latin-1", "ignore")
    assert "C:\\" not in text
    assert "/tmp/" not in text
    with pytest.raises(DocumentNormalizationError) as exc:
        serialize_hwpx_package(HwpxPackageContent(sections=()))
    message = str(exc.value)
    assert "C:\\" not in message
    assert "/tmp/" not in message


def test_output_stays_within_core_binary_document_bound() -> None:
    content = _content(tuple(f"문단{i}" for i in range(32)))
    payload = serialize_hwpx_package(content)
    assert len(payload) <= MAX_BINARY_DOCUMENT_BYTES


def extract_hwpx_package_text(content: HwpxPackageContent) -> str:
    sections: list[str] = []
    for section in content.sections:
        paragraphs = [text for text in section.paragraphs if text]
        value = "\n".join(paragraphs).strip()
        if value:
            sections.append(value)
    return "\n".join(sections).strip()
