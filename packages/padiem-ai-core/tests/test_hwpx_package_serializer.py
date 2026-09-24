from __future__ import annotations

import hashlib
import inspect
import warnings
from io import BytesIO
from zipfile import ZipFile

import pytest

import padiem_ai_core.document_normalization as document_normalization
import padiem_ai_core.hwpx_package_serializer as hwpx_package_serializer
from padiem_ai_core.document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    DocumentNormalizationError,
    extract_hwpx_text,
    parse_hwpx_sections,
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
    deserialize_hwpx_package,
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
    # #2979: one archive writer with one writestr call site, so the canonical
    # package creator and the package-preserving mutator share a single member
    # policy instead of each carrying its own.
    assert source.count("writestr(") == 1
    assert "archive.writestr(_fixed_member(name), member_payload)" in source
    # The canonical member sequence is still built here, never caller-supplied.
    assert '("mimetype", HWPX_MEDIA_TYPE.encode("ascii"))' in source
    assert 'f"Contents/section{index}.xml"' in source
    # Every emitted member name is judged by the archive gate's own predicate.
    assert "validate_ooxml_member_name(name)" in source


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


# --------------------------------------------------------------------------- #
# #2966 structured decoder: the inverse of the serializer over the subset this
# authority owns, parsed through Core's single HWPX archive-and-XML reader.
# --------------------------------------------------------------------------- #

_SECTION_NS = 'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
_PARA_NS = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'

_MIMETYPE = HWPX_MEDIA_TYPE.encode("ascii")


def _section_xml(body: str) -> bytes:
    return f"{_DECLARATION}<hs:sec {_SECTION_NS} {_PARA_NS}>{body}</hs:sec>".encode()


def _para(text: str) -> str:
    return f"<hp:p><hp:runs><hp:t>{text}</hp:t></hp:runs></hp:p>"


def _archive(members: list[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _plain_archive(section_bodies: list[bytes], *, with_mimetype: bool = True) -> bytes:
    members = [("mimetype", _MIMETYPE)] if with_mimetype else []
    members += [(f"Contents/section{index}.xml", body) for index, body in enumerate(section_bodies, start=1)]
    return _archive(members)


_CANONICAL_MODELS = [
    pytest.param(_content(("하나의 문단",)), id="single-paragraph"),
    pytest.param(_content(("첫째", "둘째", "셋째")), id="one-section-three-paragraphs"),
    pytest.param(_content(("A",), ("B", "C"), ("D",)), id="three-sections"),
    pytest.param(_content(("안녕하세요, 단지온 입주민 여러분.",), ("합계 1,000원입니다.",)), id="korean"),
    pytest.param(_content(('<b>굵게</b> & 앰퍼샌드 "인용" \'단독\'',)), id="xml-metacharacters"),
    pytest.param(_content(("", "본문", "")), id="leading-and-empty-paragraphs"),
    pytest.param(_content(("",), ("실질 본문",)), id="empty-section-then-text"),
    pytest.param(_content(("   ", "x")), id="whitespace-only-paragraph"),
    pytest.param(_content(("줄바꿈\n포함",)), id="embedded-line-feed"),
    pytest.param(_content(("탭\tNBSP\u00a0끝",)), id="tab-and-nbsp"),
    pytest.param(_content(("🙂 이모지 😀",)), id="astral-plane"),
    pytest.param(_content(*[("섹션", f"본문 {index}") for index in range(20)]), id="twenty-sections"),
]


@pytest.mark.parametrize("content", _CANONICAL_MODELS)
def test_canonical_model_round_trips_through_the_decoder(content: HwpxPackageContent) -> None:
    assert deserialize_hwpx_package(serialize_hwpx_package(content)) == content


@pytest.mark.parametrize("content", _CANONICAL_MODELS)
def test_canonical_round_trip_is_byte_stable(content: HwpxPackageContent) -> None:
    payload = serialize_hwpx_package(content)
    assert serialize_hwpx_package(deserialize_hwpx_package(payload)) == payload


def test_one_section_structured_round_trip_is_exact() -> None:
    content = _content(("견적서입니다.",))
    decoded = deserialize_hwpx_package(serialize_hwpx_package(content))
    assert decoded.sections == (HwpxPackageSection(paragraphs=("견적서입니다.",)),)


def test_section_order_survives_numeric_member_sorting() -> None:
    content = _content(*[(f"섹션 {index}",) for index in range(12)])
    decoded = deserialize_hwpx_package(serialize_hwpx_package(content))
    assert [section.paragraphs[0] for section in decoded.sections] == [f"섹션 {index}" for index in range(12)]


def test_paragraph_order_within_a_section_is_exact() -> None:
    content = _content(("하나", "둘", "셋", "넷"))
    decoded = deserialize_hwpx_package(serialize_hwpx_package(content))
    assert decoded.sections[0].paragraphs == ("하나", "둘", "셋", "넷")


def test_decoder_distinguishes_documents_the_flat_text_cannot() -> None:
    # Both models flatten to "a\nb\na\nb"; the structured projection keeps the
    # two-paragraph section and the embedded-newline paragraph apart.
    two_paragraphs = _content(("a", "b"), ("a\nb",))
    embedded = _content(("a", "b\na"), ("b",))
    flat_first = extract_hwpx_text(serialize_hwpx_package(two_paragraphs))
    flat_second = extract_hwpx_text(serialize_hwpx_package(embedded))
    assert flat_first == flat_second == "a\nb\na\nb"
    assert deserialize_hwpx_package(serialize_hwpx_package(two_paragraphs)) == two_paragraphs
    assert deserialize_hwpx_package(serialize_hwpx_package(embedded)) == embedded
    assert deserialize_hwpx_package(serialize_hwpx_package(two_paragraphs)) != embedded


def test_decoder_output_is_only_the_canonical_model_types() -> None:
    decoded = deserialize_hwpx_package(serialize_hwpx_package(_content(("모델 검증",), ("둘째",))))
    assert isinstance(decoded, HwpxPackageContent)
    assert isinstance(decoded.sections, tuple)
    assert all(isinstance(section, HwpxPackageSection) for section in decoded.sections)
    assert all(isinstance(text, str) for section in decoded.sections for text in section.paragraphs)


def test_decoded_model_is_always_writable_again() -> None:
    content = _content(("재직렬화 가능", "두 번째"))
    decoded = deserialize_hwpx_package(serialize_hwpx_package(content))
    validate_ooxml_archive(serialize_hwpx_package(decoded))
    assert serialize_hwpx_package(decoded)


def test_deserialize_is_deterministic_for_identical_bytes() -> None:
    payload = serialize_hwpx_package(_content(("결정적", "왕복"), ("셋째",)))
    assert deserialize_hwpx_package(payload) == deserialize_hwpx_package(payload)


def test_flat_projection_and_structured_decoder_agree_on_supported_documents() -> None:
    content = _content(("첫째", "둘째"), ("셋째",), ("넷째",))
    payload = serialize_hwpx_package(content)
    expected = "\n".join(
        "\n".join(text for text in section.paragraphs if text).strip()
        for section in content.sections
    ).strip()
    assert extract_hwpx_text(payload) == expected
    assert deserialize_hwpx_package(payload) == content


def test_malformed_zip_fails_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(b"PK\x03\x04not really an archive")
    assert exc.value.code == "ooxml_malformed"


def test_mimetype_mismatch_fails_closed() -> None:
    payload = _archive(
        [("mimetype", b"application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
         ("Contents/section1.xml", _section_xml(_para("mismatch")))]
    )
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(payload)
    assert exc.value.code == "hwpx_mimetype_mismatch"


def test_missing_section_parts_fails_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(_archive([("mimetype", _MIMETYPE), ("other.xml", _section_xml(_para("x")))]))
    assert exc.value.code == "hwpx_missing_part"


def test_malformed_xml_part_fails_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(_plain_archive([b"<hs:sec unclosed"]))
    assert exc.value.code == "ooxml_invalid_xml"


def test_dtd_in_section_part_fails_closed() -> None:
    body = b'<!DOCTYPE hs:sec [<!ENTITY x "y">]><hs:sec><hp:p>text</hp:p></hs:sec>'
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(_plain_archive([body]))
    assert exc.value.code == "ooxml_dtd_rejected"


def test_unsupported_table_structure_fails_closed_without_lossy_projection() -> None:
    table = (
        _para("intro")
        + "<hp:p><hp:tbl><hp:tr>"
        + f"<hp:tc>{_para('cell-a')}</hp:tc>"
        + f"<hp:tc>{_para('cell-b')}</hp:tc>"
        + "</hp:tr></hp:tbl></hp:p>"
    )
    payload = _plain_archive([_section_xml(table)])
    assert extract_hwpx_text(payload) == "intro\ncell-a\ncell-b"
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(payload)
    assert exc.value.code == "hwpx_unsupported_structure"




def test_table_outside_any_paragraph_is_structurally_decoded() -> None:
    # A direct table block is part of the bounded structured model; the legacy
    # paragraph projection and flat text remain unchanged.
    body = "<hp:tbl><hp:tr><hp:tc>" + _para("cell") + "</hp:tc></hp:tr></hp:tbl>"
    payload = _plain_archive([_section_xml(body)])
    (parsed,) = parse_hwpx_sections(payload)
    assert [(item.text, item.text_nodes, item.holds_nested_paragraph) for item in parsed.paragraphs] == [
        ("cell", 1, False)
    ]
    assert parsed.unsupported_nodes == 3
    assert extract_hwpx_text(payload) == "cell"
    assert deserialize_hwpx_package(payload).sections[0].blocks[0].kind == "table"
    assert deserialize_hwpx_package(payload).sections[0].paragraphs == ()


def test_unsupported_image_and_shape_paragraphs_fail_closed() -> None:
    for label, body in (
        ("image", "<hp:p><hp:runs><hp:img href=" '"rId1"' "/></hp:runs></hp:p>"),
        ("shape", "<hp:p><hp:runs><hp:gm><hp:pts/></hp:gm></hp:runs></hp:p>"),
        ("formula", '<hp:p><hp:runs><hp:omml xmlns:m="http://www.openschemas.org/math"><m:r>x</m:r></hp:omml></hp:runs></hp:p>'),
    ):
        with pytest.raises(DocumentNormalizationError) as exc:
            deserialize_hwpx_package(_plain_archive([_section_xml(body)]))
        assert exc.value.code == "hwpx_unsupported_structure", label


def test_paragraph_without_a_text_node_fails_closed() -> None:
    payload = _plain_archive([_section_xml("<hp:p/>" + _para("본문"))])
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(payload)
    assert exc.value.code == "hwpx_unsupported_run_semantics"


def test_multiple_run_text_nodes_fail_closed_instead_of_joining() -> None:
    joined = "<hp:p><hp:runs><hp:t>앞</hp:t></hp:runs><hp:runs><hp:t>뒤</hp:t></hp:runs></hp:p>"
    payload = _plain_archive([_section_xml(joined)])
    assert extract_hwpx_text(payload) == "앞뒤"
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(payload)
    assert exc.value.code == "hwpx_unsupported_run_semantics"


def test_nested_paragraph_holder_fails_closed() -> None:
    nested = f"<hp:p><hp:sub><hp:p>{_para('inner')}</hp:p></hp:sub></hp:p>"
    payload = _plain_archive([_section_xml(nested)])
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(payload)
    assert exc.value.code == "hwpx_unsupported_structure"


def test_foreign_section_root_fails_closed() -> None:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        + _PARA_NS
        + ">"
        + _para("docx-shaped")
        + "</w:document>"
    )
    payload = _plain_archive([body.encode()])
    assert extract_hwpx_text(payload) == "docx-shaped"
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(payload)
    assert exc.value.code == "hwpx_unsupported_section_root"


def test_duplicate_section_numbers_fail_closed() -> None:
    with warnings.catch_warnings():
        # zipfile warns about the duplicate member name; that collision is the
        # point of the case, not a finding.
        warnings.simplefilter("ignore", UserWarning)
        duplicated = _archive(
            [("mimetype", _MIMETYPE),
             ("Contents/section1.xml", _section_xml(_para("first"))),
             ("Contents/section1.xml", _section_xml(_para("again")))]
        )
    # Two members with one name: reading by name yields the last entry twice, so
    # even the flat authority cannot tell them apart.
    assert extract_hwpx_text(duplicated) == "again\nagain"
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(duplicated)
    assert exc.value.code == "hwpx_unsupported_section_order"


def test_carriage_return_fails_closed_because_parsing_destroys_it() -> None:
    # The serializer accepts 0x0D as an XML character, but a conforming parser
    # rewrites it to a line feed, so the model could not be recovered exactly.
    from_serializer = serialize_hwpx_package(_content(("일\r이",)))
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(from_serializer)
    assert exc.value.code == "hwpx_unsupported_control_character"
    assert extract_hwpx_text(from_serializer) == "일\n이"

    hand_made = _plain_archive([_section_xml(_para("이\r\n경"))])
    with pytest.raises(DocumentNormalizationError) as second:
        deserialize_hwpx_package(hand_made)
    assert second.value.code == "hwpx_unsupported_control_character"


def test_carriage_return_written_as_a_character_reference_fails_closed() -> None:
    # An entity survives parsing as a real 0x0D, so the raw-part guard cannot see
    # it; the text guard refuses it and no model is returned that the writer
    # could not read back.
    payload = _plain_archive([_section_xml(_para("&#13;앞"))])
    assert extract_hwpx_text(payload) == "앞"
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(payload)
    assert exc.value.code == "hwpx_unsupported_control_character"


def test_every_decoded_model_round_trips_through_the_writer() -> None:
    # The decoder's whole contract: whatever it returns, the writer reproduces
    # byte-for-byte and the decoder reads back as the same model.
    supported = [
        _content(("하나",)),
        _content(("a", "b"), ("c",)),
        _content(("", "text", "   ")),
        _content(("\n", "줄\n바꿈\t탭")),
        _content(('<x>&amp;</x>',)),
        _content(*[(f"s{i}", f"p{i}") for i in range(30)]),
    ]
    for content in supported:
        payload = serialize_hwpx_package(content)
        decoded = deserialize_hwpx_package(payload)
        assert decoded == content
        assert serialize_hwpx_package(decoded) == payload


def test_section_count_beyond_the_writer_bound_fails_closed() -> None:
    payload = _plain_archive([_section_xml(_para(f"섹션 {index}")) for index in range(MAX_HWPX_SECTIONS + 1)])
    with pytest.raises(DocumentNormalizationError) as exc:
        deserialize_hwpx_package(payload)
    assert exc.value.code == "hwpx_serialize_section_limit"


def test_decoder_refusals_carry_no_raw_xml_member_names_or_paths() -> None:
    refusals = [
        _plain_archive([b"<hs:sec broken"]),
        _plain_archive([_section_xml("<hp:p><hp:tbl><hp:tr><hp:tc>" + _para("c") + "</hp:tc></hp:tr></hp:tbl></hp:p>")]),
        _archive([("mimetype", b"text/plain"), ("Contents/section1.xml", _section_xml(_para("x")))]),
    ]
    for payload in refusals:
        with pytest.raises(DocumentNormalizationError) as exc:
            deserialize_hwpx_package(payload)
        message = str(exc.value) + exc.value.code
        # "mimetype" is a format concept in a fixed message, not a member name
        # taken from the document; the document's own parts and text never appear.
        for forbidden in ("<hp:", "</hs:sec>", "Contents/", "section1.xml", "cell-a", "C:\\", "/tmp/"):
            assert forbidden not in message, forbidden


def test_decoder_has_no_archive_or_xml_read_surface_of_its_own() -> None:
    """#2966: the structured path must reuse Core's reader, never re-implement it."""

    source = inspect.getsource(hwpx_package_serializer)
    for forbidden in (
        "namelist(",
        "infolist(",
        ".read(",
        "ElementTree",
        "fromstring(",
        "_parse_xml(",
        "validate_ooxml_archive(",
        "extract_hwpx_text",
    ):
        assert forbidden not in source, forbidden
    # The one archive handle in this module is the writer's, and the reader side
    # is a single delegation to Core's parse authority.
    assert source.count("ZipFile(") == 1
    assert source.count("parse_hwpx_sections(") == 1


def test_core_keeps_one_gated_hwpx_walk_per_purpose() -> None:
    """#2979: two bounded HWPX walks, both behind the single archive gate.

    ``parse_hwpx_sections`` walks for structural facts. The raw-member accessor
    walks for the member payloads a package-preserving mutator has to copy
    byte-for-byte. Neither adds a parser, neither adds a gate, and each has
    exactly one archive handle of its own.
    """

    source = inspect.getsource(document_normalization)
    assert source.count("_hwpx_section_index(") == 2  # definition plus the single call site
    assert source.count("def parse_hwpx_sections(") == 1
    assert source.count("def extract_hwpx_text(") == 1
    hwpx_walk = source.split("def parse_hwpx_sections")[1].split("def extract_hwpx_text")[0]
    assert hwpx_walk.count("ZipFile(") == 1
    assert source.count("def extract_docx_text") == 1

    # The second walk is the raw-member accessor, and it is the last one.
    assert source.count("def read_hwpx_package_members(") == 1
    member_walk = source.split("def read_hwpx_package_members(")[1].split("def _extract_pdf_text")[0]
    assert member_walk.count("ZipFile(") == 1
    assert member_walk.count("validate_ooxml_archive(payload)") == 1
    assert member_walk.count("def ") == 0
    # It reads bytes; it never becomes a second XML parser.
    assert "ElementTree" not in member_walk
    assert "fromstring(" not in member_walk
    assert "_parse_xml(" not in member_walk


def test_section_member_naming_rule_is_exposed_not_restated() -> None:
    """#2979: the public section-index name is the reader's own predicate."""

    assert document_normalization.hwpx_section_index is document_normalization._hwpx_section_index
    assert document_normalization.hwpx_section_index("Contents/section3.xml") == 3
    assert document_normalization.hwpx_section_index("Contents/other.xml") is None
    assert document_normalization.hwpx_section_index("section3.xml") is None


def test_archive_member_name_predicate_is_exposed_not_restated() -> None:
    """#2979: the writer judges member names with the gate's own predicate."""

    from padiem_ai_core.document_normalization import validate_ooxml_member_name

    assert validate_ooxml_member_name("Contents/section1.xml") == "Contents/section1.xml"
    for unsafe in ("", "/abs.xml", "../escape.xml", "a\\b.xml", "C:/x.xml", "a//b.xml"):
        with pytest.raises(DocumentNormalizationError) as exc:
            validate_ooxml_member_name(unsafe)
        assert exc.value.code == "ooxml_unsafe_path"



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
