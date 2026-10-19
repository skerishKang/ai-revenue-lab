"""#3839 — real-PDF image regression test for the left-margin stray stroke.

This defect escaped the first verification round, so the test is written to be
*load-bearing* rather than merely green:

  T1  ordering invariant   no line re-emitted by ``emit_path`` may begin with a path
                           operator (``m 25.786 707.226``); operands come first
  T2  image regression     no produced page paints ink left of the certified frame's
                           outer edge, on every page of N=4/8/25/100
  T3  mutation control     the pre-fix operator order applied to the *same* page must
                           make T2's check fail, so it is not vacuously green

The engine is located by searching upward for its directory, so this file can live
next to the engine wherever the repository keeps it. Override with
B66_SOL61_ENGINE_DIR.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import fitz
import pytest

DPI = 150
DARK = 128
SCALES = (4, 8, 25, 100)
PATH_OPS = {"m", "l", "h", "re", "c", "v", "y"}
# Operators that legitimately take no operands, so a bare-operator line is correct.
ZERO_OPERAND_OPS = {"h", "n", "W", "W*"}
OP_LINE_RE = re.compile(r"^([\d.\- ]+)\s+(m|l|h|re|c|v|y)$")
NUMBERS_RE = re.compile(r"^[\d.\- ]+\s+(?:m|l|h|re|c|v|y)$")


def _multipage_dir() -> Path:
    """Directory holding this renderer, wherever it is installed."""
    for cand in _candidates():
        if (cand / "sol61_multipage.py").is_file():
            return cand
    raise RuntimeError("sol61_multipage.py not found; set B66_SOL61_ENGINE_DIR")


def _candidates() -> list[Path]:
    env = os.environ.get("B66_SOL61_ENGINE_DIR")
    out = [Path(env)] if env else []
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        out += [base, base / "sol61" / "engine", base / "engine", base / "sol61"]
    return out


def _bundle_dir() -> Path:
    """The certified Sol 6.1 bundle: template + the certified engine + QuoteCore.

    It is a separate, hash-locked release artifact set, so this renderer resolves it
    instead of living inside it.
    """
    env = os.environ.get("B66_SOL61_BUNDLE_DIR")
    out = [Path(env)] if env else []
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        out += [base / "sol61",
                base / "reference" / "b66-public-standard-templates" / "cgi" / "v1" / "sol61",
                base / "work" / "sol61"]
    for cand in out:
        if (cand / "engine" / "quote_template.py").is_file() and (cand / "template" / "program.zlib").is_file():
            return cand
    raise RuntimeError("certified sol61 bundle not found; set B66_SOL61_BUNDLE_DIR")


MULTIPAGE_DIR = _multipage_dir()
BUNDLE_DIR = _bundle_dir()
TEMPLATE_DIR = BUNDLE_DIR / "template"
for path in (str(MULTIPAGE_DIR), str(BUNDLE_DIR / "engine")):
    if path not in sys.path:
        sys.path.insert(0, path)

import quote_template as Q  # noqa: E402
import sol61_multipage as M  # noqa: E402

ENG = M.SolMultipage(TEMPLATE_DIR)


def items(n):
    return [{"name": f"품목{i+1:04d}", "spec": f"규격-{i+1:04d}", "unit": "EA",
             "qty": (i % 9) + 1, "unitPrice": 137000 + i * 9137, "note": ""} for i in range(n)]


def scan(pdf, x_pt, dpi=DPI, dark=DARK):
    """Per page: dark pixels strictly left of ``x_pt`` and the page's leftmost ink.

    Row sampling uses ``bytes`` slicing plus ``min()``, which run in C, so even a
    51-page document stays fast enough for a test.
    """
    doc = fitz.open(pdf)
    cut = int(x_pt * dpi / 72.0)
    out = {}
    for i in range(doc.page_count):
        pm = doc[i].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        samples, width, height = pm.samples, pm.width, pm.height
        stray, left = 0, width
        for r in range(height):
            base = r * width
            row = samples[base:base + width]
            if min(row) >= dark:                 # no ink anywhere on this row
                continue
            for c in range(left):                # narrows toward the leftmost ink
                if samples[base + c] < dark:
                    left = c
                    break
            if cut:
                strip = row[:cut]
                if min(strip) < dark:
                    stray += sum(1 for v in strip if v < dark)
        out[i + 1] = {"stray_dark_px": stray, "ink_left_pt": round(left * 72.0 / dpi, 2)}
    doc.close()
    return out


def stray_total(pdf, x_pt):
    return sum(v["stray_dark_px"] for v in scan(pdf, x_pt).values())


@pytest.fixture(scope="module")
def certified_left(tmp_path_factory):
    """The certified engine's own render: its leftmost ink is the frame's outer edge."""
    out = tmp_path_factory.mktemp("certified") / "certified.pdf"
    Q.render_profile(TEMPLATE_DIR, out, {}, "node")
    return min(v["ink_left_pt"] for v in scan(out, 0.0).values())


def test_t1_operands_precede_their_operator():
    for prim in ENG.program.paths:
        for line in ENG.program.emit_path(prim).decode("latin-1").splitlines():
            line = line.strip()
            if not line:
                continue
            head = line.split()[0]
            if head in PATH_OPS:
                assert line == head and head in ZERO_OPERAND_OPS, \
                    f"operator written before its operands: {line!r}"
    lines = [ln.strip() for ln in ENG.program.emit_path(ENG.program.paths[0]).decode("latin-1").splitlines()
             if OP_LINE_RE.match(ln.strip())]
    assert lines, "the frame path emitted no path operators"
    assert lines[0][0].isdigit() and lines[0].endswith(" m"), lines[0]


@pytest.mark.parametrize("n", SCALES)
def test_t2_no_ink_left_of_the_certified_frame(n, certified_left, tmp_path):
    pdf = tmp_path / f"mp_{n}.pdf"
    info = ENG.render(pdf, {"items": items(n)})
    got = scan(pdf, certified_left)
    assert len(got) == info["pages"] == len(ENG.plan(n))
    stray = {p: v["stray_dark_px"] for p, v in got.items() if v["stray_dark_px"]}
    assert not stray, f"N={n}: stray ink outside the certified frame on pages {stray}"
    assert {v["ink_left_pt"] for v in got.values()} == {certified_left}


def test_t3_pre_fix_operator_order_is_detected(certified_left, tmp_path):
    """Mutation control: replay the bug on the same page and T2's check must fail."""
    good = tmp_path / "good.pdf"
    ENG.render(good, {"items": items(4)})
    assert stray_total(good, certified_left) == 0

    doc = fitz.open(good)
    stream = doc[0].read_contents().decode("latin-1")
    swapped = "\n".join(
        f"{m.group(2)} {m.group(1)}" if (m := OP_LINE_RE.match(ln.strip())) else ln
        for ln in stream.splitlines())
    assert swapped != stream, "mutation changed nothing: the path operators were not found"
    # PyMuPDF 1.26 replaces /Contents by xref, not by bytes.
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, swapped.encode("latin-1"))
    doc[0].set_contents(xref)
    mutated = tmp_path / "pre_fix.pdf"
    doc.save(mutated, garbage=0)
    doc.close()

    stray = stray_total(mutated, certified_left)
    assert stray > 0, "the pre-fix operator order drew no stray ink: T2 is not load-bearing"
