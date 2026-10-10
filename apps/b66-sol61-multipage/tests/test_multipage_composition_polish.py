"""CENTRAL visual-signoff items for the 4+ page Sol composition (#3839).

Both reported defects share one cause: the source's interior column rules were
re-emitted in the region the generated item grid already owns. These tests pin
the repaired policy, and pin the furniture that must survive it — the certified
column header, the payment-panel column rules and the exact outer frame.

Two layers, because the release CI runs without host fonts and without node:

* **Geometry** reads the emitted content stream directly. No rendering, no node,
  no fonts, so it is executable anywhere and cannot pass by moving a screenshot.
* **Rendered documents** open real PDFs and need the certified fonts plus node.
  They are gated exactly like ``test_windows_real_pdf_smoke``.

Anchors come from the engine's own certified geometry and from PDF vector
operators, never from a renderer-side constant chosen to match the answer.
"""
from __future__ import annotations

import hashlib
from importlib.util import spec_from_file_location, module_from_spec
import os
from pathlib import Path
import re
import shutil
import sys

import pytest
from pypdf import PdfReader

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]
BUNDLE = Path(os.environ.get("B66_SOL61_BUNDLE_DIR", str(
    REPO / "reference/b66-public-standard-templates/cgi/v1/sol61")))
SPEC = spec_from_file_location("composition_renderer", APP / "sol61_multipage.py")
M = module_from_spec(SPEC)
SPEC.loader.exec_module(M)

EPS = 0.05
NODE = os.environ.get("B66_SOL61_NODE", "node")
COUNTS = (4, 8, 25, 100)
# Same scenarios the accepted frame regression uses: first-only, final-only, mixed.
SCENARIOS = [(False, True, 3), (False, False, 10), (True, False, 5)]
STROKE = re.compile(
    rb"([-\d.]+) ([-\d.]+) m ([-\d.]+) ([-\d.]+) l S", re.S)

CERTIFIED_FONTS = ("gulim.ttc", "malgun.ttf", "malgunbd.ttf")
FONTS_PRESENT = all((Path("C:/Windows/Fonts") / f).is_file() for f in CERTIFIED_FONTS)
REQUIRES_DOCUMENT = pytest.mark.skipif(
    sys.platform != "win32" or not FONTS_PRESENT or shutil.which(NODE) is None,
    reason="real-document checks need the certified Windows fonts and node")


def items(n: int) -> list[dict]:
    return [{"name": f"품목 {i+1}", "spec": f"규격-{i+1}", "unit": "EA",
             "qty": (i % 5) + 1, "unitPrice": 137000 + i * 9137, "note": ""}
            for i in range(n)]


@pytest.fixture
def engine():
    return M.SolMultipage(BUNDLE / "template", node=NODE)


def strokes(raw: bytes, height: float) -> list[tuple[str, float, float, float]]:
    """Decode ``m/l/S`` rules from an emitted content stream.

    PDF writes bottom-up; the engine's own anchors are top-down, so y is flipped
    here once and every assertion below is in top-down page space.
    """
    found = []
    for x0, y0, x1, y1 in ((float(a), float(b), float(c), float(d))
                           for a, b, c, d in STROKE.findall(raw)):
        t0, t1 = height - y0, height - y1
        if abs(x0 - x1) < 0.01 and abs(t0 - t1) > 0.01:
            found.append(("v", round(x0, 3), min(t0, t1), max(t0, t1)))
        elif abs(t0 - t1) < 0.01 and abs(x0 - x1) > 0.01:
            found.append(("h", round(t0, 3), min(x0, x1), max(x0, x1)))
    return found


def interior(ops, xs):
    return [(x, t, b) for kind, x, t, b in ops
            if kind == "v" and any(abs(x - c) < EPS for c in xs)]


def composed(engine, summary, body_art, count):
    bottoms = [engine.body_top + (i + 1) * engine.row_pitch for i in range(count)]
    skeleton = engine._skeleton(summary, body_art, bottoms[-1])
    grid = engine._grid(bottoms)
    return skeleton + grid, bottoms[-1]


# ---------------------------------------------------------------------------
# Layer 1 — geometry of the emitted composition (no fonts, no node, no PDF).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("summary,body_art,count", SCENARIOS)
def test_no_interior_column_stroke_is_left_in_the_blank_body(engine, summary, body_art, count):
    """CENTRAL item 1: no partial vertical stroke below the item table.

    A rule that reaches the payment-panel boundary is furniture; a rule that stops
    between the last generated row and that boundary is the reported defect.
    """
    raw, table_edge = composed(engine, summary, body_art, count)
    xs = [round(x, 3) for x in engine.columns[1:-1]]
    offenders = [(x, t, b) for x, t, b in interior(strokes(raw, engine.height), xs)
                 if b > table_edge + 0.5 and b < engine.footer_top - 0.5
                 and t <= table_edge + 0.5]
    assert not offenders, (
        f"interior rules dangle between the table edge ({table_edge:.3f}) "
        f"and the payment panel ({engine.footer_top:.3f}): {offenders}")


@pytest.mark.parametrize("summary,body_art,count", SCENARIOS)
def test_item_column_rules_never_enter_the_summary_band(engine, summary, body_art, count):
    """CENTRAL item 2: 소계/부가세/합계 cells carry no item-column line."""
    raw, _ = composed(engine, summary, body_art, count)
    inside = [(x, t, b) for x, t, b in interior(strokes(raw, engine.height),
                                                [round(x, 3) for x in engine.columns[1:-1]])
              if t >= engine.totals_top - 0.5 and b <= engine.footer_top + 0.5]
    assert not inside, f"item-column rules painted through the summary band: {inside}"


@pytest.mark.parametrize("summary,body_art,count", SCENARIOS)
def test_header_and_payment_panel_column_rules_survive(engine, summary, body_art, count):
    """The repair must not thin out legitimate furniture into nothing."""
    raw, _ = composed(engine, summary, body_art, count)
    found = interior(strokes(raw, engine.height),
                     [round(x, 3) for x in engine.columns[1:-1]])
    header = [v for v in found if v[2] <= engine.body_top + 0.5]
    panel = [v for v in found
             if v[1] >= engine.footer_top - 0.5 and v[2] <= engine.frame_bottom + 0.5]
    assert header, "certified column-header separators were lost"
    assert panel, "payment-panel column rules were lost"


@pytest.mark.parametrize("summary,body_art,count", SCENARIOS)
def test_interior_rules_cover_the_row_band_exactly_once(engine, summary, body_art, count):
    """Inside the generated row band each column has exactly one owner.

    The blank body below the table edge is intentionally empty under the adopted
    policy (dividers end at the table edge), so contiguity is asserted over the row
    band only: that is where a grid that stops early, or a source fragment
    double-painting the grid, would show up.
    """
    raw, table_edge = composed(engine, summary, body_art, count)
    for x in [round(c, 3) for c in engine.columns[1:-1]]:
        spans = [(t, b) for xx, t, b in interior(strokes(raw, engine.height), [x])
                 if abs(xx - x) < EPS and t >= engine.body_top - 0.5
                 and b <= table_edge + 0.5]
        assert spans, f"column x={x} lost its grid coverage in the row band"
        cuts = sorted({engine.body_top, table_edge, *(v for s in spans for v in s)})
        for a, b in zip(cuts, cuts[1:]):
            if b - a <= EPS:
                continue
            mid = (a + b) / 2
            owners = sum(s[0] - EPS < mid < s[1] + EPS for s in spans)
            assert owners == 1, (
                f"column x={x}: coverage={owners} on [{a:.3f},{b:.3f}] spans={spans}")


# ---------------------------------------------------------------------------
# Layer 2 — real rendered documents (certified fonts + node).
# ---------------------------------------------------------------------------

fitz = pytest.importorskip("fitz", reason="document checks need PyMuPDF")


def render(engine, n: int, tmp_path: Path, tag: str = "q") -> Path:
    out = tmp_path / f"{tag}_{n}.pdf"
    engine.render(out, {"items": items(n)})
    return out


def page_verticals(page, xs):
    found = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] != "l":
                continue
            p1, p2 = it[1], it[2]
            if abs(p1.x - p2.x) > EPS or abs(p1.y - p2.y) < 0.5:
                continue
            x = round(p1.x, 3)
            if any(abs(x - c) < EPS for c in xs):
                t, b = sorted((p1.y, p2.y))
                found.append((x, round(t, 3), round(b, 3)))
    return found


def page_table_edge(page, left, right, footer_top):
    ys = set()
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] != "l":
                continue
            p1, p2 = it[1], it[2]
            if abs(p1.y - p2.y) > EPS or abs(p1.x - p2.x) < 10:
                continue
            if p1.x <= left + 1 and max(p1.x, p2.x) >= right - 1:
                ys.add(round(p1.y, 3))
    return max([y for y in ys if y <= footer_top - 0.5] or [0.0])


def frame_spans(page, x):
    out = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] != "l":
                continue
            p1, p2 = it[1], it[2]
            if abs(p1.x - p2.x) > EPS or abs(p1.x - x) > EPS or abs(p1.y - p2.y) < 0.5:
                continue
            out.append(sorted((p1.y, p2.y)))
    return out


@REQUIRES_DOCUMENT
@pytest.mark.parametrize("n", COUNTS)
def test_rendered_pages_have_no_dangling_and_no_summary_column_rules(engine, n, tmp_path):
    pdf = render(engine, n, tmp_path)
    xs = [round(x, 3) for x in engine.columns[1:-1]]
    doc = fitz.open(pdf)
    try:
        for pno, page in enumerate(doc):
            edge = page_table_edge(page, engine.columns[0], engine.columns[-1],
                                   engine.footer_top)
            found = page_verticals(page, xs)
            dangling = [(x, t, b) for x, t, b in found
                        if b > edge + 0.5 and b < engine.footer_top - 0.5
                        and t <= edge + 0.5]
            band = [(x, t, b) for x, t, b in found
                    if t >= engine.totals_top - 0.5 and b <= engine.footer_top + 0.5]
            assert not dangling, f"page {pno+1} dangling: {dangling}"
            assert not band, f"page {pno+1} summary-band rules: {band}"
    finally:
        doc.close()


@REQUIRES_DOCUMENT
@pytest.mark.parametrize("n", COUNTS)
def test_outer_frame_has_exactly_one_owner_on_every_rendered_page(engine, n, tmp_path):
    """Guards the accepted right-frame correction against regression.

    PyMuPDF reports top-down page coordinates, the same convention the engine uses
    for ``frame_top``/``frame_bottom``, so anchors are compared directly.
    """
    pdf = render(engine, n, tmp_path)
    low, high = engine.frame_top, engine.frame_bottom
    doc = fitz.open(pdf)
    try:
        for pno, page in enumerate(doc):
            for side, x in (("left", engine.frame_left), ("right", engine.frame_right)):
                spans = frame_spans(page, x)
                cuts = sorted({low, high, *(v for s in spans for v in s)})
                for a, b in zip(cuts, cuts[1:]):
                    if b - a <= EPS:
                        continue
                    mid = (a + b) / 2
                    owners = sum(s[0] - EPS < mid < s[1] + EPS for s in spans)
                    assert owners == 1, (
                        f"page {pno+1} {side} frame: coverage={owners} on "
                        f"[{a:.3f},{b:.3f}] spans={spans}")
    finally:
        doc.close()


@REQUIRES_DOCUMENT
@pytest.mark.parametrize("n", (1, 2, 3))
def test_one_to_three_items_stay_the_certified_bytes(engine, n, tmp_path):
    """1-3 must be the certified renderer's own bytes, not a generated lookalike."""
    out = render(engine, n, tmp_path, tag="multi")
    plan = engine.render(out, {"items": items(n)})
    assert plan.get("certifiedPath") is True and plan["pages"] == 1

    sys.path.insert(0, str(BUNDLE / "engine"))
    import quote_template
    direct = tmp_path / f"certified_{n}.pdf"
    quote_template.render_profile(BUNDLE / "template", direct,
                                  {"items": items(n)}, NODE)
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    assert digest(out) == digest(direct)


@REQUIRES_DOCUMENT
@pytest.mark.parametrize("n", (8, 25, 100))
def test_every_item_appears_once_in_input_order(engine, n, tmp_path):
    doc = fitz.open(render(engine, n, tmp_path))
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    positions = []
    for i in range(n):
        needle = f"품목 {i+1}"
        # "품목 1" prefixes "품목 10", so count only non-digit-extended tokens.
        hits = len(re.findall(re.escape(needle) + r"(?!\d)", text))
        assert hits == 1, f"{needle}: expected one occurrence, found {hits}"
        positions.append(text.index(needle))
    assert positions == sorted(positions), "item order changed across pages"


@REQUIRES_DOCUMENT
@pytest.mark.parametrize("n", COUNTS)
def test_displayed_totals_equal_quotecore(engine, n, tmp_path):
    """QuoteCore is the only money authority: recomputed, related, then read back."""
    request = {"items": items(n)}
    built = engine.build_slots(request, blank=())
    core, slots = built["totals"], built["slots"]

    out = render(engine, n, tmp_path)
    plan = engine.render(out, request)
    assert plan["totals"] == {k: slots[k] for k in ("subtotal", "vat", "grand")}

    rows = items(n)
    assert core["subtotal"] == sum(r["qty"] * r["unitPrice"] for r in rows)
    assert core["amounts"] == [r["qty"] * r["unitPrice"] for r in rows]
    assert core["grand"] == core["subtotal"] + core["vat"]
    assert len(core["effectiveItems"]) == n, "QuoteCore dropped a row"

    doc = fitz.open(out)
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    for key in ("subtotal", "vat", "grand"):
        assert slots[key] in text, f"displayed {key} != QuoteCore ({slots[key]})"


@REQUIRES_DOCUMENT
@pytest.mark.parametrize("n", COUNTS)
def test_render_is_deterministic(engine, n, tmp_path):
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    a = render(engine, n, tmp_path, tag="a")
    b = render(engine, n, tmp_path, tag="b")
    assert digest(a) == digest(b)


@REQUIRES_DOCUMENT
def test_generated_pages_carry_no_data_from_a_previous_document(engine, tmp_path):
    """Inherited page furniture is allowed; inherited *values* are not."""
    prior = {"items": items(6), "recipient": "㈜ 이전거래처", "project": "이전프로젝트",
             "quoteNo": "PRIOR-0001"}
    current = {"items": items(9), "recipient": "㈜ 새거래처", "project": "신규 배관공사",
               "quoteNo": "NEW-9999"}
    a, b = tmp_path / "prior.pdf", tmp_path / "current.pdf"
    engine.render(a, prior)
    engine.render(b, current)
    doc = fitz.open(b)
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    for token in ("㈜ 이전거래처", "이전프로젝트", "PRIOR-0001"):
        assert token not in text, f"previous document leaked: {token}"
    assert "㈜ 새거래처" in text and "NEW-9999" in text


@REQUIRES_DOCUMENT
def test_generated_pages_do_not_replay_certified_sample_values(engine, tmp_path):
    """The certified source carries its own 2022-era values; a generated document
    must show request values instead."""
    sample = engine.template["draft"]
    request = {"items": items(7), "recipient": "㈜ 확인거래처",
               "project": "확인 공사명", "quoteNo": "CHK-7777"}
    out = tmp_path / "chk.pdf"
    engine.render(out, request)
    doc = fitz.open(out)
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    for key in ("recipient", "project", "quoteNo"):
        value = str(sample.get(key, ""))
        if value and value != request[key]:
            assert value not in text, f"certified sample {key} replayed: {value}"


@REQUIRES_DOCUMENT
@pytest.mark.parametrize("n", COUNTS)
def test_logo_and_seal_are_emitted_on_every_page(engine, n, tmp_path):
    pdf = render(engine, n, tmp_path)
    reader = PdfReader(pdf)
    assert list(reader.pages[0].get("/Resources", {}).get("/XObject", {})), \
        "certified page carries no logo/seal XObject"
    for pno, page in enumerate(reader.pages):
        names = list(page.get("/Resources", {}).get("/XObject", {}))
        assert names, f"page {pno+1} lost the logo/seal XObjects"


def test_restoring_middle_segments_reproduces_both_defects():
    """The guards above are load-bearing: reverting the policy recreates the defects.

    A subclass re-adds the source segments between the table edge and the payment
    panel — precisely what CENTRAL rejected.
    """
    class Reverted(M.SolMultipage):
        def _column_fragments(self, line):
            top, bottom = line["top"], self.height - line["box"][1]
            result = []
            for lo, hi in ((top, min(bottom, self.body_top)),
                           (max(top, getattr(self, "_edge", self.body_top)), bottom)):
                if hi - lo <= 0.001:
                    continue
                cuts = sorted({lo, hi, *(b for b in (self.totals_top, self.footer_top)
                                         if lo < b < hi)})
                for a, b in zip(cuts, cuts[1:]):
                    if b - a <= 0.001:
                        continue
                    x = line["box"][0]
                    result.append({**line, "top": a,
                                   "box": [x, self._pdf(b), x, self._pdf(a)]})
            return result

        def _skeleton(self, include_summary, include_body_art, last_bottom):
            self._edge = last_bottom
            return super()._skeleton(include_summary, include_body_art, last_bottom)

    broken = Reverted(BUNDLE / "template", node=NODE)
    # summary=True, body_art=True: the final page of a 4+ document, which is where
    # both reported defects were observable at once.
    raw, table_edge = composed(broken, True, True, 3)
    xs = [round(x, 3) for x in broken.columns[1:-1]]
    found = interior(strokes(raw, broken.height), xs)
    dangling = [(x, t, b) for x, t, b in found
                if b > table_edge + 0.5 and b < broken.footer_top - 0.5
                and t <= table_edge + 0.5]
    band = [(x, t, b) for x, t, b in found
            if t >= broken.totals_top - 0.5 and b <= broken.footer_top + 0.5]
    assert dangling, "reverting the repair did not recreate a dangling stroke"
    assert band, "reverting the repair did not recreate summary-band column lines"

    fixed = M.SolMultipage(BUNDLE / "template", node=NODE)
    clean_raw, clean_edge = composed(fixed, True, True, 3)
    clean = interior(strokes(clean_raw, fixed.height), xs)
    assert [v for v in clean if v[2] > clean_edge + 0.5 and v[2] < fixed.footer_top - 0.5] == []
    assert [v for v in clean
            if v[1] >= fixed.totals_top - 0.5 and v[2] <= fixed.footer_top + 0.5] == []
