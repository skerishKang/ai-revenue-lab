# -*- coding: utf-8 -*-
"""#3679 bounded-archive contract for the generic B66 analyzer.

Fifteen proofs:

1.  a valid workbook still analyzes, and the committed fixture's analysis is unchanged;
2.  too many entries is refused;
3.  one oversized member is refused;
4.  aggregate uncompressed bytes past the total budget are refused;
5.  an extreme expansion ratio is refused even inside the byte caps;
6.  ``../`` traversal is refused;
7.  an absolute member path is refused;
8.  an encrypted member is refused with a deterministic code;
9.  a duplicate member the analyzer reads is refused rather than silently first-wins;
10. a malformed / truncated archive is refused, never skipped;
11. malformed XML inside an otherwise in-budget member is a bounded failure;
12. the optional drawings / rels / sharedStrings / VML routes still work;
13. a member read can never exceed the configured bound;
14. the bounded reader does not materialize the payload before the limit (peak-memory control
    against the unsized ``ZipFile.read`` it replaces) -- the #3637 measurement re-aimed here;
15. the analyzer's bounds equal Core's canonical constants whenever Core is importable.

Fixtures are built in-process; nothing here reads a customer document, and the only committed
fixture used is the public-safe synthetic one already in this directory.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import tracemalloc
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
REPO_ROOT = TOOLS.parent.parent
FIXTURES = HERE / "fixtures"

sys.path.insert(0, str(TOOLS))
import analyze  # noqa: E402

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_R}">'
    '<sheets><sheet name="견적서" sheetId="1" r:id="rId1"/></sheets>'
    "</workbook>"
).encode()
WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
    "</Relationships>"
).encode()
STYLES = (
    f'<styleSheet xmlns="{NS_MAIN}">'
    "<fonts><font><name val=\"Arial\"/><sz val=\"10\"/></font></fonts>"
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="0"/></numFmts>'
    '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs>'
    "</styleSheet>"
).encode()
SHEET = (
    f'<worksheet xmlns="{NS_MAIN}"><dimension ref="A1:B2"/>'
    '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData>'
    "</worksheet>"
).encode()
SHARED = f'<sst xmlns="{NS_MAIN}" count="1" uniqueCount="1"><si><t>견적번호</t></si></sst>'.encode()


def xlsx_bytes(extra=None, overrides=None):
    """A minimal but genuinely parseable XLSX, plus any caller-supplied members."""

    members = {
        "[Content_Types].xml": "<Types/>",
        "_rels/.rels": "<Relationships "
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        "xl/workbook.xml": WORKBOOK,
        "xl/_rels/workbook.xml.rels": WORKBOOK_RELS,
        "xl/styles.xml": STYLES,
        "xl/sharedStrings.xml": SHARED,
        "xl/worksheets/sheet1.xml": SHEET,
    }
    members.update(overrides or {})
    for name, payload in (extra or {}).items():
        members[name] = payload
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buf.getvalue()


def write(tmp_path, payload, name="source.xlsx"):
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def code_for(tmp_path, payload, name="source.xlsx"):
    """Run the gate and return the refusal code, or ``None`` when it is accepted."""

    try:
        return analyze.analyze_xlsx(write(tmp_path, payload, name))
    except analyze.ArchivePolicyError as exc:
        assert exc.code, "every refusal must carry a code"
        return exc.code


# --------------------------------------------------------------------------- #
# 1. valid input
# --------------------------------------------------------------------------- #


def test_valid_workbook_is_accepted(tmp_path):
    result = code_for(tmp_path, xlsx_bytes())
    assert isinstance(result, dict), result
    assert result["sheet_names"] == ["견적서"]
    assert "견적번호" in json.dumps(result["sheets"], ensure_ascii=False)


def test_committed_fixture_analysis_is_unchanged():
    """Golden facts for the public-safe synthetic fixture: the hardening must not move them."""

    result = analyze.analyze_xlsx(FIXTURES / "source.xlsx")
    assert result["source"]["size"] == 2875
    assert len(result["source"]["sha256"]) == 64
    assert result["sheet_names"] == ["견적서"]
    assert result["workbook"]["sheets"][0]["name"] == "견적서"
    assert result["styles"]["fonts"] and result["styles"]["fonts"][0]["name"]
    assert result["sheets"]["견적서"]["dimension"]
    assert json.dumps(result["vml_shapes"], ensure_ascii=False) is not None


# --------------------------------------------------------------------------- #
# 2-5. budget refusals
# --------------------------------------------------------------------------- #


def test_too_many_entries_is_refused(tmp_path):
    payload = xlsx_bytes(extra={f"xl/filler{i}.xml": "<a/>" for i in range(300)})
    assert code_for(tmp_path, payload) == "ooxml_entry_count"


def test_one_oversized_member_is_refused(tmp_path):
    big = "x" * (analyze.MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES + 1)
    assert code_for(tmp_path, xlsx_bytes(overrides={"xl/workbook.xml": big})) == "ooxml_entry_size"


def test_aggregate_uncompressed_bytes_are_refused(tmp_path):
    """Every member sits inside the per-entry cap; the running total is what fails.

    The fillers are ~6x-compressible, so the raw archive stays under the 2 MiB input ceiling and
    each member stays under the 1 MiB per-entry ceiling and the 200x ratio cap. Only the running
    total crosses a bound.
    """

    names = {f"xl/filler{i}.xml": filler(950 * 1024, seed=i, alphabet=2) for i in range(9)}
    payload = xlsx_bytes(extra=names)
    assert sum(len(value) for value in names.values()) > analyze.MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES
    assert all(len(value) <= analyze.MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES for value in names.values())
    assert len(payload) <= analyze.MAX_BINARY_DOCUMENT_BYTES, "raw ceiling must not fire first"
    assert code_for(tmp_path, payload) == "ooxml_total_size"


def test_extreme_expansion_ratio_is_refused(tmp_path):
    """Declared size inside every byte cap, but compressed -> uncompressed far past 200x."""

    repetitive = "A" * (900 * 1024)  # deflate crushes this to a few hundred bytes
    payload = xlsx_bytes(overrides={"xl/filler.xml": repetitive})
    assert code_for(tmp_path, payload) == "ooxml_expansion_ratio"


# --------------------------------------------------------------------------- #
# 6-9. path and member classification
# --------------------------------------------------------------------------- #


def test_traversal_member_is_refused(tmp_path):
    assert code_for(tmp_path, xlsx_bytes(extra={"xl/../evil.xml": "<a/>"})) == "ooxml_unsafe_path"


def test_absolute_member_path_is_refused(tmp_path):
    assert code_for(tmp_path, xlsx_bytes(extra={"/etc/passwd": "x"})) == "ooxml_unsafe_path"


def test_backslash_and_drive_member_forms_are_rejected_by_the_predicate():
    """zipfile rewrites the backslash form to ``/`` on write, so this is proven where names are judged.

    The route-level traversal and absolute-path refusals above are the forms a crafted archive can
    actually deliver through ``ZipFile.writestr``; these two are rejected by the predicate itself.
    """

    assert analyze._safe_ooxml_member("xl\\evil.xml") is False
    assert analyze._safe_ooxml_member("C:x.xml") is False
    assert analyze._safe_ooxml_member("xl//workbook.xml") is False
    assert analyze._safe_ooxml_member("xl/workbook.xml") is True
    # PurePosixPath normalizes a single dot away, so this form is not traversal and both predicates
    # accept it. Pinned as parity below rather than asserted as a rejection.
    assert analyze._safe_ooxml_member("xl/./workbook.xml") is True


def test_encrypted_member_is_refused_deterministically(tmp_path):
    payload = bytearray(xlsx_bytes())
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        local_offsets = [info.header_offset for info in archive.infolist()]

    # Flag bits sit at +8 in a central-directory record and +6 in a local file header; zipfile has
    # no API to emit an encrypted entry, so the bits are set on the encoded archive directly.
    cursor = payload.find(b"PK\x01\x02")
    while cursor != -1:
        payload[cursor + 8] |= 0x01
        cursor = payload.find(b"PK\x01\x02", cursor + 4)
    for offset in local_offsets:
        payload[offset + 6] |= 0x01

    assert code_for(tmp_path, bytes(payload)) == "ooxml_encrypted"


def test_duplicate_read_member_is_refused(tmp_path):
    buf = BytesIO()
    # zipfile itself warns about the collision; the refusal under test is what the analyzer does
    # about it, so the warning is asserted rather than left as suite noise.
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", WORKBOOK)
            archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
            archive.writestr("xl/styles.xml", STYLES)
            archive.writestr("xl/worksheets/sheet1.xml", SHEET)
            archive.writestr("[Content_Types].xml", "<Types/>")
            # A second copy of a member the analyzer must read: ZipFile.read would silently
            # return the first, hiding the ambiguity.
            archive.writestr("xl/workbook.xml", WORKBOOK.replace(b"rId1", b"rId9"))
    assert code_for(tmp_path, buf.getvalue()) == "ooxml_duplicate_member"


# --------------------------------------------------------------------------- #
# 10-11. malformed input
# --------------------------------------------------------------------------- #


def test_truncated_archive_is_refused_not_skipped(tmp_path):
    payload = xlsx_bytes()
    assert code_for(tmp_path, payload[: len(payload) // 2]) == "ooxml_malformed"


def test_non_archive_bytes_are_refused(tmp_path):
    assert code_for(tmp_path, b"PK\x03\x04" + b"garbage" * 40) == "ooxml_malformed"


def test_empty_file_is_refused(tmp_path):
    assert code_for(tmp_path, b"") == "ooxml_archive_size"


def test_malformed_xml_inside_a_bounded_member_fails_closed(tmp_path):
    broken = b'<workbook xmlns="%s"><sheets>' % NS_MAIN.encode()  # never closed
    assert code_for(tmp_path, xlsx_bytes(overrides={"xl/workbook.xml": broken})) == (
        "ooxml_invalid_xml"
    )


# --------------------------------------------------------------------------- #
# 12. optional routes still work
# --------------------------------------------------------------------------- #


def test_drawing_rels_shared_strings_and_vml_routes_still_produce_facts(tmp_path):
    drawing = (
        f'<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/'
        f'spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<xdr:twoCellAnchor>'
        '<xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff>'
        '<xdr:row>0</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
        '<xdr:to><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff>'
        '<xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>'
        '<xdr:pic><xdr:nvPicPr><xdr:cNvPr name="Picture 1"/>'
        '<xdr:cNvPicPr/></xdr:nvPicPr>'
        '<xdr:blipFill><a:blip r:embed="rId1" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
        "</xdr:blipFill></xdr:pic></xdr:twoCellAnchor></xdr:wsDr>"
    ).encode()
    drawing_rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="../media/logo.png" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"/>'
        "</Relationships>"
    ).encode()
    vml = (
        '<xml><v:shapes xmlns:v="urn:schemas-microsoft-com:vml">'
        '<v:shape id="Camera1"><x:Anchor>1,0,1,0,2,0,2,0</x:Anchor>'
        '<x:FmlaPict>0</x:FmlaPict><x:Camera/><v:imagedata o:relid="rId2"/></v:shape>'
        "</v:shapes></xml>"
    ).encode()

    payload = xlsx_bytes(
        extra={
            "xl/drawings/drawing1.xml": drawing,
            "xl/drawings/_rels/drawing1.xml.rels": drawing_rels,
            "xl/media/logo.png": b"\x89PNG\r\n\x1a\n" + b"logo-bytes",
            "xl/drawings/vmlDrawing1.vml": vml,
        }
    )
    result = code_for(tmp_path, payload)
    assert isinstance(result, dict), result

    images = result["drawing_images"]
    assert [i["name"] for i in images] == ["Picture 1"]
    assert images[0]["media"] == "xl/media/logo.png"
    assert images[0]["sha256"] and len(images[0]["sha256"]) == 64
    assert images[0]["from"] == {"col": 0, "col_off_emu": 0, "row": 0, "row_off_emu": 0}
    assert [s["shape_id"] for s in result["vml_shapes"]] == ["Camera1"]
    assert result["vml_shapes"][0]["is_camera"] is True
    assert "견적번호" in json.dumps(result["sheets"], ensure_ascii=False)


def test_embedded_archive_is_not_recursed(tmp_path):
    """Nested depth is 0 by construction: an embedded zip is media, never a second gate."""

    inner = BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("xl/workbook.xml", b"<workbook/>")
    payload = xlsx_bytes(extra={"xl/embeddings/oleObject1.bin": inner.getvalue()})
    result = code_for(tmp_path, payload)
    assert isinstance(result, dict), result
    assert "xl/embeddings/oleObject1.bin" not in json.dumps(result["sheets"], ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 13-14. the bounded read itself
# --------------------------------------------------------------------------- #


def _central_directory_walk(data):
    """Yield ``(record_offset, name, uncompressed_size_field_offset)`` for every CD record.

    Central-directory fields are length-prefixed, not NUL-terminated: the filename starts at +46 and
    its length is the uint16 at +28, so the record cannot be found by scanning for a separator.
    """

    cursor = 0
    while True:
        offset = data.find(b"PK\x01\x02", cursor)
        if offset == -1:
            return
        name_len = struct.unpack_from("<H", data, offset + 28)[0]
        extra_len = struct.unpack_from("<H", data, offset + 30)[0]
        comment_len = struct.unpack_from("<H", data, offset + 32)[0]
        name = bytes(data[offset + 46 : offset + 46 + name_len]).decode("utf-8", "ignore")
        yield offset, name, offset + 24
        cursor = offset + 46 + name_len + extra_len + comment_len


def forge_declared_sizes(payload: bytes, declared: dict) -> bytes:
    """Rewrite members' declared uncompressed sizes, leaving the real streams intact.

    This is the #3637 lie in both directions: ``ZipFile.read`` inflates the actual stream and
    truncates afterwards, so a bound computed from declared metadata alone is a claim, not a ceiling.
    """

    data = bytearray(payload)
    with zipfile.ZipFile(BytesIO(data)) as archive:
        local_offsets = {info.filename: info.header_offset for info in archive.infolist()}

    for offset, name, size_field in _central_directory_walk(data):
        if name not in declared:
            continue
        value = declared[name]
        struct.pack_into("<I", data, size_field, value)
        struct.pack_into("<I", data, local_offsets[name] + 22, value)
    return bytes(data)


def filler(size: int, seed: int = 0, alphabet: int = 256) -> bytes:
    """Random byte content with a measured compression factor.

    ``alphabet=256`` is incompressible (deflate ratio ~1.0), so an unrelated expansion-ratio bound
    cannot fire first. ``alphabet=2`` compresses ~6x, which keeps the raw archive under the 2 MiB
    input ceiling while letting declared bytes accumulate past the 8 MiB total budget.
    Measured in this environment: k=256 -> 1.00, k=8 -> 2.31, k=2 -> 6.18.
    """

    import random

    rng = random.Random(seed)
    values = [min(255, i * (256 // alphabet)) for i in range(alphabet)]
    return bytes(rng.choice(values) for _ in range(size))


def read_bound_payload(tmp_path):
    """A member declaring 64 bytes over ~6 MiB of real deflate output."""

    payload = xlsx_bytes(overrides={"xl/filler.xml": "Z" * (6 * 1024 * 1024)})
    return forge_declared_sizes(payload, {"xl/filler.xml": 64})


def test_member_read_cannot_exceed_the_configured_bound(tmp_path):
    """A lying member is either capped or refused -- never handed back whole."""

    raw, archive = analyze.open_bounded_ooxml(write(tmp_path, read_bound_payload(tmp_path)))
    try:
        with pytest.raises(analyze.ArchivePolicyError) as excinfo:
            archive.read("xl/filler.xml")
        assert excinfo.value.code == "ooxml_malformed"
    finally:
        archive.close()


def test_bounded_read_does_not_materialize_the_payload(tmp_path):
    """Peak memory control against the call this child replaces.

    Same forged archive, two readers. The unsized ``ZipFile.read`` has to inflate the whole stream
    before it can apply the declared size, so it peaks at roughly the real payload even though it
    then rejects the CRC; the bounded reader caps real inflate work at the declared size and rejects
    for the same reason three orders of magnitude cheaper. Both fail closed -- only one does it
    after amplifying.
    """

    path = write(tmp_path, read_bound_payload(tmp_path))

    with zipfile.ZipFile(path) as plain:
        tracemalloc.start()
        try:
            plain.read("xl/filler.xml")
        except (zipfile.BadZipFile, ValueError):
            pass
        peak_unsized = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()

    raw, archive = analyze.open_bounded_ooxml(path)
    try:
        tracemalloc.start()
        try:
            archive.read("xl/filler.xml")
        except analyze.ArchivePolicyError:
            pass
        peak_bounded = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    finally:
        archive.close()

    assert peak_bounded < 1024 * 1024, f"bounded reader peaked at {peak_bounded} bytes"
    assert peak_unsized > 4 * 1024 * 1024, f"unsized read only peaked at {peak_unsized} bytes"


def test_analyzer_refuses_a_lying_member_instead_of_amplifying(tmp_path):
    """The whole route, not just the helper.

    The lie is placed on ``xl/workbook.xml``, which the analyzer must read. Forging a member the
    analyzer never opens would prove nothing: nothing reads it, so nothing is amplified.
    """

    bloated = b"<workbook/>" + b"W" * (6 * 1024 * 1024)
    payload = xlsx_bytes(overrides={"xl/workbook.xml": bloated})
    forged = forge_declared_sizes(payload, {"xl/workbook.xml": len(WORKBOOK)})
    assert code_for(tmp_path, forged) == "ooxml_malformed"


def test_read_is_refused_when_actual_bytes_outrun_the_limit(tmp_path):
    """``min(file_size, max_bytes)`` must reject, not silently truncate, an over-limit member."""

    payload = xlsx_bytes(overrides={"xl/workbook.xml": filler(4096, seed=7)})
    raw, archive = analyze.open_bounded_ooxml(write(tmp_path, payload))
    try:
        with pytest.raises(analyze.ArchivePolicyError) as excinfo:
            archive.read("xl/workbook.xml", max_bytes=1024)
        assert excinfo.value.code == "ooxml_entry_size"
    finally:
        archive.close()


# --------------------------------------------------------------------------- #
# 15. single authority for the numbers
# --------------------------------------------------------------------------- #


def test_no_unbounded_member_read_left_in_the_analyzer():
    """Audit the source: one archive construction, and the XLSX route never touches zipfile."""

    source = (TOOLS / "analyze.py").read_text(encoding="utf-8-sig")
    assert source.count("zipfile.ZipFile(") == 1, "only the gate may open an archive"

    start = source.index("def analyze_xlsx")
    end = source.index("def analyze_pdf")
    xlsx_route = source[start:end]
    assert "zipfile." not in xlsx_route, "the XLSX route must read only through BoundedOOXML"
    assert "zf.read_xml(" in xlsx_route and "zf.read(" in xlsx_route


def _core_authority():
    """Core's canonical module, but only when it is *this* checkout's Core.

    A shared interpreter can resolve ``padiem_ai_core`` into a concurrent worktree (#3658). Parity
    against that copy would be a false signal -- it would certify agreement with a version of Core
    that this branch does not contain -- so the comparison is skipped instead.
    """

    core = pytest.importorskip("padiem_ai_core.document_normalization")
    origin = Path(core.__file__).resolve()
    if not str(origin).startswith(str(REPO_ROOT)):
        pytest.skip(f"padiem_ai_core resolves outside this checkout ({origin}); #3658 preflight")
    return core


@pytest.mark.parametrize(
    "name",
    [
        "MAX_OOXML_ENTRIES",
        "MAX_OOXML_MEMBER_NAME_CHARS",
        "MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES",
        "MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES",
        "MAX_BINARY_DOCUMENT_BYTES",
    ],
)
def test_bounds_equal_the_canonical_core_values(name):
    """Divergence between the analyzer's mirror and Core's authority fails here, not in production."""

    core = _core_authority()
    assert getattr(analyze, name) == getattr(core, name)


def test_safe_member_predicate_matches_core():
    core = _core_authority()
    for name in ("xl/workbook.xml", "../evil", "/abs", "a\\b", "C:x", "", "..", "x/../y",
                 "xl/./workbook.xml", "xl//workbook.xml", "x" * 300):
        assert analyze._safe_ooxml_member(name) is core._safe_ooxml_member(name), name


# --------------------------------------------------------------------------- #
# CLI refusal surface
# --------------------------------------------------------------------------- #


def test_cli_refuses_with_a_code_and_writes_no_evidence(tmp_path):
    bad = write(tmp_path, xlsx_bytes(extra={"xl/../evil.xml": "<a/>"}))
    pdf = FIXTURES / "reference.pdf"
    out = tmp_path / "evidence"
    proc = subprocess.run(
        [sys.executable, str(TOOLS / "analyze.py"), "--xlsx", str(bad), "--pdf", str(pdf),
         "--outdir", str(out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "REFUSED ooxml_unsafe_path" in proc.stderr
    assert not (out / "xlsx_analysis.json").exists()
