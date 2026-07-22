"""Deterministic input normalization and segmentation.

Contract (PERSONAL_EDITION_MVP_CONTRACT.md section 4.3):

- normalized input is divided into stable segments before model use;
- segment identifiers are stable and deterministic across repeated runs;
- each segment offset must map exactly to its text in the normalized input;
- empty segments, overlapping offsets, gaps, and duplicate identifiers are
  rejected.

Normalization only rewrites whitespace and line endings; it never changes the
intended meaning of the supplied material. All offset math operates on the
already-normalized text so that normalized[start:end] == segment.text holds
exactly.
"""

from __future__ import annotations

import unicodedata

from app.domain.models import InputSegment
from app.pipeline.errors import SegmentationError

_SEGMENT_ID_PREFIX = "s"
_SEGMENT_ID_WIDTH = 3

# Default per-segment target size in characters. Korean and English are both
# segmented by the same deterministic sentence-boundary scanner; the target only
# controls grouping granularity and does not affect determinism.
DEFAULT_TARGET_CHARS = 480
MAX_SEGMENTS = 32

_SENTENCE_TERMINATORS = frozenset(".!?。！？")
_WHITESPACE_RUN = " \t"
_NEWLINE = "\n"
# Characters that a sentence-ending terminator can absorb (whitespace + newlines).
_TERMINATOR_TRAILING = " \t\n"


def normalize_text(raw_text: str) -> str:
    """Return a deterministically normalized copy of raw_text.

    Steps (all meaning-preserving):
    1. NFKC normalization so visually-identical characters compare equal.
    2. Line-ending normalization (CRLF/CR -> LF).
    3. Collapse runs of spaces/tabs to a single space.
    4. Trim trailing whitespace on every line.
    5. Collapse 3+ consecutive newlines to exactly two (paragraph break).
    6. Strip leading/trailing whitespace from the whole text.

    Raises SegmentationError if the input is empty after stripping.
    """
    if not isinstance(raw_text, str):
        raise SegmentationError("raw_text must be a string")

    text = unicodedata.normalize("NFKC", raw_text)
    text = text.replace("\r\n", _NEWLINE).replace("\r", _NEWLINE)

    out_chars: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in _WHITESPACE_RUN:
            j = i
            while j < n and text[j] in _WHITESPACE_RUN:
                j += 1
            # Collapse to a single space, but never absorb a newline.
            if j < n and text[j] == _NEWLINE:
                # Drop trailing spaces before a newline entirely.
                i = j
                continue
            out_chars.append(" ")
            i = j
        else:
            out_chars.append(ch)
            i += 1

    text = "".join(out_chars)

    # Trim trailing whitespace on each line.
    lines = text.split(_NEWLINE)
    text = _NEWLINE.join(line.rstrip(_WHITESPACE_RUN) for line in lines)

    # Collapse 3+ newlines to exactly two.
    collapsed: list[str] = []
    newline_run = 0
    for ch in text:
        if ch == _NEWLINE:
            newline_run += 1
            if newline_run <= 2:
                collapsed.append(ch)
        else:
            newline_run = 0
            collapsed.append(ch)
    text = "".join(collapsed)

    text = text.strip()
    if not text:
        raise SegmentationError("input is empty after normalization")
    return text


def _iter_sentences(text: str):
    """Yield (start, end) offsets of sentences within text.

    A sentence extends from the current position to the next sentence
    terminator (inclusive). Newlines that follow a terminator, or act as a
    standalone paragraph break, also terminate a sentence. Trailing whitespace
    after a terminator is attached to the preceding sentence so that the next
    sentence starts on a non-space character.
    """
    n = len(text)
    start = 0
    i = 0
    while i < n:
        ch = text[i]
        if ch in _SENTENCE_TERMINATORS:
            j = i + 1
            # Absorb any trailing whitespace or newlines immediately
            # following the terminator. This ensures paragraph breaks
            # are included in the preceding sentence's offset range so
            # offsets remain contiguous.
            while j < n and text[j] in _TERMINATOR_TRAILING:
                j += 1
            yield start, j
            start = j
            i = j
            continue
        if ch == _NEWLINE:
            # A newline ends the current sentence (paragraph boundary). Absorb
            # a following blank line so the next sentence starts cleanly. The
            # newline bytes are attributed to the preceding sentence so that
            # offsets remain contiguous (no gap between segments).
            j = i + 1
            while j < n and text[j] == _NEWLINE:
                j += 1
            while j < n and text[j] in _WHITESPACE_RUN:
                j += 1
            if start < i:
                yield start, j
                start = j
                i = j
                continue
            # Leading newline with no preceding content: skip it.
            start = j
            i = j
            continue
        i += 1
    if start < n:
        yield start, n


def _format_segment_id(index: int) -> str:
    return f"{_SEGMENT_ID_PREFIX}{index + 1:0{_SEGMENT_ID_WIDTH}d}"


def segment_text(
    text: str,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
) -> list[InputSegment]:
    """Segment text into stable, non-overlapping, gap-free segments.

    Sentences are grouped until target_chars is reached; a segment never splits
    a sentence. A single sentence longer than target_chars becomes its own
    segment. Segment identifiers are s001, s002, ... assigned in document order.

    Raises SegmentationError on empty input, too many segments, or when the
    resulting offsets fail the exact-text invariant.
    """
    normalized = normalize_text(text)

    if not isinstance(target_chars, int) or target_chars < 1:
        raise SegmentationError("target_chars must be a positive integer")

    sentences = list(_iter_sentences(normalized))
    if not sentences:
        raise SegmentationError("normalized input produced no sentences")

    segments: list[InputSegment] = []
    current_start = sentences[0][0]
    current_end = sentences[0][0]
    for sent_start, sent_end in sentences:
        if sent_start != current_end:
            # Should never happen with a well-formed sentence iterator; guard
            # against gaps or overlaps caused by implementation errors.
            raise SegmentationError(
                "sentence offsets are not contiguous"
            )
        prospective_len = (sent_end - current_start)
        if (
            current_end > current_start
            and prospective_len > target_chars
        ):
            # Close the current segment before this sentence so we never split
            # a sentence and never exceed the target once we already have one.
            segments.append(
                _make_segment(len(segments), normalized, current_start, current_end)
            )
            current_start = sent_start
        current_end = sent_end

    if current_end > current_start:
        segments.append(
            _make_segment(len(segments), normalized, current_start, current_end)
        )

    if not segments:
        raise SegmentationError("segmentation produced no segments")

    if len(segments) > MAX_SEGMENTS:
        raise SegmentationError(
            f"segmentation produced {len(segments)} segments; "
            f"maximum is {MAX_SEGMENTS}"
        )

    verify_segments(normalized, segments)
    return segments


def _make_segment(index: int, normalized: str, start: int, end: int) -> InputSegment:
    if end <= start:
        raise SegmentationError(
            f"segment {index} has non-positive length (start={start}, end={end})"
        )
    text = normalized[start:end]
    if not text.strip():
        raise SegmentationError(f"segment {index} is empty after slicing")
    return InputSegment(
        segment_id=_format_segment_id(index),
        text=text,
        start_offset=start,
        end_offset=end,
    )


def verify_segments(normalized: str, segments: list[InputSegment]) -> None:
    """Assert the exact-offset, contiguity, and uniqueness invariants.

    Raises SegmentationError if any invariant is violated. This is the single
    source of truth for the offset contract and is reused by the service and
    tests.
    """
    if not segments:
        raise SegmentationError("segments must be a non-empty list")

    ids_seen: set[str] = set()
    expected_start = 0
    # Segments must begin at offset 0 and be contiguous with no gaps/overlaps.
    first_start = segments[0].start_offset
    if first_start != expected_start:
        raise SegmentationError(
            f"first segment must start at offset 0 (got {first_start})"
        )

    for idx, seg in enumerate(segments):
        if seg.start_offset != expected_start:
            raise SegmentationError(
                f"segment {idx} ({seg.segment_id}) starts at "
                f"{seg.start_offset}, expected {expected_start} "
                "(gap or overlap detected)"
            )
        if seg.end_offset < seg.start_offset:
            raise SegmentationError(
                f"segment {idx} ({seg.segment_id}) end < start"
            )
        actual = normalized[seg.start_offset:seg.end_offset]
        if actual != seg.text:
            raise SegmentationError(
                f"segment {idx} ({seg.segment_id}) text does not match "
                "normalized[start:end] (offset mismatch)"
            )
        if not seg.text.strip():
            raise SegmentationError(
                f"segment {idx} ({seg.segment_id}) is empty"
            )
        if seg.segment_id in ids_seen:
            raise SegmentationError(
                f"duplicate segment_id: {seg.segment_id}"
            )
        ids_seen.add(seg.segment_id)
        expected_start = seg.end_offset

    if expected_start != len(normalized):
        raise SegmentationError(
            f"segments do not cover the full normalized text "
            f"(covered {expected_start} of {len(normalized)} chars)"
        )
