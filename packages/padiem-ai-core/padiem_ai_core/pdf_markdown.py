"""PDF to Markdown conversion on the canonical reviewed pypdf reader (#5568).

Why this module exists
----------------------
``document_normalization.inspect_pdf`` is the repository's reviewed in-process
PDF *inspection* boundary: it opens the single canonical ``pypdf`` reader, reads
each page's native text layer under the existing per-page character ceiling and
returns bounded page provenance. ``document_parser_boundary`` guards the other
path — the unbounded ``extract_binary_document`` normalizer that feeds model
context — and that decision is untouched here.

Conversion is a separate, explicitly bounded product surface. It projects the
same native text layer into a Markdown document using the text matrices the
reader already reports, and never calls a provider, model or OCR engine.

What this module deliberately does NOT do
-----------------------------------------
* No OCR, vision or model call exists. A page with no native text layer is
  reported as unreadable inside the document; nothing is guessed for it.
* No second PDF reader. Every byte comes through ``_open_pdf_reader``.
* No new resource ceiling. Page count, per-page text size and document identity
  reuse the existing Core bounds.
* ``precise`` mode is declared and refused, never silently downgraded to ``fast``.
* Orientation is judged from the text matrices. The ``/Rotate`` entry is not
  trusted: a page can declare 0 and still carry turned content.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any
import unicodedata

from .document_normalization import (
    # #5734 stage 2: imported, not applied. The conversion enforces no page
    # count and no per-page text length; the names stay so this module can
    # never grow a second, quieter ceiling than Core's vocabulary.
    MAX_PDF_PAGES,
    MAX_PDF_PAGE_TEXT_CHARS,
    DocumentNormalizationError,
    _open_pdf_reader,
    validate_document_identity,
)

#: Wired modes. ``precise`` needs an OCR authority this runtime does not have.
CONVERT_MODE_FAST = "fast"
CONVERT_MODE_VERIFY = "verify"
SUPPORTED_CONVERT_MODES = (CONVERT_MODE_FAST, CONVERT_MODE_VERIFY)
CONVERT_MODE_PRECISE = "precise"
#: Bounded reason for the unwired mode; the caller surfaces it, never guesses.
PRECISE_MODE_UNAVAILABLE = "pdf_precise_mode_unavailable"

#: Provenance anchor emitted at the start of every converted page, so the result
#: document and the reviewing UI address the same page. Line numbers are the
#: emitter's own measure, never an invented coordinate.
PAGE_ANCHOR_PREFIX = "<!-- padiem:page "
PAGE_ANCHOR_SUFFIX = " -->"

#: Below this many points the layout says the two runs are one word.
_SPACE_GAP_RATIO = 0.28
#: Runs this close in y are the same visual line, scaled by the run's own height.
_LINE_TOLERANCE_RATIO = 0.45
#: A run this much taller than the page body is a heading; taller is a title.
_HEADING_BODY_RATIO = 1.18
_TITLE_BODY_RATIO = 1.45
#: A table candidate needs this many aligned rows and this many cells per row.
_TABLE_MIN_ROWS = 3
_TABLE_MIN_CELLS = 2
#: Two column starts closer than this are the same column.
_COLUMN_TOLERANCE_PT = 4.0
#: Whitespace this wide (in em of the taller run) is a column gap, not a word
#: gap. Reflowed text chunks sit closer than this, so a table needs real air.
_COLUMN_GAP_EM = 1.2
#: Width this module charges one glyph, in em. Only ever used to measure the
#: empty space *between* runs; no coordinate is asserted about the page.
_ADVANCE_PER_GLYPH = 0.5
#: A vertical gap this much wider than the page's own leading starts a new
#: paragraph. Whitespace is the only paragraph signal a text layer carries, so
#: this is measured from the document, never assumed from a template.
_PARAGRAPH_LEADING_RATIO = 1.4
_PARAGRAPH_BODY_RATIO = 1.5
#: A page whose prose sits under this share of its characters is layout-heavy:
#: rules, stamps and artwork dominate, so structural guessing is unreliable.
_SPARSE_PAGE_SHARE = 0.5
#: Sequence matching is quadratic; above this many tokens order is not computed.
_ORDER_TOKEN_CEILING = 1200
#: Text this far from vertical counts as turned content.
_ROTATION_TOLERANCE_DEG = 20.0

_BULLET_CHARS = "•◦▪▸‣·∙○●◆◇■□★☆⁃-"
_BULLET_LINE = re.compile(rf"^\s*[{re.escape(_BULLET_CHARS)}*_]\s+(?P<text>\S.*)$")
_NUMBERED_LINE = re.compile(
    r"^\s*(?P<marker>\d{1,3}[.)]|\d{1,3}\.|[가-힣][.)]|[가-힣]\.|제\s*\d+\s*[조항항])\s+"
    r"(?P<text>\S.*)$"
)
_WHITESPACE_RUN = re.compile(r"\s+")
#: #5568 T1: the layer put whitespace inside what reads as one number.
_SPLIT_NUMBER = re.compile(r"(?<=\d)[ \u00a0](?=\d)")
#: #5568 T5: a dot-grouped number reads as a decimal in the other convention.
#: The value is transcribed verbatim; this marks it for the reviewer instead of
#: interpreting it, because only the document knows which one it was.
_SEPARATOR_AMBIGUITY = re.compile(r"\d{1,3}(?:\.\d{3})+")
_HANGUL_SYLLABLE = re.compile(r"[\uac00-\ud7a3]")
_HANGUL_SPACED = re.compile(r"[\uac00-\ud7a3]\s+[\uac00-\ud7a3]")
_DIGIT_GROUP = re.compile(r"\d+")
#: A line this module already emitted as a list item.
_MD_ITEM = re.compile(r"^(?:[-*]|\d{1,3}\.)\s")


@dataclass(frozen=True, slots=True)
class ConversionNotices:
    """Caller-supplied product wording for the two structural notices.

    Core stays locale-free: the route owns the sentence, this module owns the
    condition that puts it in the document.
    """

    unreadable_page: str = (
        "This page carries no native text layer. Precise conversion needs an OCR "
        "authority this runtime does not provide, so nothing was guessed."
    )

    @staticmethod
    def rotated_page_marker() -> str:
        return "rotated_text_layer"


DEFAULT_NOTICES = ConversionNotices()


@dataclass(frozen=True, slots=True)
class ConvertedPage:
    """One converted page with the emitter's own line provenance."""

    number: int
    start_line: int
    end_line: int
    native_text_present: bool
    rotated_text: bool
    character_count: int

    def public_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "native_text_present": self.native_text_present,
            "rotated_text": self.rotated_text,
            "character_count": self.character_count,
        }


@dataclass(frozen=True, slots=True)
class Mismatch:
    """One bounded structural disagreement carried by the text layer."""

    page: int
    kind: str
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {"page": self.page, "kind": self.kind, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class PageAgreement:
    """Per-page agreement between the result and the source text layer.

    These measure the *character layer*, not the printed page. A faithful
    transcription of a damaged layer scores high and is still wrong at the
    source, so this is never presented as accuracy.
    """

    page: int
    character_coverage: float
    digit_preservation: float | None
    reading_order: float | None
    rotated_text: bool

    def public_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "character_coverage": round(self.character_coverage, 4),
            "digit_preservation": (
                None if self.digit_preservation is None
                else round(self.digit_preservation, 4)
            ),
            "reading_order": (
                None if self.reading_order is None else round(self.reading_order, 4)
            ),
            "rotated_text": self.rotated_text,
        }


@dataclass(frozen=True, slots=True)
class ConversionResult:
    name: str
    media_type: str
    byte_size: int
    page_count: int
    markdown: str
    mode: str
    pages: tuple[ConvertedPage, ...]
    agreement: tuple[PageAgreement, ...] = ()
    mismatches: tuple[Mismatch, ...] = ()
    warnings: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "page_count": self.page_count,
            "mode": self.mode,
            "character_count": len(self.markdown),
            "line_count": self.markdown.count("\n") + 1,
            "pages": [page.public_dict() for page in self.pages],
            "agreement": [row.public_dict() for row in self.agreement],
            "mismatches": [row.public_dict() for row in self.mismatches],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class _Run:
    text: str
    x: float
    y: float
    height: float
    angle: float


@dataclass(slots=True)
class _Line:
    y: float
    height: float
    runs: list[_Run]

    @property
    def text(self) -> str:
        return _join_runs(self.runs)


def _matrix_point(cm: Any, tm: Any) -> tuple[float, float, float, float]:
    """Return the run's page point, glyph height and baseline angle in degrees."""

    a, b = float(tm[0]), float(tm[1])
    ex, ey = float(tm[4]), float(tm[5])
    if cm is not None and len(cm) >= 6:
        ca, cb, cc, cd, ce, cf = (float(value) for value in cm[:6])
        x, y = ca * ex + cc * ey + ce, cb * ex + cd * ey + cf
        # The content matrix rotates the baseline as well as the pen position.
        a, b = ca * a + cc * b, cb * a + cd * b
    else:
        x, y = ex, ey
    height = math.hypot(a, b) or abs(float(tm[3]))
    angle = math.degrees(math.atan2(b, a)) if (a or b) else 0.0
    return x, y, height, angle


def _collect_runs(page: Any) -> tuple[list[_Run], str]:
    """Return the positioned text runs and the page's native text layer.

    One extraction pass produces both: ``extract_text`` hands its visitor the
    content matrix and text matrix of every text-showing operator it renders
    into the returned layer, so the geometry and the text can never disagree.
    """

    runs: list[_Run] = []

    def visit(text: str, cm: Any, tm: Any, font_dict: Any, font_size: Any) -> None:
        if not text or not text.strip():
            return
        x, y, height, angle = _matrix_point(cm, tm)
        if not height:
            return
        runs.append(_Run(text=text, x=x, y=y, height=height, angle=angle))

    layer = page.extract_text(visitor_text=visit) or ""
    return runs, layer


def _group_lines(runs: list[_Run], page_height: float) -> list[_Line]:
    """Bucket runs into visual lines and flip y so the page top sorts first."""

    lines: list[_Line] = []
    for run in sorted(runs, key=lambda item: (-item.y, item.x)):
        y = page_height - run.y
        tolerance = max(0.6, run.height * _LINE_TOLERANCE_RATIO)
        placed = next(
            (candidate for candidate in lines if abs(candidate.y - y) <= tolerance),
            None,
        )
        moved = _Run(text=run.text, x=run.x, y=y, height=run.height, angle=run.angle)
        if placed is None:
            lines.append(_Line(y=y, height=run.height, runs=[moved]))
        else:
            placed.height = max(placed.height, run.height)
            placed.runs.append(moved)
    lines.sort(key=lambda line: line.y)
    for line in lines:
        line.runs.sort(key=lambda run: run.x)
    return lines


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _join_runs(runs: list[_Run]) -> str:
    """Rebuild one line, inserting a space only where the layout asks for one."""

    if not runs:
        return ""
    unit = _median([run.height for run in runs if run.height]) or 1.0
    parts = [runs[0].text]
    previous = runs[0]
    for current in runs[1:]:
        gap = current.x - previous.x
        bridge = (previous.text[-1:].isspace() or current.text[:1].isspace())
        if not bridge and gap > previous.height * _SPACE_GAP_RATIO:
            parts.append(" ")
        parts.append(current.text)
        previous = current
    return unicodedata.normalize("NFC", "".join(parts)).strip()


def _body_size(lines: list[_Line]) -> float:
    heights = [run.height for line in lines for run in line.runs]
    return _median([height for height in heights if height])


def _leading(lines: list[_Line]) -> float:
    """The page's own typical baseline-to-baseline distance."""

    gaps = [
        current.y - previous.y
        for previous, current in zip(lines, lines[1:])
        if current.y > previous.y
    ]
    return _median(gaps)


def _starts_paragraph(previous: _Line | None, line: _Line, body: float, leading: float) -> bool:
    """True when the whitespace above this line is wider than the page's leading."""

    if previous is None:
        return False
    gap = line.y - previous.y
    return gap > body * _PARAGRAPH_BODY_RATIO and gap > leading * _PARAGRAPH_LEADING_RATIO


def _digit_fragmented(lines: list[_Line]) -> bool:
    """#5568 T1: a row of running text whose layer splits one number.

    Only ordinary prose is judged. A columnar row is a table, and there two
    digit groups really are two cells, so the same spacing is not a defect.
    """

    for line in lines:
        if _is_columnar(line):
            continue
        if _SPLIT_NUMBER.search(line.text):
            return True
    return False


def _is_sparse(lines: list[_Line], body: float) -> bool:
    total = sum(len(line.text) for line in lines)
    if total == 0:
        return True
    if not body or len(lines) < 3:
        return False
    near_body = sum(
        len(line.text)
        for line in lines
        if line.height >= body * 0.9 and line.height <= body * 1.15
    )
    return near_body / total < _SPARSE_PAGE_SHARE


def _heading_level(line: _Line, body: float) -> int | None:
    text = line.text
    if not text or len(text) > 120:
        return None
    ratio = line.height / body if body else 0.0
    if ratio >= _TITLE_BODY_RATIO:
        return 1
    if ratio >= _HEADING_BODY_RATIO:
        return 2
    return None


def _column_anchors(window: list[_Line]) -> list[float]:
    """Cluster the runs of the window into the columns they actually share."""

    xs = sorted(run.x for line in window for run in line.runs)
    anchors: list[float] = []
    for value in xs:
        if not anchors or value - anchors[-1] > _COLUMN_TOLERANCE_PT:
            anchors.append(value)
    return anchors


def _row_cells(line: _Line, anchors: list[float]) -> list[str]:
    cells = [""] * len(anchors)
    for run in line.runs:
        index = min(
            range(len(anchors)),
            key=lambda position: abs(run.x - anchors[position]),
        )
        value = run.text.strip()
        cells[index] = f"{cells[index]} {value}".strip() if cells[index] else value
    return cells


def _advance_of(run: _Run) -> float:
    """Estimated horizontal advance of a run, used only to size the gap after it."""

    return len(run.text.rstrip()) * run.height * _ADVANCE_PER_GLYPH


def _is_columnar(line: _Line) -> bool:
    """True when every run boundary on the line is separated by real air.

    Reflowed prose arrives as adjacent chunks, so this is what tells a column
    layout from one sentence chopped into text-showing operators.
    """

    if len(line.runs) < _TABLE_MIN_CELLS:
        return False
    for previous, current in zip(line.runs, line.runs[1:]):
        gap = current.x - previous.x - _advance_of(previous)
        if gap < max(current.height, previous.height) * _COLUMN_GAP_EM:
            return False
    return True


def _detect_table(lines: list[_Line], start: int) -> tuple[int, list[list[str]]] | None:
    """Read a column-aligned block as a table from the runs' own x positions."""

    if start + _TABLE_MIN_ROWS > len(lines):
        return None
    window: list[_Line] = []
    index = start
    while index < len(lines) and len(window) < 24:
        line = lines[index]
        if not _is_columnar(line):
            break
        window.append(line)
        index += 1
    if len(window) < _TABLE_MIN_ROWS:
        return None
    anchors = _column_anchors(window)
    if len(anchors) < _TABLE_MIN_CELLS:
        return None
    rows = [_row_cells(line, anchors) for line in window]
    if not any(any(cell for cell in row) for row in rows):
        return None
    return len(window), rows


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _table_markdown(rows: list[list[str]]) -> list[str]:
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    out = [
        "| " + " | ".join(_escape_cell(cell) for cell in padded[0]) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    out.extend(
        "| " + " | ".join(_escape_cell(cell) for cell in row) + " |"
        for row in padded[1:]
    )
    return out


def _list_markdown(text: str) -> str | None:
    bullet = _BULLET_LINE.match(text)
    if bullet:
        return f"- {bullet.group('text').strip()}"
    numbered = _NUMBERED_LINE.match(text)
    if numbered:
        marker = numbered.group("marker").strip().rstrip(".)")
        if marker.startswith("제"):
            return text
        return f"{marker}. {numbered.group('text').strip()}"
    return None


def _anchor(number: int) -> str:
    return f"{PAGE_ANCHOR_PREFIX}{number}{PAGE_ANCHOR_SUFFIX}"


def _page_lines(
    page: Any, number: int, notices: ConversionNotices
) -> tuple[list[str], list[_Run], str, bool]:
    """Project one page's text layer into Markdown lines.

    Returns the emitted lines, the positioned runs, the page's raw layer, and
    whether that layer splits a number inside running prose. A blank line
    between pages is the document builder's business, so the line range a page
    reports always covers exactly its own content.
    """

    runs, layer = _collect_runs(page)
    if not layer.strip():
        return [_anchor(number), f"> {notices.unreadable_page}"], [], layer, False
    try:
        page_height = float(page.mediabox.height)
    except Exception as exc:
        raise DocumentNormalizationError(
            "pdf_page_geometry_unavailable", "PDF page geometry could not be read safely."
        ) from exc
    if not runs:
        return [_anchor(number), layer], [], layer, False
    lines = _group_lines(runs, page_height)
    body = _body_size(lines)
    leading = _leading(lines)
    sparse = _is_sparse(lines, body)
    out: list[str] = [_anchor(number)]
    pending: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        text = line.text
        if not text:
            index += 1
            continue
        if not sparse:
            table = _detect_table(lines, index)
            if table is not None:
                if pending:
                    out.append(" ".join(pending).strip())
                    pending = []
                out.extend(_table_markdown(table[1]))
                out.append("")
                index += table[0]
                continue
        level = None if sparse else _heading_level(line, body)
        if level is not None:
            if pending:
                out.append(" ".join(pending).strip())
                pending = []
            if out and out[-1].strip():
                out.append("")
            out.extend(["#" * level + " " + text, ""])
            index += 1
            continue
        item = None if line.height > body * 1.1 else _list_markdown(text)
        if item is not None:
            if pending:
                out.append(" ".join(pending).strip())
                pending = []
                out.append("")
            # A list glued under a paragraph line is a lazy continuation, so the
            # block needs its own blank line before it starts.
            if out and out[-1].strip() and not _MD_ITEM.match(out[-1]):
                out.append("")
            out.append(item)
            index += 1
            continue
        if pending and _starts_paragraph(lines[index - 1] if index else None, line, body, leading):
            out.append(" ".join(pending).strip())
            out.append("")
            pending = []
        pending.append(text)
        index += 1
    if pending:
        out.append(" ".join(pending).strip())
    return out, runs, layer, _digit_fragmented(lines)


def _is_rotated(runs: list[_Run]) -> bool:
    """Judge orientation from the text matrices, never from the /Rotate entry."""

    angles = [run.angle for run in runs]
    if not angles:
        return False
    turned = sum(
        1
        for angle in angles
        if min(abs(abs(angle) - 90.0), abs(abs(angle) - 270.0)) <= _ROTATION_TOLERANCE_DEG
    )
    return turned / len(angles) >= 0.6


def _fold(text: str) -> str:
    return _WHITESPACE_RUN.sub(" ", text).strip()


def _multiset(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for char in text:
        if not char.isspace():
            counts[char] = counts.get(char, 0) + 1
    return counts


def _coverage(source: str, converted: str) -> float:
    """Share of the source layer's characters that survive in the result."""

    wanted = _multiset(source)
    total = sum(wanted.values())
    if not total:
        return 1.0
    got = _multiset(converted)
    kept = sum(min(count, got.get(char, 0)) for char, count in wanted.items())
    return kept / total


def _digit_preservation(source: str, converted: str) -> float | None:
    """Token-level digit retention: a split number is a lost number."""

    wanted = _DIGIT_GROUP.findall(source)
    if not wanted:
        return None
    remaining: dict[str, int] = {}
    for token in _DIGIT_GROUP.findall(converted):
        remaining[token] = remaining.get(token, 0) + 1
    kept = 0
    for token in wanted:
        if remaining.get(token, 0) > 0:
            remaining[token] -= 1
            kept += 1
    return kept / len(wanted)


def _reading_order(source: str, converted: str) -> float | None:
    """Longest-common-subsequence share over word tokens, or None if unbounded."""

    from difflib import SequenceMatcher

    left = _fold(source).split()
    right = _fold(converted).split()
    if not left:
        return None
    if len(left) > _ORDER_TOKEN_CEILING or len(right) > _ORDER_TOKEN_CEILING:
        return None
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _layer_mismatches(
    page: int, source: str, converted: str, digit_fragmented: bool
) -> list[Mismatch]:
    """Report the layer defects #5568 named, on the page that carries them."""

    found: list[Mismatch] = []
    if not source.strip():
        found.append(Mismatch(
            page, "no_source_layer",
            "The page carries no native text layer, so its agreement numbers are "
            "vacuous and nothing was verified against the printed page.",
        ))
        return found
    if digit_fragmented:
        found.append(Mismatch(
            page, "digit_fragmentation",
            "The source text layer places whitespace inside a digit sequence in "
            "running text.",
        ))
    if _SEPARATOR_AMBIGUITY.search(source):
        found.append(Mismatch(
            page, "separator_ambiguity",
            "The source text layer carries a grouped number whose separator "
            "convention is ambiguous; the token is transcribed, not interpreted.",
        ))
    if (
        _HANGUL_SPACED.search(source)
        and not _HANGUL_SPACED.search(converted)
        and _HANGUL_SYLLABLE.search(converted)
    ):
        found.append(Mismatch(
            page, "syllable_spacing_loss",
            "Spaces between Hangul syllables are absent from the result.",
        ))
    if not converted.strip():
        found.append(Mismatch(
            page, "empty_result", "The result carries no text for this page."
        ))
    return found


def _plain_projection(markdown: str) -> str:
    """Strip only the Markdown syntax this module itself emitted.

    Agreement compares text, so a heading's ``#`` or a table's ``|`` must not
    count as a character the source layer lost. Nothing else is removed: a word
    that never reached the result still shows up as missing.
    """

    kept: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(PAGE_ANCHOR_PREFIX):
            continue
        skeleton = stripped.replace("|", "").replace(" ", "")
        if skeleton and set(skeleton) == {"-"}:
            continue
        text = re.sub(r"^#+\s+", "", stripped)
        text = re.sub(r"^[-*]\s+", "", text)
        text = re.sub(r"^>\s?", "", text)
        if text.startswith("|") and text.endswith("|"):
            text = " ".join(cell.strip() for cell in text.strip("|").split("|") if cell.strip())
        kept.append(text)
    return "\n".join(kept)


def _page_slice(markdown: str, number: int, page_count: int) -> str:
    """Slice one page's own Markdown out of the emitted document by its anchor."""

    anchor = _anchor(number)
    position = markdown.find(anchor)
    if position < 0:
        return ""
    start = position + len(anchor)
    if number < page_count:
        end = markdown.find(_anchor(number + 1), start)
        return markdown[start:] if end < 0 else markdown[start:end]
    return markdown[start:]


def convert_pdf_to_markdown(
    *,
    name: Any,
    media_type: Any,
    payload: Any,
    mode: str = CONVERT_MODE_FAST,
    notices: ConversionNotices = DEFAULT_NOTICES,
) -> ConversionResult:
    """Convert one PDF's native text layer into a Markdown document.

    ``verify`` adds the page-addressed agreement report against that same text
    layer. It does not look at the rendered page and does not claim to.
    """

    if mode == CONVERT_MODE_PRECISE:
        raise DocumentNormalizationError(
            PRECISE_MODE_UNAVAILABLE,
            "Precise conversion needs an OCR authority this runtime does not provide.",
        )
    if mode not in SUPPORTED_CONVERT_MODES:
        raise DocumentNormalizationError("invalid_convert_mode", "Unknown conversion mode.")
    safe_name, safe_media = validate_document_identity(
        name=name, media_type=media_type, source_kind="binary"
    )
    if safe_media != "application/pdf":
        raise DocumentNormalizationError(
            "unsupported_binary_media_type", "Only PDF documents convert to Markdown."
        )
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise DocumentNormalizationError(
            "invalid_binary_payload", "PDF payload must be non-empty bytes."
        )
    binary = bytes(payload)
    reader = _open_pdf_reader(binary)
    emitted: list[list[str]] = []
    layers: list[str] = []
    rotated: list[bool] = []
    fragmented_pages: list[bool] = []
    try:
        page_count = len(reader.pages)
        if page_count < 1:
            raise DocumentNormalizationError(
                "pdf_no_pages", "PDF contains no readable pages."
            )
        # #5734 stage 2: a page count is not a reason to refuse a document. What
        # bounds this conversion is the work it actually does per page, not a
        # PADIEM number for how long a normal contract may be.
        for number, page in enumerate(reader.pages, start=1):
            try:
                lines, runs, layer, fragmented = _page_lines(page, number, notices)
            except DocumentNormalizationError:
                raise
            except Exception as exc:
                raise DocumentNormalizationError(
                    "pdf_page_text_invalid", "PDF page text could not be read safely."
                ) from exc
            # Same judgement per page: a dense page is a dense page.
            emitted.append(lines)
            layers.append(layer)
            fragmented_pages.append(fragmented)
            rotated.append(_is_rotated(runs))
    finally:
        close = getattr(reader, "close", None)
        if callable(close):
            close()

    body: list[str] = []
    pages: list[ConvertedPage] = []
    cursor = 1
    for index, lines in enumerate(emitted):
        if index:
            body.append("")
            cursor += 1
        start = cursor
        body.extend(lines)
        cursor += len(lines)
        pages.append(ConvertedPage(
            number=index + 1,
            start_line=start,
            end_line=cursor - 1,
            native_text_present=bool(layers[index].strip()),
            rotated_text=rotated[index],
            character_count=len(layers[index]),
        ))
    markdown = "\n".join(body).strip() + "\n"

    warnings = [
        *(f"unreadable_page:{page.number}" for page in pages if not page.native_text_present),
        *(f"{ConversionNotices.rotated_page_marker()}:{page.number}" for page in pages if page.rotated_text),
    ]
    agreement: tuple[PageAgreement, ...] = ()
    mismatches: tuple[Mismatch, ...] = ()
    if mode == CONVERT_MODE_VERIFY:
        rows: list[PageAgreement] = []
        found: list[Mismatch] = []
        for index, page in enumerate(pages):
            converted = _fold(_plain_projection(_page_slice(markdown, page.number, page_count)))
            rows.append(PageAgreement(
                page=page.number,
                character_coverage=_coverage(layers[index], converted),
                digit_preservation=_digit_preservation(layers[index], converted),
                reading_order=_reading_order(layers[index], converted),
                rotated_text=page.rotated_text,
            ))
            found.extend(
                _layer_mismatches(page.number, layers[index], converted, fragmented_pages[index])
            )
        agreement = tuple(rows)
        mismatches = tuple(found)
    return ConversionResult(
        name=safe_name,
        media_type=safe_media,
        byte_size=len(binary),
        page_count=page_count,
        markdown=markdown,
        mode=mode,
        pages=tuple(pages),
        agreement=agreement,
        mismatches=mismatches,
        warnings=tuple(warnings),
    )


__all__ = [
    "CONVERT_MODE_FAST",
    "CONVERT_MODE_PRECISE",
    "CONVERT_MODE_VERIFY",
    "ConversionNotices",
    "ConversionResult",
    "ConvertedPage",
    "DEFAULT_NOTICES",
    "Mismatch",
    "PAGE_ANCHOR_PREFIX",
    "PAGE_ANCHOR_SUFFIX",
    "PRECISE_MODE_UNAVAILABLE",
    "PageAgreement",
    "SUPPORTED_CONVERT_MODES",
    "convert_pdf_to_markdown",
]
