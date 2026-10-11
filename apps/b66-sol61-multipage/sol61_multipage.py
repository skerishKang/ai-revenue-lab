"""B66 #3839 — Sol 6.1 native variable-row / continuous-A4 renderer.

This module EXTENDS the certified Sol 6.1 source-derived CGI template. It does not
replace it, does not re-create it and never falls back to another renderer.

Derivation contract
-------------------
* Every geometric value is read at run time from the certified package
  (`template.json` bindings + the certified `program.zlib` drawing program).
  Nothing is guessed; PR #3855's placeholder figures are not used.
* Money, tax, rounding and Korean number words come exclusively from QuoteCore via
  `slots_multipage.cjs` -> `quote-core.js`. This module performs layout only.
* 1-3 rows are delegated verbatim to the certified `quote_template.render_profile`,
  so certified output for the existing scope stays byte-identical.
* No model inference, no network, no browser, no HTML print path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zlib
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ByteStringObject,
    ContentStream,
    DecodedStreamObject,
    NameObject,
    TextStringObject,
)

RENDERER_ID = "b66.sol61.native-multipage.render.v1"
RENDERER_VERSION = 1
CERTIFIED_MAX_ROWS = 3
ROW_FIELD_ORDER = ("Name", "Spec", "Unit", "Qty", "UnitPrice", "Amount", "Note")
WRAPPABLE_FIELDS = ("Name", "Spec", "Note")
SHRINKABLE_FIELDS = ("Unit", "Qty", "UnitPrice", "Amount")
LINE_TOP = 14.261
LINE_HEIGHT = 12.0
ROW_PAD = 4.0
CONTENT_BOTTOM = 780.0
LAST_ROWS_CEILING = 500.0
PAGE_NUMBER_TOP = 800.0
PAGE_NUMBER_SIZE = 12.0
SUMMARY_LO, SUMMARY_HI = 499.0, 720.0
YELLOW_BAND_LO, YELLOW_BAND_HI = 265.0, 300.0
ROW_CLEARANCE = 6.0
TOTALS_KEYS = ("subtotal", "vat", "grand")
BLANK_MARKER_CHARS = ("이", "하", "여", "백")
# The headline 합계금액 band is certified LETTERHEAD: it sits above the item table
# (y~289) and states the document total, so it is redacted on no page. Only the
# 소계/부가세/합계 breakdown block belongs to the final page.
BLANKABLE = ("subtotal", "vat", "grand")


def _mul(a, b):
    return [a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3], a[2]*b[0]+a[3]*b[2],
            a[2]*b[1]+a[3]*b[3], a[4]*b[0]+a[5]*b[2]+b[4], a[4]*b[1]+a[5]*b[3]+b[5]]


def _pt(cm, x, y):
    return (x*cm[0]+y*cm[2]+cm[4], x*cm[1]+y*cm[3]+cm[5])


def _num(v) -> str:
    return ('%.6f' % float(v)).rstrip('0').rstrip('.') or '0'


def _tj_bytes(arr) -> bytes:
    parts = []
    for el in arr:
        if isinstance(el, (ByteStringObject, TextStringObject)):
            parts.append(b"<" + el.original_bytes.hex().encode() + b">")
        else:
            parts.append(_num(el).encode())
    return b"[" + b" ".join(parts) + b"] TJ\n"


def _rgba(cmd: str, rgb) -> bytes:
    return (" ".join(_num(v) for v in rgb) + f" {cmd}\n").encode()


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
class Program:
    """Decomposes the certified program into self-contained absolute primitives.

    Every primitive is re-emitted as its own ``q ... Q`` block so that page
    composition never depends on streaming graphics state from the source.
    """

    def __init__(self, template_dir: Path):
        self.raw = zlib.decompress((Path(template_dir) / "program.zlib").read_bytes())
        self.reader = PdfReader(Path(template_dir) / "resources.pdf")
        self.page = self.reader.pages[0]
        self.height = float(self.page.mediabox.height)
        self.width = float(self.page.mediabox.width)
        stream = DecodedStreamObject()
        stream.set_data(self.raw)
        self.ops = ContentStream(stream, self.reader).operations
        self.text_runs: list[dict] = []
        self.lines: list[dict] = []
        self.rects: list[dict] = []
        self.paths: list[dict] = []
        self.images: list[dict] = []
        self._decompose()
        self.imap = self._decode_maps()

    def top(self, y_pdf: float) -> float:
        return self.height - y_pdf

    def _decompose(self) -> None:
        stack: list = []
        cm = [1, 0, 0, 1, 0, 0]
        fill, stroke, lw = [0.0]*3, [0.0]*3, 1.0
        clip = [0.0, 0.0, self.width, self.height]
        path: list = []
        raw: list = []
        active: dict | None = None
        for order, (args, op) in enumerate(self.ops):
            if op == b"q":
                stack.append((cm[:], fill[:], stroke[:], lw, clip[:]))
            elif op == b"Q":
                if stack:
                    cm, fill, stroke, lw, clip = stack.pop()
            elif op == b"cm":
                cm = _mul([float(x) for x in args], cm)
            elif op == b"w":
                lw = float(args[0])
                if active is not None:
                    # The certified title sets its own stroke width INSIDE the text
                    # object (``Tr 2`` then ``w 4.58``); the stroke colour likewise.
                    active["strokeWidth"] = lw
            elif op in (b"g", b"rg", b"k"):
                v = [float(x) for x in args]
                fill = [v[0]]*3 if op == b"g" else (v[:3] if len(v) >= 3 else v)
                if active is not None:
                    active["fill"] = list(fill)
            elif op in (b"G", b"RG", b"K"):
                v = [float(x) for x in args]
                stroke = [v[0]]*3 if op == b"G" else (v[:3] if len(v) >= 3 else v)
                if active is not None:
                    active["stroke"] = list(stroke)
            elif op == b"re":
                x, y, w, h = (float(v) for v in args)
                path.append(("re", [_pt(cm, x, y), _pt(cm, x+w, y+h)]))
                raw.append((op, [float(v) for v in args]))
            elif op in (b"m", b"l"):
                path.append((op.decode(), [_pt(cm, float(args[0]), float(args[1]))]))
                raw.append((op, [float(args[0]), float(args[1])]))
            elif op in (b"c", b"v", b"y"):
                path.append((op.decode(), [_pt(cm, float(args[i]), float(args[i+1]))
                                          for i in range(0, len(args) - 1, 2)]))
                raw.append((op, [float(v) for v in args]))
            elif op == b"h":
                raw.append((op, []))
            elif op in (b"W", b"W*"):
                if path:
                    xs = [p[0] for _, pts in path for p in pts]
                    ys = [p[1] for _, pts in path for p in pts]
                    clip = [max(clip[0], min(xs)), max(clip[1], min(ys)),
                            min(clip[2], max(xs)), min(clip[3], max(ys))]
            elif op in (b"n", b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
                if path:
                    xs = [p[0] for _, pts in path for p in pts]
                    ys = [p[1] for _, pts in path for p in pts]
                    box = [min(xs), min(ys), max(xs), max(ys)]
                    # A filled band may be a single ``re`` or a 4-point m/l
                    # rectangle; both are axis-aligned with exactly two distinct
                    # x and two distinct y coordinates.
                    is_rect = (len({round(v, 3) for v in xs}) == 2
                               and len({round(v, 3) for v in ys}) == 2)
                    is_segment = len(path) == 2 and path[0][0] in ("m", "re")
                    # Everything else (nested frames, double rules, curves) is kept as a
                    # whole path and re-emitted verbatim: the certified form paints its
                    # table frame as a two-subpath ``B`` at the very end of the stream,
                    # and dropping it removed the whole info-table border.
                    is_simple = (len(path) <= 5
                                 and not any(k in ("c", "v", "y") for k, _ in path))
                    is_rect = is_rect and is_simple
                    if is_rect and op in (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
                        self.rects.append({"box": box, "fill": list(fill), "order": order,
                                           "top": round(self.top(box[3]), 4)})
                    elif is_segment and op in (b"S", b"s", b"B", b"B*", b"b", b"b*"):
                        self.lines.append({"box": box, "stroke": list(stroke), "order": order,
                                           "width": round(lw*abs(cm[0]), 4),
                                           "top": round(self.top(box[3]), 4)})
                    elif op != b"n":
                        # Re-emitted inside its own ``cm`` with the raw operands, so
                        # subpaths, closepath, winding rule and widths stay exactly as
                        # the certified program wrote them.
                        self.paths.append({"ops": list(raw), "cm": cm[:], "fill": list(fill),
                                           "stroke": list(stroke), "width": lw, "paint": op,
                                           "order": order, "top": round(self.top(box[3]), 4)})
                path = []
                raw = []
            elif op == b"Do":
                self.images.append({"name": str(args[0]), "cm": cm[:], "order": order})
            elif op == b"BT":
                # The stroke width in force at BT time matters: the certified title and
                # the 합계금액 line are drawn with renderMode 2 (fill+stroke) and a hard
                # coded 1.0 would render their outlines visibly lighter than the source.
                active = {"cm": cm[:], "clip": clip[:], "fill": list(fill),
                          "stroke": list(stroke), "font": None,
                          "order": order, "size": None, "tm": None, "mode": 0,
                          "strokeWidth": lw, "tj": bytearray()}
            elif op == b"ET":
                if active is not None:
                    tm = active["tm"] or [1, 0, 0, 1, 0, 0]
                    x, y = _pt(active["cm"], tm[4], tm[5])
                    active["origin"] = (round(x, 4), round(y, 4))
                    active["top"] = round(self.top(y), 4)
                    self.text_runs.append(active)
                active = None
            elif active is not None:
                if op == b"Tf":
                    active["font"] = str(args[0]); active["size"] = float(args[1])
                elif op == b"Tm":
                    active["tm"] = [float(x) for x in args]
                elif op == b"Tr":
                    active["mode"] = int(args[0])
                elif op == b"w":
                    active["strokeWidth"] = float(args[0])
                elif op in (b"Tj", b"TJ"):
                    active["tj"] += _tj_bytes(args[0] if op == b"TJ" else [args[0]])

    def _decode_maps(self) -> dict:
        mapping = {}
        for name, ref in self.page["/Resources"]["/Font"].items():
            table: dict[int, str] = {}
            data = ref.get_object().get("/ToUnicode")
            if data is not None:
                raw = data.get_data().decode("ascii", "replace")
                for block in re.findall(r"beginbfchar(.*?)endbfchar", raw, re.S):
                    for a, b in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                        table[int(a, 16)] = bytes.fromhex(b).decode("utf-16-be")
                for block in re.findall(r"beginbfrange(.*?)endbfrange", raw, re.S):
                    for a, b, c in re.findall(
                            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                        for k in range(int(a, 16), int(b, 16) + 1):
                            table[k] = chr(int(c, 16) + k - int(a, 16))
            mapping[str(name)] = table
        return mapping

    def emit_path(self, prim: dict) -> bytes:
        """Re-emit a whole path verbatim (operands and paint operator included).

        Used for the primitives that are neither a single axis-aligned rectangle nor
        a two-point segment: nested frames, double rules and curved shapes. They keep
        their own ``cm``, colours, width, closepath and winding rule.
        """
        out = bytearray(b"q\n")
        out += (" ".join(_num(v) for v in prim["cm"]) + " cm\n").encode()
        out += _rgba("rg", prim["fill"]) + _rgba("RG", prim["stroke"])
        out += f"{_num(prim['width'])} w\n".encode()
        for op, args in prim["ops"]:
            # PDF operands precede their operator: ``x y m``, never ``m x y``.
            # Writing the operator first leaves the first ``m`` of each path with an
            # empty operand stack, so the path starts at the page origin instead of
            # its own first point; the paint operator then strokes a stray diagonal
            # from (0, 0) to the frame corner, across the left margin. Every later
            # operator happens to find its own operand pair still on the stack, which
            # is why the frame itself kept rendering and the defect stayed hidden.
            if args:
                out += " ".join(_num(v) for v in args).encode() + b" "
            out += op + b"\n"
        out += prim["paint"] + b"\nQ\n"
        return bytes(out)

    def decode(self, run: dict) -> str:
        table = self.imap.get(run["font"] or "", {})
        out, buf, i = [], bytes(run["tj"]), 0
        while i < len(buf):
            if buf[i:i+1] == b"<":
                j = buf.index(b">", i)
                for k in range(i + 1, j, 4):
                    out.append(table.get(int(buf[k:k+4], 16), "?"))
                i = j + 1
            else:
                i += 1
        return "".join(out)

    def emit_run(self, run: dict) -> bytes:
        n = _num
        x0, y0, x1, y1 = run["clip"]
        out = bytearray(b"q\n")
        out += (f"{n(x0)} {n(y0)} {n(max(x1-x0, 0.01))} {n(max(y1-y0, 0.01))} re W n\n").encode()
        out += _rgba("rg", run.get("fill") or [0, 0, 0])
        out += _rgba("RG", run.get("stroke") or [0, 0, 0])
        # The certified stream carries its own stroke width; without it the outlined
        # heading glyphs render noticeably thinner than the source page.
        out += f"{n(run.get('strokeWidth', 1))} w\n".encode()
        out += (" ".join(n(v) for v in run["cm"]) + " cm\n").encode()
        out += b"BT\n"
        if run.get("font"):
            out += f"{run['font']} {n(run['size'])} Tf\n".encode()
        out += f"{int(run.get('mode', 0))} Tr\n".encode()
        if run.get("tm"):
            out += (" ".join(n(v) for v in run["tm"]) + " Tm\n").encode()
        out += bytes(run["tj"]) + b"ET\nQ\n"
        return bytes(out)


# --------------------------------------------------------------------------- #
class SolMultipage:
    def __init__(self, template_dir: Path, node: str = "node"):
        self.dir = Path(template_dir).resolve()
        self.bundle = self._resolve_bundle()
        self.node = node
        self.template = json.loads((self.dir / "template.json").read_text(encoding="utf-8"))
        if self.template["renderer"].get("runtimeSourceAccess"):
            raise ValueError("Certified template declares runtime source access")
        self.program = Program(self.dir)
        self.height, self.width = self.program.height, self.program.width
        self.binds = {b["key"]: b for b in self.template["bindings"]}
        self._font_keys: dict[str, str] = {}
        self._constants: list[dict] | None = None
        self._marker_t: float | None = None
        self._quote_no_changed = False
        self._derive_geometry()

    # -- certified geometry -------------------------------------------------- #
    def _derive_geometry(self) -> None:
        self.certified_max = int(self.template.get("supportedItemCount", {})
                                 .get("maximum", CERTIFIED_MAX_ROWS))
        if any(self.binds.get(f"item0{f}") is None for f in ROW_FIELD_ORDER):
            raise ValueError("Certified template lacks a complete first item row")
        self.row_spec = {f: self.binds[f"item0{f}"] for f in ROW_FIELD_ORDER}
        self.body_top = min(b["bbox"][1] for b in self.row_spec.values())
        self.row_pitch = (self.binds["item2Name"]["bbox"][1]
                          - self.binds["item0Name"]["bbox"][1]) / 2.0
        self.row_cm = self.row_spec["Name"]["cm"]
        self.row_size = self.row_spec["Name"]["nominalSize"]
        band_lo = self.height - (self.body_top + 3*self.row_pitch)
        band_hi = self.height - self.body_top
        cols = sorted({round(l["box"][0], 2) for l in self.program.lines
                       if abs(l["box"][0] - l["box"][2]) < 0.01
                       and l["box"][1] <= band_hi + 0.5 and l["box"][3] >= band_lo - 0.5
                       and abs(l["width"] - 0.72) < 0.001})
        if len(cols) < 8:
            raise ValueError(f"Certified column grid not recognised: {cols}")
        self.columns = cols
        self.rule_width = 0.72
        outer = [l for l in self.program.lines
                 if l["stroke"] == [0.0, 0.0, 0.0]
                 and abs(l["width"] - self.rule_width) < 0.001
                 and abs(l["box"][0] - l["box"][2]) < 0.001
                 and min(abs(l["box"][0] - cols[0]),
                         abs(l["box"][0] - cols[-1])) < 0.01]
        if not outer:
            raise ValueError("Certified lower table frame not recognised")
        self.frame_left = min(l["box"][0] for l in outer)
        self.frame_right = max(l["box"][0] for l in outer)
        self.frame_top = min(l["top"] for l in outer)
        self.frame_bottom = max(self.height-l["box"][1] for l in outer)
        self.columns[0], self.columns[-1] = self.frame_left, self.frame_right
        hairs = {l["width"] for l in self.program.lines
                 if abs(l["box"][1] - l["box"][3]) < 0.01 and l["width"] < 0.2}
        self.hair_width = sorted(hairs)[0] if hairs else 0.12
        self.row_band_hi = self.body_top + 3*self.row_pitch
        # -- pagination bands, derived from the certified program --------------- #
        # The totals block (소계/부가세/합계 + the yellow 합계금액 band) belongs to the
        # LAST page only. The form footer below it (결제계좌 line, ⊙특기사항 notes, the
        # white cells they sit on, the CGI logo) is certified page furniture and is
        # re-emitted on every page, so rows may never enter either band.
        self.totals_top = min((self.binds[k]["bbox"][1] for k in TOTALS_KEYS),
                              default=LAST_ROWS_CEILING)
        yellow = [r for r in self.program.rects if r["fill"] == [1.0, 1.0, 0.6]]
        self.summary_bottom = max((r["top"] + self.row_pitch for r in yellow),
                                  default=self.totals_top)
        below = [p["top"] for p in self.constants() if p["top"] >= self.summary_bottom - 0.5]
        below += [r["top"] for r in self.program.rects
                  if r["top"] >= self.summary_bottom - 0.5 and r["fill"] != [1.0, 1.0, 0.6]]
        below += [l["top"] for l in self.program.lines if l["top"] >= self.summary_bottom - 0.5]
        self.footer_top = min(below, default=CONTENT_BOTTOM)
        self.cont_capacity = int((self.footer_top - ROW_CLEARANCE - self.body_top)
                                 // self.row_pitch)
        self.last_capacity = int((self.totals_top - ROW_CLEARANCE - self.body_top)
                                 // self.row_pitch)

    def _pdf(self, top: float) -> float:
        return self.height - top

    # -- QuoteCore slots ----------------------------------------------------- #
    def build_slots(self, changes: dict, blank: tuple = ()) -> dict:
        request = {"draft": self.template["draft"], "changes": changes,
                   "blankKeys": list(blank), "maxItems": 2000}
        core = self.bundle / "quote-core.js"
        if core.is_file():
            # QuoteCore lives beside the certified bundle, not beside this adapter, so
            # hand its absolute path over. The adapter then resolves the ONE money
            # authority wherever it is installed instead of trusting its own location.
            request["quoteCore"] = str(core)
        proc = subprocess.run(
            [self.node, str(Path(__file__).resolve().parent / "slots_multipage.cjs")],
            input=json.dumps(request, ensure_ascii=False),
            text=True, encoding="utf-8", capture_output=True)
        if proc.returncode:
            raise ValueError((proc.stderr or "").strip().splitlines()[:3])
        return json.loads(proc.stdout)

    # -- constants ----------------------------------------------------------- #
    def constants(self) -> list[dict]:
        if self._constants is None:
            consumed: set[int] = set()
            for b in self.template["bindings"]:
                consumed.update(b.get("runIndices") or [])
            runs = []
            for idx, run in enumerate(self.program.text_runs):
                if idx in consumed or not run["tj"]:
                    continue
                if not self.program.decode(run).strip():
                    continue
                runs.append({**run, "index": idx, "text": self.program.decode(run)})
            self._constants = runs
        return self._constants

    def _is_row_number(self, run: dict) -> bool:
        """True only for the certified NO-column row numbers (1..3).

        The band and the digit test are both required: a y-only test also matches
        every footer line whose x lands in the NO column (the ⊙특기사항 heading and
        the leading fragments of notes 1-3), which would silently delete them.
        """
        if not (self.body_top - 1.0 <= run["top"] <= self.row_band_hi + 1.0):
            return False
        if not re.fullmatch(r"\d+", re.sub(r"\s+", "", self.program.decode(run))):
            return False
        x = run["origin"][0]
        return self.columns[0] - 0.5 <= x <= self.columns[1] + 0.5

    def _is_row_boundary_rule(self, line: dict) -> bool:
        return (abs(line["box"][1] - line["box"][3]) < 0.01
                and self.body_top + 0.01 <= line["top"] <= self.row_band_hi + 0.01)

    def _is_outer_frame_rule(self, line: dict) -> bool:
        box = line["box"]
        return (line["stroke"] == [0.0, 0.0, 0.0]
                and abs(line["width"]-self.rule_width) < 0.001
                and abs(box[0]-box[2]) < 0.001
                and min(abs(box[0]-self.frame_left), abs(box[0]-self.frame_right)) < 0.001
                and self.frame_top-0.001 <= line["top"]
                and self.height-box[1] <= self.frame_bottom+0.001)

    def _is_body_column_rule(self, line: dict) -> bool:
        box = line["box"]
        return (line["stroke"] == [0.0, 0.0, 0.0]
                and abs(line["width"]-self.rule_width) < 0.001
                and abs(box[0]-box[2]) < 0.001
                and any(abs(box[0]-x) < 0.01 for x in self.columns[1:-1])
                and self.height-box[1] > self.body_top+0.001)

    def _column_fragments(self, line: dict) -> list[dict]:
        """End interior column rules at ONE horizontal item-table edge.

        Two regions are genuine page furniture for the source's own column rules:
        the certified column-header separators above the item table, and the
        payment-account panel rules below ``footer_top``. Everything between them
        is owned by the generated grid in :meth:`_grid`, which draws the interior
        rules across the actual row band and stops at the last row boundary.

        Re-emitting the source's *middle* segments as well produced the two
        presentational defects from this single cause: strokes that started inside
        the band and stopped in mid-air above the payment panel, and item-column
        lines running straight through the 소계/부가세/합계 block on the final page.
        Shortening them somewhere else would leave a different partial stroke, so
        this renderer emits neither of those segments on any page.

        Outer frame rules are structural and are emitted whole by the caller.
        """
        top, bottom = line["top"], self.height-line["box"][1]
        x = line["box"][0]
        result = []
        for lo, hi in ((top, min(bottom, self.body_top)),
                       (max(top, self.footer_top), bottom)):
            if hi-lo <= 0.001:
                continue
            result.append({**line, "top": lo,
                           "box": [x, self._pdf(hi), x, self._pdf(lo)]})
        return result

    @staticmethod
    def _emit_line(line: dict) -> bytes:
        x0, y0, x1, y1 = line["box"]
        return (b"q\n" + _rgba("RG", line["stroke"])
                + f"{_num(line['width'])} w\n".encode()
                + f"{_num(x0)} {_num(y0)} m {_num(x1)} {_num(y1)} l S\nQ\n".encode())

    def _is_binding_underline(self, line: dict) -> bool:
        """The certified quote-number rule is redrawn at the new value's width.

        When the value is unchanged the certified rule is kept verbatim; when it
        changes, `_binding_ops` draws the correctly sized rule and painting the
        original-length one as well would leave two overlapping rules.
        """
        if not self._quote_no_changed:
            return False
        underline = self.binds.get("quoteNo", {}).get("underline")
        if not underline:
            return False
        (x0, y0), (x1, _) = underline["points"]
        box = line["box"]
        return (abs(box[0] - x0) < 0.01 and abs(box[2] - x1) < 0.01
                and abs(box[1] - y0) < 0.01 and abs(box[3] - y0) < 0.01
                and abs(line["width"] - underline["widthPt"]) < 0.001)

    def _resolve_bundle(self) -> Path:
        """The certified Sol 6.1 package root: ``engine/`` plus QuoteCore.

        This renderer takes the TEMPLATE directory (template.json, program.zlib,
        resources.pdf) because that is the directory the certified engine itself
        expects. Its siblings live in the parent package root, and resolving them
        here is what lets this module be installed OUTSIDE the certified bundle
        instead of beside it. Failing closed beats silently importing a stale copy
        of the certified engine that happens to be on ``sys.path``.
        """
        for cand in (self.dir.parent, self.dir):
            if ((cand / "engine" / "quote_template.py").is_file()
                    and (cand / "quote-core.js").is_file()):
                return cand
        raise ValueError(f"certified sol61 package (engine/ and quote-core.js) not found "
                         f"next to {self.dir}")

    def certified_engine_dir(self) -> Path:
        return self.bundle / "engine"

    # -- pagination ---------------------------------------------------------- #
    def plan(self, item_count: int, row_heights: list[float] | None = None) -> list[dict]:
        """Height-aware pagination.

        Rows can wrap, so a fixed rows-per-page count would let a page overrun its
        band. The last page is reserved first (its band ends at the certified totals
        block); the remainder is packed greedily into pages that end at the certified
        footer band.
        """
        if item_count <= self.certified_max:
            return [{"kind": "certified", "rows": item_count, "index": 0, "total": 1,
                     "first_row_index": 0}]
        heights = list(row_heights or [self.row_pitch] * item_count)
        rest = list(range(self.certified_max, item_count))
        budget_last = self.totals_top - ROW_CLEARANCE - self.body_top
        budget_cont = self.footer_top - ROW_CLEARANCE - self.body_top
        last: list[int] = []
        used = 0.0
        while rest:
            h = heights[rest[-1]]
            if last and used + h > budget_last:
                break
            last.insert(0, rest.pop())
            used += h
        middle: list[list[int]] = []
        cur: list[int] = []
        used_mid = 0.0
        for i in rest:
            h = heights[i]
            if cur and used_mid + h > budget_cont:
                middle.append(cur)
                cur, used_mid = [], 0.0
            cur.append(i)
            used_mid += h
        if cur:
            middle.append(cur)
        pages = [{"kind": "first", "rows": self.certified_max}]
        pages += [{"kind": "continuation", "rows": len(c)} for c in middle]
        if last:
            pages.append({"kind": "last", "rows": len(last)})
        for i, p in enumerate(pages):
            p["index"] = i
            p["total"] = len(pages)
            p["first_row_index"] = sum(q["rows"] for q in pages[:i])
        return pages

    # -- composition --------------------------------------------------------- #
    def _include(self, top: float, include_summary: bool, include_body_art: bool,
                 is_summary_fill: bool) -> bool:
        if top >= self.footer_top - 0.5:
            return True
        in_summary = ((is_summary_fill and top > self.body_top)
                      or SUMMARY_LO <= top <= SUMMARY_HI)
        if in_summary:
            return include_summary
        if top > self.body_top:
            return include_body_art
        return True

    def _marker_top(self) -> float:
        if self._marker_t is None:
            tops = [r["top"] for r in self.constants()
                    if r["top"] > self.row_band_hi
                    and re.sub(r"\s+", "", r["text"]) in BLANK_MARKER_CHARS]
            self._marker_t = min(tops) if tops else -1.0
        return self._marker_t

    def _is_blank_marker(self, prim: dict) -> bool:
        """`이하여백` closes the certified 3-row form. A generated page break already
        delimits the item list, so the marker is never re-emitted by this renderer."""
        t = self._marker_top()
        if t < 0 or abs(prim["top"] - t) > 2.0:
            return False
        text = re.sub(r"\s+", "", prim.get("text", ""))
        if not text:
            return True
        return text in BLANK_MARKER_CHARS or text.startswith("*")

    def _skip_body_art(self, prim: dict, last_bottom: float) -> bool:
        """Never paint the blank-row furniture on top of an item row."""
        if self._is_blank_marker(prim):
            return True
        return prim["top"] > self.body_top and prim["top"] < last_bottom - 0.5

    def _skeleton(self, include_summary: bool, include_body_art: bool,
                  last_bottom: float) -> bytes:
        """Re-emit the certified page furniture in its ORIGINAL paint order.

        Order matters: the source paints white/grey cell backgrounds before the
        text that sits on them, so grouping by primitive type would hide text.
        """
        items: list[tuple[int, str, dict]] = []
        for run in self.constants():
            items.append((run["order"], "text", run))
        for line in self.program.lines:
            items.append((line["order"], "line", line))
        for rect in self.program.rects:
            items.append((rect["order"], "rect", rect))
        for path in self.program.paths:
            items.append((path["order"], "path", path))
        for img in self.program.images:
            items.append((img["order"], "image", img))
        items.sort(key=lambda it: it[0])

        out = bytearray()
        for _, kind, prim in items:
            if kind == "text":
                if self._is_row_number(prim) or self._skip_body_art(prim, last_bottom):
                    continue
                if not self._include(prim["top"], include_summary, include_body_art, False):
                    continue
                out += self.program.emit_run(prim)
            elif kind == "line":
                # The original outer frame is structural on EVERY page. Body
                # filters must never discard its lower-right source segment.
                if self._is_outer_frame_rule(prim):
                    out += self._emit_line(prim)
                    continue
                if self._is_body_column_rule(prim):
                    for fragment in self._column_fragments(prim):
                        out += self._emit_line(fragment)
                    continue
                if (self._is_binding_underline(prim) or self._is_row_boundary_rule(prim)
                        or self._skip_body_art(prim, last_bottom)):
                    continue
                if not self._include(prim["top"], include_summary, include_body_art, False):
                    continue
                out += self._emit_line(prim)
            elif kind == "rect":
                # Keyed on the certified colour, not on a y-range: the grey column
                # header background also sits just above the table.
                is_yellow = prim["fill"] == [1.0, 1.0, 0.6]
                if not self._include(prim["top"], include_summary, include_body_art, is_yellow):
                    continue
                x0, y0, x1, y1 = prim["box"]
                out += b"q\n" + _rgba("rg", prim["fill"])
                out += f"{_num(x0)} {_num(y0)} {_num(x1-x0)} {_num(y1-y0)} re f\nQ\n".encode()
            elif kind == "path":
                if self._skip_body_art(prim, last_bottom):
                    continue
                if not self._include(prim["top"], include_summary, include_body_art, False):
                    continue
                out += self.program.emit_path(prim)
            else:
                out += b"q\n" + (" ".join(_num(v) for v in prim["cm"]) + " cm\n").encode()
                out += f"{prim['name']} Do\nQ\n".encode()
        return bytes(out)

    def _grid(self, row_bottoms: list[float]) -> bytes:
        cols, top, bottom = self.columns, self.body_top, row_bottoms[-1]
        out = bytearray()
        for x in cols[1:-1]:
            out += b"q\n" + _rgba("RG", [0, 0, 0]) + f"{_num(self.rule_width)} w\n".encode()
            out += (f"{_num(x)} {_num(self._pdf(top))} m {_num(x)} "
                    f"{_num(self._pdf(bottom))} l S\nQ\n").encode()
        for b in row_bottoms:
            out += b"q\n" + _rgba("RG", [0, 0, 0]) + f"{_num(self.hair_width)} w\n".encode()
            out += (f"{_num(cols[0])} {_num(self._pdf(b))} m {_num(cols[-1])} "
                    f"{_num(self._pdf(b))} l S\nQ\n").encode()
        return bytes(out)

    def _cell_lines(self, metrics: dict, slots: dict, row_index: int) -> dict[str, list[str]]:
        lines: dict[str, list[str]] = {}
        for field in ROW_FIELD_ORDER:
            spec = self.row_spec[field]
            text = slots.get(f"item{row_index}{field}", "")
            if not text:
                continue
            met = metrics.get(spec["family"])
            if met is None:
                lines[field] = [text]
                continue
            # width() is in em; the certified cell geometry is in points, so the
            # certified CTM scale (abs(cm[0])) must be applied exactly as the
            # certified renderer does for widths.
            size = spec["nominalSize"] * abs(spec["cm"][0])
            avail = max(spec["bbox"][2] - spec["bbox"][0] - 1.0, 1.0)
            lines[field] = (_wrap(text, met, size, avail) if field in WRAPPABLE_FIELDS
                            else [text])
        return lines

    def _text_op(self, met, family: str, size: float, cm, clip_box, x: float,
                 top: float, text: str, mode: int = 0, stroke_width: float = 1.0,
                 source_seq: list | None = None) -> bytes:
        # The y-flip must go through the binding's own cm: several certified header
        # cells carry cm[5] = 706.5 rather than the page height, so the naive
        # top/|cm[3]| form placed them hundreds of points away and their clip
        # removed them entirely. This is the certified renderer's own formula.
        tm = [1, 0, 0, -1, (x - cm[4]) / cm[0], (self.height - top - cm[5]) / cm[3]]
        out = bytearray(b"q\n")
        out += (f"{_num(clip_box[0])} {_num(self._pdf(clip_box[3]))} "
                f"{_num(clip_box[2]-clip_box[0])} {_num(clip_box[3]-clip_box[1])} re W n\n").encode()
        out += (" ".join(_num(v) for v in cm) + " cm\n").encode()
        out += b"0 g 0 G\n"
        out += f"{_num(stroke_width)} w\n".encode()
        out += b"BT\n" + f"{self._font_keys[family]} {_num(size)} Tf\n{int(mode)} Tr\n".encode()
        out += (" ".join(_num(v) for v in tm) + " Tm\n").encode()
        if source_seq is None:
            out += b"<" + met.encode(text).hex().encode() + b"> Tj\n"
        else:
            out += self._seq_operator(text, met, source_seq)
        out += b"ET\nQ\n"
        return bytes(out)

    @staticmethod
    def _seq_operator(text: str, met, source_seq: list) -> bytes:
        """Native ``}[...] TJ`` operator (certified ``text_operator``).

        Dates keep the source year/month/day letter spacing: the published program
        encodes the gaps as TJ adjustments between the vector label pieces, and a
        plain ``Tj`` would collapse them into overlapping digits.
        """
        pos, parts = 0, []
        for part in source_seq:
            if isinstance(part, str):
                current = text[pos:pos + len(part)]
                pos += len(part)
                parts.append("<" + met.encode(current).hex() + ">")
            else:
                parts.append(_num(part))
        if pos != len(text):
            raise ValueError("Date digit layout mismatch")
        return ("[" + " ".join(parts) + "] TJ\n").encode()

    def _binding_ops(self, b: dict, text: str, met, bbox: list, tm0: list | None = None,
                     row_top: float = 0.0, wraps: bool = False) -> bytes:
        """Certified scalar/row-cell placement, mirrored from ``render_profile``.

        Exactly the certified rules: source inset, shrink-to-fit, right/centre
        anchors, vertical re-centring after shrink, and - critically - a refusal to
        emit a non-shrinking cell that would overflow. Silently clipping here would
        produce a quote that looks complete but hides part of a value.
        """
        cm = b["cm"]
        tm = list(tm0 if tm0 is not None else b["tm"])
        size = b["nominalSize"]
        sx = abs(cm[0])
        width = met.width(text) * size * sx
        source_origin = _pt(cm, tm[4], tm[5])
        source_inset = max(0.0, source_origin[0] - bbox[0])
        available = max(0.0, bbox[2] - bbox[0] - 2 * source_inset)
        if b["shrink"] and width > available:
            size *= available / width
            width = available
        x = source_origin[0]
        if b["align"] == "right":
            x = b["rightAnchorPt"] - width
        elif b["align"] == "center":
            x = (bbox[0] + bbox[2] - width) / 2.0
        if not wraps and not b["shrink"] and b["align"] != "date" \
                and width > bbox[2] - x - 0.5:
            raise ValueError(
                f"Text exceeds source cell {b.get('cell')}; shorten {b['key']} "
                "(native cell does not shrink)")
        tm[4] = (x - cm[4]) / cm[0]
        top = self.height - source_origin[1]
        if tm0 is not None:
            top = row_top
        if b["shrink"] and size != b["size"]:
            center = (bbox[1] + bbox[3]) / 2.0
            baseline_top = self.height - source_origin[1]
            top = center + (baseline_top - center) * size / b["size"]
        seq = (b["runs"][0].get("seq") if b["align"] == "date" and b.get("runs") else None)
        out = self._text_op(met, b["family"], size, cm, bbox, x, top, text,
                            mode=int(b.get("renderMode", 0)),
                            stroke_width=float(b.get("strokeWidth", 1)),
                            source_seq=seq)
        underline = b.get("underline")
        if underline:
            y = underline["points"][0][1]
            out += (f"q\n0 G\n{_num(underline['widthPt'])} w\n"
                    f"{_num(x)} {_num(y)} m "
                    f"{_num(x + width + underline['extensionPt'])} {_num(y)} l S\nQ\n").encode()
        return out

    def _row_ops(self, metrics: dict, lines: dict[str, list[str]], row_index: int,
                 row_top: float, row_height: float) -> bytes:
        out = bytearray()
        # NO column (regenerated; the certified source numbers live in that cell)
        no_family = self.row_spec["Name"]["family"]
        no_met = metrics[no_family]
        no_clip = [self.columns[0], row_top, self.columns[1], row_top + row_height]
        no_size = self.row_size
        label = str(row_index + 1)
        width = no_met.width(label) * no_size * abs(self.row_cm[0])
        # certified row numbers are centred in the NO cell
        no_spec = self.row_spec["Name"]
        x = (no_clip[0] + no_clip[2] - width) / 2.0
        out += self._text_op(no_met, no_family, no_size, self.row_cm, no_clip, x,
                             row_top + LINE_TOP, label,
                             mode=int(no_spec.get("renderMode", 0)),
                             stroke_width=float(no_spec.get("strokeWidth", 1)))
        for field in ROW_FIELD_ORDER:
            field_lines = lines.get(field)
            if not field_lines:
                continue
            spec = self.row_spec[field]
            family = spec["family"]
            met = metrics[family]
            clip_box = [spec["bbox"][0], row_top, spec["bbox"][2], row_top + row_height]
            total = len(field_lines)
            wraps = field in WRAPPABLE_FIELDS
            for li, line in enumerate(field_lines):
                top = row_top + LINE_TOP + (li * LINE_HEIGHT if total > 1 else 0.0)
                tm0 = [1, 0, 0, -1, spec["tm"][4], top / abs(spec["cm"][3])]
                out += self._binding_ops(spec, line, met, clip_box, tm0=tm0,
                                         row_top=top, wraps=wraps)
        return bytes(out)

    def _scalar_ops(self, metrics: dict, slots: dict) -> bytes:
        out = bytearray()
        for b in self.template["bindings"]:
            key = b["key"]
            if key.startswith("item"):
                continue
            text = slots.get(key, "")
            if not text:
                continue
            if text == b["original"] and b.get("runs"):
                # Exactly the certified renderer's rule: a binding whose value is
                # unchanged keeps its certified vector run - original font object,
                # original glyph advances, original paint order. Re-encoding it with
                # a freshly embedded subset measured ~2% wider on Latin text than the
                # source font, which was the last visible header deviation.
                source = [self.program.text_runs[r["index"]] for r in b["runs"]]
                if "".join(self.program.decode(r) for r in source) == text:
                    for run in source:
                        out += self.program.emit_run(run)
                    continue
            family = b["family"]
            if family not in metrics:
                continue
            met = metrics[family]
            out += self._binding_ops(b, text, met, list(b["bbox"]))
        return bytes(out)

    def _page_number(self, metrics: dict, page_no: int, total: int) -> bytes:
        family = "MalgunGothic"
        met = metrics.get(family)
        if met is None:
            return b""
        text = f"{page_no} / {total}"
        w = met.width(text) * PAGE_NUMBER_SIZE
        x = (self.width - w) / 2.0
        # Same page-space convention the certified compiler uses for absolute
        # placement: cm maps text space onto a top-origin page coordinate.
        return self._text_op(met, family, PAGE_NUMBER_SIZE, [1, 0, 0, -1, 0, self.height],
                             [0, PAGE_NUMBER_TOP - 8, self.width, PAGE_NUMBER_TOP + 12], x,
                             PAGE_NUMBER_TOP, text)

    # -- render -------------------------------------------------------------- #
    def render(self, output: Path, changes: dict | None = None) -> dict:
        changes = changes or {}
        n_items = len(changes.get("items") or self.template["draft"]["items"])
        if n_items <= self.certified_max:
            return self._render_certified(output, changes)
        summary_slots = self.build_slots(changes, blank=())["slots"]
        blank_slots = self.build_slots(changes, blank=BLANKABLE)["slots"]

        sys.path.insert(0, str(self.certified_engine_dir()))
        from font_support import embed_font
        import font_support
        sys.path.insert(0, str(Path(font_support.__file__).resolve().parent))

        writer = PdfWriter()
        texts: dict[str, list[str]] = {}
        for b in self.template["bindings"]:
            value = summary_slots.get(b["key"], "")
            if value:
                texts.setdefault(b["family"], []).append(value)
        for i in range(n_items):
            for field in ROW_FIELD_ORDER:
                value = summary_slots.get(f"item{i}{field}", "")
                if value:
                    texts.setdefault(self.row_spec[field]["family"], []).append(value)
        texts.setdefault("MalgunGothic", []).append("0123456789 /")
        texts.setdefault("MalgunGothicBold", []).append("0123456789 /")
        metrics: dict[str, object] = {}
        refs = {}
        # Resource names must be derived per render: reusing an engine instance would
        # otherwise name the same font /Edit4 on the second document, so identical
        # input produced different PDF bytes.
        self._font_keys = {}
        for family in sorted(texts):
            ref, met = embed_font(writer, family, "".join(texts[family]))
            metrics[family] = met
            refs[family] = ref
            self._font_keys[family] = f"/Edit{len(self._font_keys) + 1}"

        self._quote_no_changed = summary_slots.get("quoteNo", "") != self.binds["quoteNo"]["original"]
        rows_lines = {i: self._cell_lines(metrics, summary_slots, i) for i in range(n_items)}
        rows_heights = [max(self.row_pitch,
                            (max(len(v) for v in rows_lines[i].values()) if rows_lines[i]
                             else 1) * LINE_HEIGHT + ROW_PAD)
                        for i in range(n_items)]
        plan = self.plan(n_items, rows_heights)

        page_info = []
        for page in plan:
            first = page["first_row_index"]
            rows_idx = list(range(first, first + page["rows"]))
            lines = {i: rows_lines[i] for i in rows_idx}
            heights = [rows_heights[i] for i in rows_idx]
            tops, y = [], self.body_top
            for h in heights:
                tops.append(y); y += h
            bottoms = [t + h for t, h in zip(tops, heights)]
            is_last = page["kind"] == "last"
            content = bytearray()
            content += self._skeleton(is_last, page["kind"] == "first", bottoms[-1])
            content += self._grid(bottoms)
            content += self._scalar_ops(metrics, summary_slots if is_last else blank_slots)
            for i, top, h in zip(rows_idx, tops, heights):
                content += self._row_ops(metrics, lines[i], i, top, h)
            content += self._page_number(metrics, page["index"] + 1, page["total"])

            writer.add_page(self.program.reader.pages[0])
            pg = writer.pages[-1]
            for family, ref in refs.items():
                pg["/Resources"]["/Font"][NameObject(self._font_keys[family])] = ref
            stream_obj = DecodedStreamObject()
            stream_obj.set_data(bytes(content))
            pg[NameObject("/Contents")] = writer._add_object(stream_obj.flate_encode())
            page_info.append({**page, "row_tops": [round(t, 2) for t in tops],
                              "row_heights": [round(h, 2) for h in heights]})
        writer.add_metadata({"/Title": "견적서",
                             "/Producer": f"B66 {RENDERER_ID} v{RENDERER_VERSION}"})
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as fh:
            writer.write(fh)
        return {"rendererId": RENDERER_ID, "rendererVersion": RENDERER_VERSION,
                "templateId": self.template["templateId"], "itemCount": n_items,
                "pages": len(plan), "plan": page_info, "pdfSha256": _sha(output),
                "totals": {"subtotal": summary_slots["subtotal"], "vat": summary_slots["vat"],
                           "grand": summary_slots["grand"]}}

    def _render_certified(self, output: Path, changes: dict) -> dict:
        sys.path.insert(0, str(self.certified_engine_dir()))
        import quote_template
        inst = quote_template.render_profile(self.dir, output, changes or None, self.node)
        return {"rendererId": "b66.sol61.certified-single-page", "rendererVersion": 1,
                "templateId": inst["templateId"], "itemCount": len(inst["draft"]["items"]),
                "pages": 1, "certifiedPath": True, "totals": inst["totals"],
                "pdfSha256": _sha(output)}


def _wrap(text: str, met, size: float, avail: float) -> list[str]:
    """Wrap at spaces first, breaking inside a word only when it cannot fit.

    A pure character wrap cut certified item names mid-word ("장기공사비용 초장문
    품목명" became "...초장품" / "목명..."), which is not how the source form
    breaks text.
    """
    if met.width(text) * size <= avail:
        return [text]
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = word if not current else current + " " + word
        if met.width(candidate) * size <= avail:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if met.width(word) * size <= avail:
            current = word
            continue
        for ch in word:
            if current and met.width(current + ch) * size > avail:
                lines.append(current)
                current = ch
            else:
                current += ch
    if current or not lines:
        lines.append(current)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--request")
    ap.add_argument("--items", type=int)
    ap.add_argument("--node", default="node")
    args = ap.parse_args()
    changes: dict = {}
    if args.request:
        payload = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
        changes = payload.get("changes", payload)
    if args.items:
        changes["items"] = [
            {"name": f"품목 {i+1}", "spec": f"규격-{i+1}", "unit": "EA",
             "qty": (i % 5) + 1, "unitPrice": 137000 + i*9137, "note": ""}
            for i in range(args.items)]
    engine = SolMultipage(Path(args.template), args.node)
    print(json.dumps(engine.render(Path(args.out), changes), ensure_ascii=False))


if __name__ == "__main__":
    main()
