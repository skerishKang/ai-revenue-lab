"""Load-bearing lower-frame regressions; source composition needs no host fonts."""
from __future__ import annotations

from io import BytesIO
import importlib.util
import math
import os
from pathlib import Path
import sys

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, DecodedStreamObject, NameObject


APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]
BUNDLE = Path(os.environ.get("B66_SOL61_BUNDLE_DIR", str(
    REPO / "reference/b66-public-standard-templates/cgi/v1/sol61")))
SPEC = importlib.util.spec_from_file_location("frame_renderer_under_test", APP / "sol61_multipage.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
EPS = 0.001
DARK = 160
SCENARIOS = [(False, True, 3), (False, False, 10), (True, False, 5)]


@pytest.fixture
def engine():
    return M.SolMultipage(BUNDLE / "template", node=os.environ.get("B66_SOL61_NODE", "node"))


def black_segments(raw, reader):
    """Decode stroke geometry independently of the renderer's primitive lists."""
    stream = DecodedStreamObject()
    stream.set_data(raw)
    cm, width, color, stack = [1, 0, 0, 1, 0, 0], 1.0, [0, 0, 0], []
    current, start, segments = None, None, []

    def point(x, y):
        return (x*cm[0]+y*cm[2]+cm[4], x*cm[1]+y*cm[3]+cm[5])

    for args, op in ContentStream(stream, reader).operations:
        if op == b"q":
            stack.append((cm[:], width, color[:]))
        elif op == b"Q":
            cm, width, color = stack.pop()
        elif op == b"cm":
            cm = M._mul([float(v) for v in args], cm)
        elif op == b"w":
            width = float(args[0])
        elif op == b"G":
            color = [float(args[0])]*3
        elif op == b"RG":
            color = [float(v) for v in args]
        elif op == b"m":
            current = start = point(*map(float, args))
        elif op == b"l":
            end = point(*map(float, args))
            if current is not None:
                segments.append((current, end))
            current = end
        elif op == b"h":
            if current is not None and start is not None:
                segments.append((current, start))
                current = start
        elif op == b"re":
            x, y, w, h = map(float, args)
            corners = [point(x, y), point(x+w, y), point(x+w, y+h), point(x, y+h)]
            segments.extend(zip(corners, corners[1:]+corners[:1]))
            current = start = corners[0]
        elif op in (b"n", b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
            if op in (b"S", b"s", b"B", b"B*", b"b", b"b*") and color == [0, 0, 0]:
                for a, b in segments:
                    yield (a, b, width*abs(cm[0]))
            current, start, segments = None, None, []


def intervals(segments, axis, position, width=0.72):
    result = []
    for a, b, w in segments:
        fixed = 0 if axis == "vertical" else 1
        variable = 1-fixed
        if (abs(w-width) < EPS and abs(a[fixed]-position) < EPS
                and abs(b[fixed]-position) < EPS):
            result.append(sorted((a[variable], b[variable])))
    return result


def assert_single_coverage(spans, low, high, label):
    relevant = [(max(a, low), min(b, high)) for a, b in spans if b > low+EPS and a < high-EPS]
    cuts = sorted({low, high, *(v for span in relevant for v in span)})
    for a, b in zip(cuts, cuts[1:]):
        if b-a <= EPS:
            continue
        midpoint = (a+b)/2
        owners = sum(start-EPS < midpoint < end+EPS for start, end in relevant)
        assert owners == 1, f"{label}: coverage={owners} on [{a:.3f},{b:.3f}]"


def assert_frame(raw, reader, eng):
    segments = list(black_segments(raw, reader))
    low, high = eng.height-eng.frame_bottom, eng.height-eng.frame_top
    assert_single_coverage(intervals(segments, "vertical", eng.frame_left), low, high, "left")
    assert_single_coverage(intervals(segments, "vertical", eng.frame_right), low, high, "right")
    assert_single_coverage(intervals(segments, "horizontal", high), eng.frame_left, eng.frame_right, "top")
    assert_single_coverage(intervals(segments, "horizontal", low), eng.frame_left, eng.frame_right, "bottom")


def compose(eng, summary, body_art, count):
    bottoms = [eng.body_top+(i+1)*eng.row_pitch for i in range(count)]
    skeleton = eng._skeleton(summary, body_art, bottoms[-1])
    grid = eng._grid(bottoms)
    return skeleton+grid, skeleton, grid, bottoms


def test_outer_anchors_match_the_source_without_rounding(engine):
    assert (engine.frame_left, engine.frame_right) == pytest.approx((24.587, 572.572))
    assert (engine.frame_top, engine.frame_bottom) == pytest.approx((270.424, 605.218))
    assert engine.columns[0] == engine.frame_left
    assert engine.columns[-1] == engine.frame_right


@pytest.mark.parametrize("summary,body_art,count", SCENARIOS)
def test_all_four_boundaries_have_exactly_one_native_owner(engine, summary, body_art, count):
    raw, _, _, _ = compose(engine, summary, body_art, count)
    assert_frame(raw, engine.program.reader, engine)


@pytest.mark.parametrize("summary,body_art,count", SCENARIOS)
def test_generated_rows_own_only_their_interior_grid(engine, summary, body_art, count):
    _, skeleton, grid, bottoms = compose(engine, summary, body_art, count)
    source = list(black_segments(skeleton, engine.program.reader))
    generated = list(black_segments(grid, engine.program.reader))
    low, high = engine.height-bottoms[-1], engine.height-engine.body_top
    inherited_body_columns = [(a, b) for a, b, width in source
                              if abs(width-engine.rule_width) < EPS and abs(a[0]-b[0]) < EPS
                              and engine.frame_left+EPS < a[0] < engine.frame_right-EPS
                              and max(a[1], b[1]) > low+EPS and min(a[1], b[1]) < high-EPS]
    assert not inherited_body_columns, "Native column fragments overlap the generated body"
    for x in engine.columns[1:-1]:
        assert_single_coverage(intervals(generated, "vertical", x), low, high, f"generated column {x}")
    assert not intervals(generated, "vertical", engine.frame_left)
    assert not intervals(generated, "vertical", engine.frame_right)
    rows = [s for s in generated if abs(s[0][1]-s[1][1]) < EPS]
    assert len(rows) == len(bottoms)
    for bottom in bottoms:
        assert_single_coverage(intervals(generated, "horizontal", engine.height-bottom, engine.hair_width),
                               engine.frame_left, engine.frame_right, f"row bottom {bottom}")


@pytest.mark.parametrize("summary,body_art,count", SCENARIOS)
def test_body_top_header_and_footer_are_retained(engine, summary, body_art, count):
    _, skeleton, _, _ = compose(engine, summary, body_art, count)
    segments = list(black_segments(skeleton, engine.program.reader))
    assert_single_coverage(intervals(segments, "horizontal", engine.height-engine.body_top, engine.hair_width),
                           engine.frame_left, engine.frame_right, "original body top")
    # The native first column spans both the column header and the old body.
    assert_single_coverage(intervals(segments, "vertical", 53.851),
                           engine.height-engine.body_top, engine.height-299.552, "header first column")
    # This native rule crosses summary/footer; its footer portion must survive on every page.
    assert_single_coverage(intervals(segments, "vertical", 184.221),
                           engine.height-engine.frame_bottom, engine.height-engine.footer_top, "footer column")
    footer_runs = [r for r in engine.constants() if r["top"] >= engine.footer_top]
    assert footer_runs
    assert all(engine.program.emit_run(r) in skeleton for r in footer_runs)
    for image in engine.program.images:
        assert f"{image['name']} Do\n".encode() in skeleton


@pytest.mark.parametrize("n", [4, 8, 25, 100])
def test_last_page_budget_uses_the_summary_cell_boundary(engine, n):
    assert engine.totals_top == pytest.approx(518.313)
    heights = [28.0 if i % 5 == 0 else engine.row_pitch for i in range(n)]
    plan = engine.plan(n, heights)
    assert sum(p["rows"] for p in plan) == n
    last = plan[-1]
    assert last["kind"] == "last"
    first = last["first_row_index"]
    bottom = engine.body_top+sum(heights[first:first+last["rows"]])
    assert bottom <= min(engine.binds[k]["bbox"][1] for k in M.TOTALS_KEYS)-M.ROW_CLEARANCE+EPS


def test_disabling_source_edge_ownership_reproduces_the_gap(engine, monkeypatch):
    monkeypatch.setattr(engine, "_is_outer_frame_rule", lambda line: False)
    raw, _, _, _ = compose(engine, True, False, 5)
    with pytest.raises(AssertionError, match="right: coverage=0"):
        assert_frame(raw, engine.program.reader, engine)


def test_removing_final_native_right_segment_is_detected(engine):
    before = len(engine.program.lines)
    engine.program.lines = [line for line in engine.program.lines
                            if not (abs(line["box"][0]-engine.frame_right) < EPS
                                    and engine._is_outer_frame_rule(line)
                                    and abs(engine.height-line["box"][1]-engine.frame_bottom) < EPS)]
    assert len(engine.program.lines) == before-1
    raw, _, _, _ = compose(engine, True, False, 5)
    with pytest.raises(AssertionError, match="right: coverage=0"):
        assert_frame(raw, engine.program.reader, engine)


def test_frozen_pre_fix_pdf_is_a_failing_control(engine):
    baseline = os.environ.get("B66_SOL61_PRE_FIX_PDF")
    if not baseline:
        pytest.skip("Set B66_SOL61_PRE_FIX_PDF to the frozen pre-fix 8-item PDF")
    reader = PdfReader(baseline)
    assert len(reader.pages) > 1
    with pytest.raises(AssertionError, match="right: coverage=0"):
        assert_frame(reader.pages[-1].get_contents().get_data(), reader, engine)


def source_seal_footprint(eng):
    seals = [image for image in eng.program.images if image["name"] == "/Im4"]
    assert len(seals) == 1
    corners = [M._pt(seals[0]["cm"], x, y) for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
    xs, ys = zip(*corners)
    return min(xs), eng.height-max(ys), max(xs), eng.height-min(ys)


def without_seal_for_intrinsic_probe(eng, raw):
    image = next(image for image in eng.program.images if image["name"] == "/Im4")
    block = (b"q\n" + (" ".join(M._num(v) for v in image["cm"])+" cm\n").encode()
             + b"/Im4 Do\nQ\n")
    assert raw.count(block) == 1
    return raw.replace(block, b"", 1)


def top_raster_occlusion(page, eng, dpi):
    fitz = pytest.importorskip("fitz")
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    data, width, scale = pix.samples, pix.width, dpi/72
    y0 = math.floor((eng.frame_top-eng.rule_width/2)*scale)
    y1 = math.ceil((eng.frame_top+eng.rule_width/2)*scale)
    return {x/scale for x in range(math.ceil(eng.frame_left*scale)+1, math.floor(eng.frame_right*scale))
            if min(data[row*width+x] for row in range(y0, y1+1)) >= DARK}


@pytest.mark.parametrize("dpi", [72, 144])
def test_top_occlusion_is_identical_to_the_certified_source(engine, dpi):
    baseline = os.environ.get("B66_SOL61_PRE_FIX_PDF")
    if not baseline:
        pytest.skip("Set B66_SOL61_PRE_FIX_PDF to prove preserved source seal layering")
    fitz = pytest.importorskip("fitz")
    original = BUNDLE.parent / "source/original.pdf"
    with fitz.open(original) as source, fitz.open(baseline) as before:
        source_hidden = top_raster_occlusion(source[0], engine, dpi)
        assert source_hidden == top_raster_occlusion(before[0], engine, dpi)
        assert source_hidden, "Control must expose the existing seal over the source rule"
        x0, y0, x1, y1 = source_seal_footprint(engine)
        assert y0 <= engine.frame_top <= y1
        assert all(x0 <= x <= x1 for x in source_hidden)


def assert_raster_frame(page, eng, dpi, allow_source_seal=True):
    fitz = pytest.importorskip("fitz")
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    data, width, scale = pix.samples, pix.width, dpi/72
    for label, x in [("left", eng.frame_left), ("right", eng.frame_right)]:
        x0, x1 = math.floor((x-eng.rule_width/2)*scale), math.ceil((x+eng.rule_width/2)*scale)
        for y in range(math.ceil(eng.frame_top*scale)+1, math.floor(eng.frame_bottom*scale)):
            assert min(data[y*width+x0:y*width+x1+1]) < DARK, f"{label} gap: dpi={dpi}, y={y/scale:.3f}"
    for label, y in [("top", eng.frame_top), ("bottom", eng.frame_bottom)]:
        y0, y1 = math.floor((y-eng.rule_width/2)*scale), math.ceil((y+eng.rule_width/2)*scale)
        for x in range(math.ceil(eng.frame_left*scale)+1, math.floor(eng.frame_right*scale)):
            seal_x0, seal_y0, seal_x1, seal_y1 = source_seal_footprint(eng)
            # The issued seal paints over the top rule. Its native CTM is the only exception.
            if allow_source_seal and seal_y0 <= y <= seal_y1 and seal_x0 <= x/scale <= seal_x1:
                continue
            assert min(data[row*width+x] for row in range(y0, y1+1)) < DARK, f"{label} gap: dpi={dpi}, x={x/scale:.3f}"


@pytest.mark.parametrize("dpi", [72, 144])
@pytest.mark.parametrize("summary,body_art,count", SCENARIOS)
def test_font_independent_composition_raster(engine, summary, body_art, count, dpi):
    if os.environ.get("B66_SOL61_FRAME_RASTER") != "1":
        pytest.skip("Enable B66_SOL61_FRAME_RASTER after the artifact-operation marker")
    fitz = pytest.importorskip("fitz")
    raw, _, _, _ = compose(engine, summary, body_art, count)
    for include_seal in (True, False):
        writer = PdfWriter()
        writer.add_page(engine.program.reader.pages[0])
        stream = DecodedStreamObject()
        stream.set_data(raw if include_seal else without_seal_for_intrinsic_probe(engine, raw))
        writer.pages[0][NameObject("/Contents")] = writer._add_object(stream)
        buffer = BytesIO()
        writer.write(buffer)
        with fitz.open(stream=buffer.getvalue(), filetype="pdf") as doc:
            assert_raster_frame(doc[0], engine, dpi, allow_source_seal=include_seal)


@pytest.mark.parametrize("n", [8, 25])
def test_windows_real_pdf_smoke(engine, n, tmp_path):
    if sys.platform != "win32" or os.environ.get("B66_SOL61_FRAME_REAL_PDF") != "1":
        pytest.skip("Enable Windows real-PDF smoke after the artifact-operation marker")
    fitz = pytest.importorskip("fitz")
    if not all((Path("C:/Windows/Fonts")/font).is_file()
               for font in ("gulim.ttc", "malgun.ttf", "malgunbd.ttf")):
        pytest.skip("Certified Windows fonts unavailable; source composition remains executable")
    output = tmp_path / f"frame-{n}.pdf"
    request = {"items": [{"name": f"Frame item {i+1}", "spec": "Spec", "unit": "EA",
                          "qty": i % 3+1, "unitPrice": 137000+i*9137, "note": ""}
                         for i in range(n)]}
    result = engine.render(output, request)
    reader = PdfReader(output)
    assert len(reader.pages) == result["pages"]
    with fitz.open(output) as doc:
        for i, page in enumerate(reader.pages):
            assert_frame(page.get_contents().get_data(), reader, engine)
            for dpi in (72, 144):
                assert_raster_frame(doc[i], engine, dpi)
