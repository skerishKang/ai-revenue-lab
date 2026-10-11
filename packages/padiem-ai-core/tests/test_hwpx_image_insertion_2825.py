"""#2825 bounded PNG-canonical HWPX image insertion authority.

The tests pin the exact supported subset rather than an idealized HWPX: a
template package that carries a ``content.hpf`` manifest and a section part with
a single ``</hs:sec>`` anchor, plus unrelated members that must survive
byte-for-byte.
"""

from __future__ import annotations

import ast
import inspect
from io import BytesIO
from zipfile import ZipFile

import pytest

Image = pytest.importorskip("PIL.Image")

import padiem_ai_core.hwpx_image_insertion as hwpx_image_insertion
from padiem_ai_core.document_normalization import (
    DocumentNormalizationError,
    read_hwpx_package_members,
    read_hwpx_section_facts,
    validate_ooxml_archive,
)
from padiem_ai_core.hwpx_image_insertion import (
    HWPX_BIN_DATA_PREFIX,
    HWPX_EMBEDDED_IMAGE_EXTENSION,
    HWPX_EMBEDDED_IMAGE_MEDIA_TYPE,
    HWPX_IMAGE_INPUT_FORMATS,
    HWPX_MANIFEST_MEMBER,
    MAX_HWPX_IMAGE_BYTES,
    MAX_HWPX_IMAGE_INSERTIONS,
    HwpxImageInsertion,
    insert_hwpx_image,
)
from padiem_ai_core.hwpx_package_serializer import (
    HWPX_MEDIA_TYPE,
    HwpxPicture,
    serialize_hwpx_package,
    serialize_hwpx_picture_paragraph,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

_SECTION_NS = "http://www.hancom.co.kr/hwpml/2011/section"
_PARAGRAPH_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_CORE_NS = "http://www.hancom.co.kr/hwpml/2011/core"
_OPF_NS = "http://www.idpf.org/2007/opf/"
_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'


def _png(width: int = 24, height: int = 16, color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(width: int = 24, height: int = 16) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 30, 40)).save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def _webp(width: int = 8, height: int = 8) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (5, 5, 5)).save(buffer, format="WEBP")
    return buffer.getvalue()


def _section_part(text: str) -> bytes:
    """A section part shaped like a real one: attributes, a run, a linesegarray.

    The extra structure is deliberate. It is exactly what the writer's writable
    subset refuses, so it proves the insertion authority splices additively into
    a member it could never have produced itself.
    """

    body = (
        '<hp:p id="2764991984" paraPrIDRef="3" styleIDRef="0" pageBreak="0">'
        f'<hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run>'
        '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000"'
        ' textheight="1000" baseline="850" horzpos="0" horzsize="42520" flags="393216"/>'
        "</hp:linesegarray></hp:p>"
    )
    document = (
        f'{_DECLARATION}<hs:sec xmlns:hs="{_SECTION_NS}" xmlns:hp="{_PARAGRAPH_NS}"'
        f' xmlns:hc="{_CORE_NS}" version="1.4">{body}</hs:sec>'
    )
    return document.encode("utf-8")


def _manifest(items: str = "") -> bytes:
    manifest = (
        f'{_DECLARATION}<opf:package xmlns:opf="{_OPF_NS}" version="" id="">'
        "<opf:metadata><opf:title/><opf:language>ko</opf:language></opf:metadata>"
        "<opf:manifest>"
        '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
        f"{items}</opf:manifest>"
        '<opf:spine><opf:itemref idref="header" linear="yes"/>'
        '<opf:itemref idref="section0" linear="yes"/></opf:spine>'
        "</opf:package>"
    )
    return manifest.encode("utf-8")


_HEADER = (
    f"{_DECLARATION}<hh:head xmlns:hh=\"http://www.hancom.co.kr/hwpml/2011/head\""
    ' version="1.4" secCnt="1"><hh:beginNum/><hh:refList/></hh:head>'
).encode("utf-8")

_VERSION = (
    f'{_DECLARATION}<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version"'
    ' tagetApplication="WORDPROCESSOR" major="5" minor="0" micro="5" buildNumber="0"/>'
).encode("utf-8")

_SETTINGS = (
    f'{_DECLARATION}<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app"/>'
).encode("utf-8")

_CONTAINER = (
    f'{_DECLARATION}<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf"'
    ' media-type="application/hwpml-package+xml"/></ocf:rootfiles></ocf:container>'
).encode("utf-8")

_UNRELATED = b"\x00\x01opaque pre-existing payload\xff"


def _archive(members: list[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _template(*, manifest: bytes | None = None, sections: int = 1) -> bytes:
    members: list[tuple[str, bytes]] = [
        ("mimetype", HWPX_MEDIA_TYPE.encode("ascii")),
        ("version.xml", _VERSION),
        ("Contents/header.xml", _HEADER),
    ]
    for index in range(sections):
        members.append((f"Contents/section{index}.xml", _section_part(f"본문 {index}")))
    members += [
        ("Contents/content.hpf", _manifest() if manifest is None else manifest),
        ("settings.xml", _SETTINGS),
        ("META-INF/container.xml", _CONTAINER),
        ("Unrelated/opaque.bin", _UNRELATED),
    ]
    return _archive(members)


def _insert(image: bytes, **kwargs) -> tuple[HwpxImageInsertion, ...]:
    return (HwpxImageInsertion(section_index=kwargs.pop("section_index", 0), image=image, **kwargs),)


def _members(payload: bytes) -> dict[str, bytes]:
    return {member.name: member.payload for member in read_hwpx_package_members(payload)}


def _code() -> str:
    """The module's code with every docstring removed.

    Several boundary tests scan the source for forbidden tokens. This module's
    docstrings deliberately *discuss* the tokens it must not use — deferred JPEG
    spellings, ``subprocess``, ``binDataList`` — so a raw text scan would match
    its own rationale. Stripping docstrings leaves the executable source, which
    is what the boundary claims are about.
    """

    tree = ast.parse(inspect.getsource(hwpx_image_insertion))
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _pictures(payload: bytes) -> list[tuple[str, int, int, tuple[str, ...]]]:
    return [
        (block.picture.binary_item_id_ref, block.picture.width_hwpunit, block.picture.height_hwpunit, block.picture.unsupported)
        for section in read_hwpx_section_facts(payload)
        for block in section.blocks
        if block.kind == "picture" and block.picture is not None
    ]


# --------------------------------------------------------------------------- #
# Canonical PNG authority
# --------------------------------------------------------------------------- #


def test_png_input_is_embedded_as_canonical_png() -> None:
    output, receipts = insert_hwpx_image(_template(), _insert(_png()))
    (receipt,) = receipts
    assert receipt.media_type == HWPX_EMBEDDED_IMAGE_MEDIA_TYPE == "image/png"
    assert receipt.source_format == "PNG"
    assert HWPX_EMBEDDED_IMAGE_EXTENSION == "png"
    stored = _members(output)[f"{HWPX_BIN_DATA_PREFIX}BIN0001.png"]
    assert stored.startswith(b"\x89PNG\r\n\x1a\n")
    with ZipFile(BytesIO(output)) as archive:
        assert "BinData/BIN0001.png" in archive.namelist()


def test_jpeg_input_is_decoded_by_core_image_authority_and_stored_as_png() -> None:
    output, receipts = insert_hwpx_image(_template(), _insert(_jpeg()))
    (receipt,) = receipts
    # The receipt keeps the conversion visible instead of silently claiming the
    # caller's own format survived.
    assert receipt.source_format == "JPEG"
    assert receipt.media_type == "image/png"
    members = _members(output)
    assert [name for name in members if name.startswith(HWPX_BIN_DATA_PREFIX)] == [
        f"{HWPX_BIN_DATA_PREFIX}BIN0001.png"
    ]
    # Nothing anywhere in the package mentions a JPEG member or media type.
    for name, payload in members.items():
        assert not name.lower().endswith((".jpg", ".jpeg"))
        assert b"image/jpg" not in payload
        assert b"image/jpeg" not in payload


def test_direct_jpeg_embedding_is_deferred() -> None:
    # Only one embedded media type exists, and it is not JPEG's.
    assert HWPX_IMAGE_INPUT_FORMATS == ("png", "jpeg")
    assert HWPX_EMBEDDED_IMAGE_MEDIA_TYPE == "image/png"
    source = _code()
    assert "image/jpeg" not in source
    assert "image/jpg" not in source


def test_output_png_is_deterministic_for_identical_input() -> None:
    template = _template()
    first, _ = insert_hwpx_image(template, _insert(_jpeg()))
    second, _ = insert_hwpx_image(template, _insert(_jpeg()))
    assert first == second


def test_caller_declared_format_cannot_override_the_payload() -> None:
    # The request carries no format field at all, so there is nothing to lie
    # with: the authority observes the payload.
    assert [field for field in HwpxImageInsertion.__dataclass_fields__] == [
        "section_index",
        "image",
        "width_hwpunit",
        "height_hwpunit",
    ]


def test_embedded_bytes_go_through_the_core_image_authority() -> None:
    source = _code()
    assert "inspect_image(" in source
    assert "transform_image(" in source
    # No second decoder: this module never imports Pillow itself.
    assert "from PIL" not in source
    assert "Image.open" not in source


def test_unsupported_input_format_is_refused_before_any_package_work() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(_template(), _insert(_webp()))
    assert exc.value.code == "hwpx_image_format_unsupported"


def test_malformed_image_payload_is_refused_with_a_core_image_code() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(_template(), _insert(b"\x89PNG\r\n\x1a\n truncated"))
    assert exc.value.code in {"image_decode_failed", "image_bytes_invalid"}


def test_canonical_png_respects_the_archive_gate_per_entry_bound() -> None:
    assert MAX_HWPX_IMAGE_BYTES == 1024 * 1024


# --------------------------------------------------------------------------- #
# Deterministic id allocation
# --------------------------------------------------------------------------- #


def test_first_insertion_allocates_bin0001() -> None:
    output, receipts = insert_hwpx_image(_template(), _insert(_png()))
    assert receipts[0].binary_item_id_ref == "BIN0001"
    assert (
        f"{HWPX_BIN_DATA_PREFIX}BIN0001.{HWPX_EMBEDDED_IMAGE_EXTENSION}"
        in _members(output)
    )
    assert _pictures(output) == [("BIN0001", 24 * 75, 16 * 75, ())]


def test_allocation_skips_ids_already_used_in_the_manifest() -> None:
    template = _template(
        manifest=_manifest(
            '<opf:item id="BIN0001" href="BinData/BIN0001.png" media-type="image/png" isEmbeded="1"/>'
        )
    )
    _, receipts = insert_hwpx_image(template, _insert(_png()))
    assert receipts[0].binary_item_id_ref == "BIN0002"


_MANIFEST_ITEM_BIN1 = '<opf:item id="BIN0001" href="BinData/BIN0001.png" media-type="image/png"/>'


def test_allocation_scans_header_ids() -> None:
    header = _HEADER.replace(
        b"<hh:refList/>",
        b'<hh:refList><hh:binItem id="1" BinData="BIN0002.png"/></hh:refList>',
    )
    template = _archive(
        [
            ("mimetype", HWPX_MEDIA_TYPE.encode("ascii")),
            ("version.xml", _VERSION),
            ("Contents/header.xml", header),
            ("Contents/section0.xml", _section_part("본문 0")),
            (HWPX_MANIFEST_MEMBER, _manifest(_MANIFEST_ITEM_BIN1)),
        ]
    )
    _, receipts = insert_hwpx_image(template, _insert(_png()))
    assert receipts[0].binary_item_id_ref == "BIN0003"


def test_allocation_scans_manifest_ids() -> None:
    # The manifest item id is ``image9``; only its href carries a BIN token.
    template = _template(
        manifest=_manifest(
            '<opf:item id="image9" href="BinData/BIN0001.png" media-type="image/png"/>'
        )
    )
    _, receipts = insert_hwpx_image(template, _insert(_png()))
    assert receipts[0].binary_item_id_ref == "BIN0002"


def test_allocation_scans_package_member_names() -> None:
    # A BinData member whose *name* carries the token, with neither the manifest
    # nor the header mentioning it.
    members: list[tuple[str, bytes]] = [
        ("mimetype", HWPX_MEDIA_TYPE.encode("ascii")),
        ("version.xml", _VERSION),
        ("Contents/header.xml", _HEADER),
        ("Contents/section0.xml", _section_part("본문 0")),
        (f"{HWPX_BIN_DATA_PREFIX}BIN0001.png", b"\x89PNG\r\n\x1a\n"),
        (HWPX_MANIFEST_MEMBER, _manifest()),
    ]
    _, receipts = insert_hwpx_image(_archive(members), _insert(_png()))
    assert receipts[0].binary_item_id_ref == "BIN0002"


def test_allocation_scans_section_part_references() -> None:
    # A section part that already mentions a BIN#### token must have that token
    # treated as taken, even though the reference is not an id-bearing attribute.
    section = _section_part("BIN0001").replace(b"</hp:linesegarray>", b"</hp:linesegarray>")
    assert b"BIN0001" in section
    template = _archive(
        [
            ("mimetype", HWPX_MEDIA_TYPE.encode("ascii")),
            ("Contents/header.xml", _HEADER),
            ("Contents/section0.xml", section),
            (HWPX_MANIFEST_MEMBER, _manifest()),
        ]
    )
    _, receipts = insert_hwpx_image(template, _insert(_png()))
    assert receipts[0].binary_item_id_ref == "BIN0002"


def test_multiple_insertions_allocate_ascending_distinct_ids() -> None:
    request = (
        HwpxImageInsertion(section_index=0, image=_png(8, 8)),
        HwpxImageInsertion(section_index=0, image=_png(9, 9)),
    )
    _, receipts = insert_hwpx_image(_template(), request)
    assert [receipt.binary_item_id_ref for receipt in receipts] == ["BIN0001", "BIN0002"]


def test_allocation_is_deterministic_across_runs() -> None:
    # Allocation takes the *lowest* free id, so a taken BIN0002 does not move
    # the answer past it.
    template = _template(
        manifest=_manifest(
            '<opf:item id="BIN0002" href="BinData/BIN0002.png" media-type="image/png"/>'
        )
    )
    ids = {insert_hwpx_image(template, _insert(_png()))[1][0].binary_item_id_ref for _ in range(3)}
    assert ids == {"BIN0001"}


def test_id_space_exhaustion_is_a_refusal_not_a_loop() -> None:
    # Every id in the grammar is already present somewhere in the package.
    items = "".join(
        f'<opf:item id="BIN{index:04d}" href="BinData/BIN{index:04d}.png" media-type="image/png"/>'
        for index in range(1, 10_000)
    )
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(_template(manifest=_manifest(items)), _insert(_png()))
    assert exc.value.code == "hwpx_image_id_exhausted"


# --------------------------------------------------------------------------- #
# Manifest, section and readback
# --------------------------------------------------------------------------- #


def test_manifest_gains_exactly_one_png_item_before_its_close_tag() -> None:
    output, _ = insert_hwpx_image(_template(), _insert(_png()))
    manifest = _members(output)[HWPX_MANIFEST_MEMBER]
    assert manifest.count(b'<opf:item id="BIN0001" href="BinData/BIN0001.png" media-type="image/png" isEmbeded="1"/>') == 1
    # The splice is additive: the original manifest bytes are still a subsequence
    # in order, and the new item sits immediately before the single close tag.
    assert manifest.index(b'isEmbeded="1"') < manifest.index(b"</opf:manifest>")
    assert manifest.endswith(b"</opf:package>")


def test_inserted_picture_reads_back_through_the_single_reader() -> None:
    output, receipts = insert_hwpx_image(_template(), _insert(_png(), width_hwpunit=14_400, height_hwpunit=9_600))
    (item_id, width, height, unsupported), = _pictures(output)
    assert (item_id, width, height, unsupported) == ("BIN0001", 14_400, 9_600, ())
    assert receipts[0].width_hwpunit == 14_400
    section_xml = _members(output)["Contents/section0.xml"]
    assert b'binaryItemIDRef="BIN0001"' in section_xml


def test_inserted_picture_paragraph_is_the_section_producer_bytes() -> None:
    output, _ = insert_hwpx_image(_template(), _insert(_png(), width_hwpunit=14_400, height_hwpunit=9_600))
    section_xml = _members(output)["Contents/section0.xml"]
    expected = serialize_hwpx_picture_paragraph(
        HwpxPicture(binary_item_id_ref="BIN0001", width_hwpunit=14_400, height_hwpunit=9_600)
    )
    assert expected in section_xml


def test_draw_extent_defaults_to_the_decoded_pixel_geometry() -> None:
    _, receipts = insert_hwpx_image(_template(), _insert(_png(40, 25)))
    (receipt,) = receipts
    assert (receipt.width_hwpunit, receipt.height_hwpunit) == (3_000, 1_875)
    assert (receipt.width_px, receipt.height_px) == (40, 25)


def test_a_single_declared_extent_derives_the_other_from_the_source_ratio() -> None:
    _, receipts = insert_hwpx_image(_template(), _insert(_png(40, 25), width_hwpunit=8_000))
    assert receipts[0].width_hwpunit == 8_000
    assert receipts[0].height_hwpunit == 5_000


def test_output_reenters_the_archive_gate() -> None:
    output, _ = insert_hwpx_image(_template(), _insert(_png()))
    assert validate_ooxml_archive(output) is None


def test_output_stays_readable_through_the_existing_text_reader() -> None:
    from padiem_ai_core.document_normalization import extract_hwpx_text

    output, _ = insert_hwpx_image(_template(), _insert(_png()))
    assert extract_hwpx_text(output) == "본문 0"


def test_output_is_a_valid_hwpx_for_the_existing_decoder_subset() -> None:
    # A from-scratch Core package plus a picture block is refused by the
    # from-scratch writer, because it owns no manifest to resolve the reference.
    from padiem_ai_core.hwpx_package_serializer import (
        HwpxPackageContent,
        HwpxPackageSection,
        HwpxSectionBlock,
    )

    content = HwpxPackageContent(
        sections=(
            HwpxPackageSection(
                paragraphs=("본문",),
                blocks=(
                    HwpxSectionBlock("paragraph", text="본문"),
                    HwpxSectionBlock(
                        "picture",
                        picture=HwpxPicture("BIN0001", 14_400, 9_600),
                    ),
                ),
            ),
        )
    )
    with pytest.raises(DocumentNormalizationError) as exc:
        serialize_hwpx_package(content)
    assert exc.value.code == "hwpx_serialize_picture_unsupported"


# --------------------------------------------------------------------------- #
# Preservation
# --------------------------------------------------------------------------- #


def test_unrelated_members_survive_byte_for_byte() -> None:
    template = _template()
    before = _members(template)
    output, _ = insert_hwpx_image(template, _insert(_png()))
    after = _members(output)
    for name, payload in before.items():
        if name in {HWPX_MANIFEST_MEMBER, "Contents/section0.xml"}:
            continue
        assert after[name] == payload, name


def test_the_target_section_keeps_every_byte_it_did_not_gain() -> None:
    template = _template()
    before = _members(template)["Contents/section0.xml"]
    output, _ = insert_hwpx_image(template, _insert(_png()))
    after = _members(output)["Contents/section0.xml"]
    assert after.startswith(before[: before.index(b"</hs:sec>")])
    assert after.endswith(b"</hs:sec>")
    assert len(after) > len(before)


def test_the_manifest_keeps_every_byte_it_did_not_gain() -> None:
    template = _template()
    before = _members(template)[HWPX_MANIFEST_MEMBER]
    output, _ = insert_hwpx_image(template, _insert(_png()))
    after = _members(output)[HWPX_MANIFEST_MEMBER]
    assert after.startswith(before[: before.index(b"</opf:manifest>")])
    assert after.endswith(before[before.index(b"</opf:manifest>") :])


def test_member_name_sequence_is_preserved_except_for_the_new_binary_member() -> None:
    template = _template()
    output, _ = insert_hwpx_image(template, _insert(_png()))
    assert [member.name for member in read_hwpx_package_members(output)] == [
        member.name for member in read_hwpx_package_members(template)
    ] + ["BinData/BIN0001.png"]


def test_untargeted_sections_are_untouched() -> None:
    template = _template(sections=2)
    output, _ = insert_hwpx_image(template, _insert(_png(), section_index=1))
    after = _members(output)
    assert after["Contents/section0.xml"] == _members(template)["Contents/section0.xml"]
    assert b"binaryItemIDRef" in after["Contents/section1.xml"]


def test_two_insertions_into_one_section_add_two_paragraphs() -> None:
    request = (
        HwpxImageInsertion(section_index=0, image=_png(8, 8)),
        HwpxImageInsertion(section_index=0, image=_png(9, 9)),
    )
    output, _ = insert_hwpx_image(_template(), request)
    section_xml = _members(output)["Contents/section0.xml"]
    assert section_xml.count(b"binaryItemIDRef") == 2
    # Document order is request order, not the reverse: both paragraphs are
    # spliced in one additive step ahead of the single section close.
    assert [item[0] for item in _pictures(output)] == ["BIN0001", "BIN0002"]


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


def _no_manifest() -> bytes:
    return _archive(
        [
            ("mimetype", HWPX_MEDIA_TYPE.encode("ascii")),
            ("Contents/section0.xml", _section_part("본문 0")),
        ]
    )


def test_package_without_a_manifest_is_refused() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(_no_manifest(), _insert(_png()))
    assert exc.value.code == "hwpx_image_manifest_missing"


def test_manifest_without_the_package_namespace_is_refused() -> None:
    manifest = _manifest().replace(b'xmlns:opf="http://www.idpf.org/2007/opf/"', b'xmlns:opf="urn:example:other"')
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(_template(manifest=manifest), _insert(_png()))
    assert exc.value.code == "hwpx_image_manifest_unsupported"


def test_manifest_without_a_single_anchor_is_refused() -> None:
    manifest = _manifest().replace(b"</opf:manifest>", b"")
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(_template(manifest=manifest), _insert(_png()))
    assert exc.value.code == "hwpx_image_manifest_unsupported"


def test_section_without_a_single_anchor_is_refused() -> None:
    # Well-formed XML, admitted by the single reader, but carrying no
    # ``</hs:sec>`` byte to splice before. A self-closing section root is the
    # only way to reach that: dropping the close tag instead would make the
    # member malformed XML and be refused by the reader before this authority
    # ever sees it.
    empty_section = (
        f'{_DECLARATION}<hs:sec xmlns:hs="{_SECTION_NS}" xmlns:hp="{_PARAGRAPH_NS}"'
        ' version="1.4"/>'
    ).encode("utf-8")
    template = _archive(
        [
            ("mimetype", HWPX_MEDIA_TYPE.encode("ascii")),
            ("Contents/header.xml", _HEADER),
            ("Contents/section0.xml", empty_section),
            (HWPX_MANIFEST_MEMBER, _manifest()),
        ]
    )
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(template, _insert(_png()))
    assert exc.value.code == "hwpx_image_section_unsupported"


def test_missing_section_is_refused() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(_template(), _insert(_png(), section_index=4))
    assert exc.value.code == "hwpx_image_section_missing"


def test_oversized_extent_is_refused_by_the_section_producer() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(_template(), _insert(_png(), width_hwpunit=1_000_001, height_hwpunit=1_000_001))
    assert exc.value.code == "hwpx_serialize_picture_dimension_limit"


def test_non_positive_extent_is_refused() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(_template(), _insert(_png(), width_hwpunit=0, height_hwpunit=1))
    assert exc.value.code == "hwpx_serialize_picture_dimension_limit"


def test_malformed_request_containers_fail_closed() -> None:
    template = _template()
    for bad, code in (
        ((), "hwpx_image_request"),
        ([HwpxImageInsertion(0, _png())], "hwpx_image_request"),
        (("not-an-insertion",), "hwpx_image_request"),
        ((HwpxImageInsertion(0, "not-bytes"),), "hwpx_image_request"),
        ((HwpxImageInsertion(True, _png()),), "hwpx_image_index_type"),
        ((HwpxImageInsertion(-1, _png()),), "hwpx_image_index_negative"),
        ((HwpxImageInsertion(0, _png(), width_hwpunit="wide"),), "hwpx_image_extent_type"),
    ):
        with pytest.raises(DocumentNormalizationError) as exc:
            insert_hwpx_image(template, bad)  # type: ignore[arg-type]
        assert exc.value.code == code, bad


def test_too_many_insertions_are_refused() -> None:
    request = tuple(
        HwpxImageInsertion(section_index=0, image=_png(4, 4)) for _ in range(MAX_HWPX_IMAGE_INSERTIONS + 1)
    )
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(_template(), request)
    assert exc.value.code == "hwpx_image_limit"


def test_source_is_admitted_before_the_instruction_is_judged() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(b"PK\x03\x04 not an archive", ())
    assert exc.value.code == "ooxml_malformed"


def test_malformed_source_fails_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        insert_hwpx_image(b"not a zip at all", _insert(_png()))
    assert exc.value.code == "ooxml_malformed"


def test_refusal_messages_carry_no_xml_member_names_or_paths() -> None:
    refusals = (
        lambda: insert_hwpx_image(_template(manifest=_manifest().replace(b"</opf:manifest>", b"")), _insert(_png())),
        lambda: insert_hwpx_image(_no_manifest(), _insert(_png())),
        lambda: insert_hwpx_image(_template(), _insert(_png(), section_index=9)),
        lambda: insert_hwpx_image(_template(), _insert(b"garbage")),
    )
    for refuse in refusals:
        with pytest.raises(DocumentNormalizationError) as exc:
            refuse()
        message = str(exc.value) + exc.value.code
        for forbidden in ("<hp:", "<opf:", "</hs:sec>", "Contents/", "section0.xml", "BinData/", "C:\\", "/tmp/"):
            assert forbidden not in message, forbidden


# --------------------------------------------------------------------------- #
# Authority boundaries, proven by source scan
# --------------------------------------------------------------------------- #


def test_public_request_carries_no_raw_xml_path_or_relationship_authority() -> None:
    signature = inspect.signature(insert_hwpx_image)
    assert list(signature.parameters) == ["payload", "insertions"]
    for name in HwpxImageInsertion.__dataclass_fields__:
        assert name not in {
            "xml",
            "member_name",
            "member_path",
            "path",
            "relationship_id",
            "r_id",
            "namespace",
            "manifest_id",
            "item_id",
            "shape_id",
            "style_id",
            "media_type",
        }


def test_module_owns_no_archive_writer_xml_parser_or_image_decoder() -> None:
    source = _code()
    # One archive writer, reached through the existing private seam.
    assert "ZipFile(" not in source
    assert "writestr(" not in source
    assert "_assemble_hwpx_package_members" in source
    # No XML parsing of its own.
    for forbidden in ("ElementTree", "fromstring(", "minidom", "lxml", "etree"):
        assert forbidden not in source, forbidden
    # No host, process or network surface.
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
    ):
        assert forbidden not in source, forbidden
    # The archive gate is reached only through the existing authorities.
    assert "validate_ooxml_archive(" in source
    assert "read_hwpx_package_members(" in source
    assert "parse_hwpx_sections(" in source
    assert "read_hwpx_section_facts(" in source


def test_module_does_not_write_a_header_bin_data_list() -> None:
    # The header is scanned for id collisions but never patched: the official
    # read chain does not use one and no available fixture carries one.
    source = _code()
    assert "binDataList" not in source
    assert "binItem" not in source
    assert "Contents/header.xml" not in source


def test_serializer_picture_producer_and_reader_agree_on_one_shape() -> None:
    from padiem_ai_core.document_normalization import HWPX_PICTURE_CHILD_NAMES

    picture = HwpxPicture("BIN0001", 14_400, 9_600)
    paragraph = serialize_hwpx_picture_paragraph(picture)
    assert paragraph.startswith(b"<hp:p><hp:runs><hp:pic ")
    # Self-contained: the core namespace is declared on the picture itself.
    assert b'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"' in paragraph
    import xml.etree.ElementTree as ElementTree

    # The paragraph is spliced into a section root that already declares the
    # paragraph namespace, so it is parsed here inside an equivalent root
    # rather than as a standalone document.
    root = ElementTree.fromstring(
        f'<hs:sec xmlns:hs="{_SECTION_NS}" xmlns:hp="{_PARAGRAPH_NS}">'.encode("utf-8")
        + paragraph
        + b"</hs:sec>"
    )
    (picture_element,) = [node for node in root.iter() if node.tag.endswith("}pic")]
    assert tuple(node.tag.rsplit("}", 1)[-1] for node in picture_element) == HWPX_PICTURE_CHILD_NAMES


def test_every_receipt_is_bounded_and_payload_free() -> None:
    _, receipts = insert_hwpx_image(_template(), _insert(_png()))
    (receipt,) = receipts
    projection = receipt.safe_dict()
    assert set(projection) == {
        "section_index",
        "binary_item_id_ref",
        "media_type",
        "source_format",
        "width_hwpunit",
        "height_hwpunit",
        "width_px",
        "height_px",
        "image_bytes",
    }
    assert not any(isinstance(value, (bytes, bytearray)) for value in projection.values())
    assert all(isinstance(value, (int, str)) for value in projection.values())


def test_receipt_never_contains_the_image_bytes() -> None:
    image = _png()
    _, receipts = insert_hwpx_image(_template(), _insert(image))
    assert image not in repr(receipts[0]).encode("latin-1", "ignore")
    assert receipts[0].image_bytes > 0
