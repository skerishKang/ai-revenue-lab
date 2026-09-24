"""#2828: bounded wire contract for the kagent-local PaddleOCR child adapter.

The OCR adapter is two processes, so every value that crosses between them needs
exactly one owner. This module is that owner: the request envelope, the child
report, the pinned official model manifests, the bounded reason-code vocabulary
and every count/character/box/byte ceiling live here and are *derived* from the
existing Core image bounds rather than guessed into existence.

What crosses the boundary
-------------------------
Only a **canonical sanitized single-frame PNG** produced by the existing Core
``transform_image`` (#3037) crosses into the child, plus two explicit local
model directory paths. The original untrusted caller payload, the original
filename, the caller's environment and every image fact stay on the parent side
of the boundary.

Authority boundaries
--------------------
- ``CORE != OCR_AUTHORITY``. Every ceiling below is read from
  :mod:`padiem_ai_core.image_helpers`; nothing here can widen an image bound and
  no Core source changes for OCR.
- ``ORIGINAL_SOURCE_BYTES_TO_OCR_CHILD=0``. The #2824 intake gate and the #3037
  Core transform are the only authorities over untrusted source bytes, and the
  Core transform emits the canonical PNG. The original bytes are never handed
  to the child, so the child never sees an attacker-shaped artifact.
- ``SECOND_UNTRUSTED_IMAGE_DECODER=0``. Decoding the *canonical sanitized PNG*
  inside the isolated PaddleOCR child is explicitly allowed and expected —
  PaddleOCR's own pipeline decodes the file it is given, and the child does not
  decode anything itself. What is refused is a second decoder for
  *untrusted* input: this module therefore reads the PNG signature and the
  ``IHDR`` header directly, byte for byte, and never invokes an image decoder on
  either side of the boundary.
- ``CHILD != UNBOUNDED_CONSUMER``. Every decode returns ``None`` — a bounded
  refusal — instead of raising on attacker-shaped or model-shaped input.
- ``OCR != PDF_AUTHORITY``. Nothing here reads, writes, parses or emits a PDF.
  The sanitized PNG is the only artifact that crosses.

Vocabulary
----------
``OcrOutcome`` values are ``completed``, ``rejected``, ``timed_out`` and
``failed``. ``rejected`` means the child ran and the OCR step refused the
image with a bounded reason code; ``failed`` means the boundary could not
produce a trustworthy result at all (child crash, malformed or oversized
report, a child that outlived the kill). A timeout is reported only as
``timed_out`` and is never re-labelled as a failure or a cancellation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import struct
from dataclasses import dataclass
from typing import Any

from padiem_ai_core.image_helpers import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS

__all__ = [
    "CHILD_MODULE_NAME",
    "DETECTOR_MODEL_REVISION",
    "DETECTOR_MODEL_MANIFEST",
    "ENVELOPE_KEYS",
    "MAX_OCR_BOX_COORD_ABS",
    "MAX_OCR_BOX_POINTS",
    "MAX_OCR_BOXES_PER_RESULT",
    "MAX_OCR_CHILD_ENVELOPE_BYTES",
    "MAX_OCR_CHILD_ERROR_BYTES",
    "MAX_OCR_CHILD_OUTPUT_BYTES",
    "MAX_OCR_INPUT_PIXELS",
    "MAX_OCR_MODEL_DIR_CHARS",
    "MAX_OCR_MODEL_READ_CHUNK_BYTES",
    "MAX_OCR_RESULTS",
    "MAX_OCR_RESULT_TEXT_CHARS",
    "MAX_OCR_SCORE",
    "MAX_OCR_TOTAL_TEXT_CHARS",
    "OCR_INPUT_REASON_CODE",
    "OCR_ISOLATION_FAILURE_REASON_CODE",
    "OCR_RESULT_INVALID_REASON_CODE",
    "OCR_RUNTIME_MISSING_REASON_CODE",
    "OCR_TIMEOUT_REASON_CODE",
    "ORIENTATION_STAGES_OFF",
    "PADDLEOCR_RUNTIME_REVISION",
    "PNG_SIGNATURE",
    "PROVENANCE_KEYS",
    "RECOGNIZER_MODEL_REVISION",
    "RECOGNIZER_MODEL_MANIFEST",
    "REPORT_REJECTION_KEYS",
    "REPORT_SUCCESS_KEYS",
    "RESULT_KEYS",
    "CanonicalPngFacts",
    "OcrBox",
    "OcrProvenance",
    "OcrReport",
    "OcrResult",
    "OcrEnvelope",
    "decode_envelope",
    "decode_report",
    "encode_envelope",
    "encode_report",
    "inspect_canonical_png",
    "is_bounded_reason_code",
    "validate_model_manifest",
]

#: The one reviewed child module the parent is allowed to start. The parent
#: never builds a command from caller input, so this constant is the whole
#: executable authority of the adapter.
CHILD_MODULE_NAME = "kagent.image_ocr_child"

#: The reviewed runtime revision this adapter is written against. The child
#: reports what it actually imported; a mismatch is a bounded refusal rather
#: than a silent behaviour change. Compared for **equality**: ``3.7.0`` and
#: ``3.7.0-rc1`` are different runtimes, and a prefix match would accept both.
PADDLEOCR_RUNTIME_REVISION = "3.7.0"

# ---------------------------------------------------------------------------
# Pinned official model manifests
# ---------------------------------------------------------------------------
#
# These are the *only* model revisions this adapter may claim, and they are
# literals rather than directory basenames: provenance must state which reviewed
# artifact set ran, and a basename is caller-controlled, unbounded and can be
# renamed on disk without anything changing underneath it.
#
# The manifest is the full required-exact file set of one official PaddleX
# inference directory. A directory is accepted only when it contains precisely
# these three files, at precisely these byte counts, with precisely these
# SHA-256 digests, and is not a symlink.

#: Streaming chunk for manifest hashing. Bounded so a hostile "model file" is
#: never read whole into memory; 1 MiB keeps a real 88 MB weight file bounded.
MAX_OCR_MODEL_READ_CHUNK_BYTES = 1 << 20

#: The PP-OCRv5_server_det revision this adapter is pinned to.
DETECTOR_MODEL_REVISION = "ca867c897ecbca8873081573a802ad70d499cb94"

#: The korean_PP-OCRv5_mobile_rec revision this adapter is pinned to.
RECOGNIZER_MODEL_REVISION = "c02ecaf1f22bfd1c618cce154fd19185b47e663a"

#: ``(filename, bytes, sha256)`` per required official model file, sorted by
#: filename so a comparison never depends on directory iteration order.
DETECTOR_MODEL_MANIFEST: tuple[tuple[str, int, str], ...] = (
    (
        "inference.json",
        402480,
        "af5876933d8806a1b50d895867e0781e135cd92ff37381992828fc8d1b842d28",
    ),
    (
        "inference.pdiparams",
        87932887,
        "183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d",
    ),
    (
        "inference.yml",
        903,
        "28fb721efc3634fc8aa677e474b9602cb815a91cf569ef357a7a553d7b3ce685",
    ),
)

RECOGNIZER_MODEL_MANIFEST: tuple[tuple[str, int, str], ...] = (
    (
        "inference.json",
        217724,
        "562404e3c590c50c93778d5f0a94df21b47b5ab8f3ea6d47c7f8a7930c3bc844",
    ),
    (
        "inference.pdiparams",
        13342671,
        "cac3e5f12cf04aaa77f6a5bc704e4e736ef2908476551891d84b41b4e9090462",
    ),
    (
        "inference.yml",
        96039,
        "f757fa1c40e99edcf27e9cce879b93eb2a51fa46f5ef39095689b8c37dd75998",
    ),
)


#: Document-orientation, unwarping and textline-orientation stages are all
#: disabled. The Core transform already applied EXIF orientation and produced a
#: single upright frame, so a second geometric model inside the child would be
#: both redundant work and a second, unreviewed geometry authority.
ORIENTATION_STAGES_OFF: frozenset[str] = frozenset(
    {
        "use_doc_orientation_classify",
        "use_doc_unwarping",
        "use_textline_orientation",
    }
)

# ---------------------------------------------------------------------------
# Bounded reason vocabulary
# ---------------------------------------------------------------------------

#: Hard timeout. Reported only for a child that had to be terminated.
OCR_TIMEOUT_REASON_CODE = "image_ocr_timeout"

#: The boundary itself could not produce a trustworthy result.
OCR_ISOLATION_FAILURE_REASON_CODE = "image_ocr_isolated_failure"

#: The caller handed the boundary input outside the existing Core byte bound.
#: Defence in depth: the #2824 gate and the Core transform normally refuse this
#: first, so reaching this code means a bound was bypassed or has drifted.
OCR_INPUT_REASON_CODE = "image_ocr_input_rejected"

#: The reviewed runtime or a local model directory is not available. A separate
#: code keeps "not provisioned" distinguishable from "ran and failed".
OCR_RUNTIME_MISSING_REASON_CODE = "image_ocr_runtime_missing"

#: The child ran and its OCR projection was not a bounded, defensible result.
OCR_RESULT_INVALID_REASON_CODE = "image_ocr_result_invalid"

#: A reason code is a bounded enumeration, never free text. This is the
#: structural guard that keeps a payload, a host path, an exception message or a
#: traceback out of any public note: none of them can match this grammar.
_BOUNDED_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def is_bounded_reason_code(value: Any) -> bool:
    """Whether ``value`` is a bounded reason identifier and not free text."""

    return isinstance(value, str) and _BOUNDED_REASON_RE.fullmatch(value) is not None


# ---------------------------------------------------------------------------
# Ceilings
# ---------------------------------------------------------------------------

#: Largest accepted OCR result count. A page of dense text is tens of lines;
#: anything past this is a model or decoder failure, not a page.
MAX_OCR_RESULTS = 256

#: Largest accepted recognized text for one result. One text line, not a
#: paragraph and certainly not a whole document smuggled into one box.
MAX_OCR_RESULT_TEXT_CHARS = 4_000

#: Largest accepted recognized text across every result of one image. Aligned
#: with the existing Core document character bound, so OCR text can never
#: exceed what a Core document parse would have accepted for the same content.
MAX_OCR_TOTAL_TEXT_CHARS = 40_000

#: Largest accepted score. Scores are unit-interval confidences; a value above
#: 1 is a malformed projection, not a very confident one.
MAX_OCR_SCORE = 1.0

#: Largest accepted box count per result. One detection polygon per recognized
#: line; extra boxes are dropped rather than merged.
MAX_OCR_BOXES_PER_RESULT = 1

#: Largest accepted vertex count for one box. Four points is a quadrilateral,
#: which is what a text detector returns; a longer contour is not a text box.
MAX_OCR_BOX_POINTS = 4

#: Largest accepted absolute box coordinate, in pixels. An OCR input is bounded
#: by :data:`MAX_OCR_INPUT_PIXELS`, so no in-bounds coordinate can exceed the
#: largest possible side; the ceiling only rejects fabricated geometry.
MAX_OCR_BOX_COORD_ABS = 1_000_000

#: Largest accepted ``width * height`` of the sanitized PNG the child is asked
#: to read, re-exported from the existing Core image bound. The Core transform
#: already refuses more; the parent re-checks it as defence in depth, and the
#: box coordinate ceiling is meaningful only relative to this number.
MAX_OCR_INPUT_PIXELS = MAX_IMAGE_PIXELS

#: A model directory path is a bounded token, not free text, and it is validated
#: as an explicit local directory on both sides of the boundary.
MAX_OCR_MODEL_DIR_CHARS = 1_024

#: Parent -> child. The envelope carries the canonical PNG base64-encoded, so
#: the ceiling is the Core image byte bound expanded by the base64 ratio plus a
#: small fixed frame for the two model directory paths and the fixed-size
#: ``format``/``width``/``height``/``sha256`` fact record. That frame is a few
#: hundred bytes of JSON, so the 8 KiB allowance covers it with room to spare
#: and is not a place where a caller can widen the image bound.
MAX_OCR_CHILD_ENVELOPE_BYTES = ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 8_192

#: Child -> parent. The successful payload is bounded text plus bounded boxes
#: plus a small provenance record. JSON escaping can expand a single character
#: to six bytes, so the text part of the ceiling is derived from the character
#: ceiling rather than guessed; the box part is derived from the per-result box
#: bound, since every coordinate can be up to seven characters plus a sign,
#: comma and JSON punctuation.
MAX_OCR_CHILD_OUTPUT_BYTES = (
    (min(MAX_OCR_TOTAL_TEXT_CHARS, MAX_OCR_RESULTS * MAX_OCR_RESULT_TEXT_CHARS) * 6)
    + (
        MAX_OCR_RESULTS
        * (
            (min(MAX_OCR_RESULT_TEXT_CHARS, MAX_OCR_TOTAL_TEXT_CHARS) * 6)
            + (MAX_OCR_BOXES_PER_RESULT * MAX_OCR_BOX_POINTS * 24)
            + 128
        )
    )
    + 8_192
)

#: Child stderr is drained to keep the pipe from filling, and is never surfaced.
MAX_OCR_CHILD_ERROR_BYTES = 8_192

# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------

ENVELOPE_KEYS = frozenset(
    {
        "detector_dir",
        "recognizer_dir",
        "format",
        "width",
        "height",
        "sha256",
        "base64",
    }
)
REPORT_SUCCESS_KEYS = frozenset({"ok", "provenance", "results"})
REPORT_REJECTION_KEYS = frozenset({"ok", "code"})
RESULT_KEYS = frozenset({"text", "score", "boxes"})
PROVENANCE_KEYS = frozenset(
    {
        "runtime",
        "runtime_revision",
        "detector_revision",
        "recognizer_revision",
        "canonical_png_sha256",
        "mode",
    }
)


@dataclass(frozen=True, slots=True)
class OcrEnvelope:
    """One bounded parent -> child OCR request.

    ``payload`` is always the canonical sanitized single-frame PNG from the
    existing Core transform, never the caller's original untrusted bytes. The
    four fact fields are the parent's claims about that payload; the child
    re-derives all of them and refuses the request on any disagreement.
    """

    detector_dir: str
    recognizer_dir: str
    payload: bytes
    format: str
    width: int
    height: int
    sha256: str


@dataclass(frozen=True, slots=True)
class OcrBox:
    """One bounded text box: a convex quadrilateral in image pixel coordinates."""

    points: tuple[tuple[int, int], ...]

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection as plain JSON-ready lists."""

        return {"points": [list(point) for point in self.points]}


@dataclass(frozen=True, slots=True)
class OcrResult:
    """One bounded recognized text line and the boxes it was found in."""

    text: str
    score: float
    boxes: tuple[OcrBox, ...] = ()

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection. No payload bytes and no host paths."""

        return {
            "text": self.text,
            "score": self.score,
            "boxes": [box.safe_dict() for box in self.boxes],
        }


@dataclass(frozen=True, slots=True)
class OcrProvenance:
    """Bounded, path-free record of what actually produced the text.

    The model revisions are the **fixed official constants**, not the model
    directory basenames: the manifest was already checked against the exact
    official digests, so a basename adds nothing and could only ever report what
    the caller happened to name a directory. ``canonical_png_sha256`` is the
    digest of the exact PNG that was decoded, which ties the receipt to one
    specific image without carrying the image or a path.
    """

    runtime: str
    runtime_revision: str
    detector_revision: str
    recognizer_revision: str
    canonical_png_sha256: str
    mode: str

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection. Never contains a model directory path."""

        return {
            "runtime": self.runtime,
            "runtime_revision": self.runtime_revision,
            "detector_revision": self.detector_revision,
            "recognizer_revision": self.recognizer_revision,
            "canonical_png_sha256": self.canonical_png_sha256,
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class OcrReport:
    """One bounded child -> parent OCR report.

    A successful report carries provenance and results and no code; a refusal
    carries a bounded code and neither. The two shapes cannot be mixed, so a
    caller can never read a partial success or an unbounded error string.
    """

    ok: bool
    provenance: OcrProvenance | None = None
    results: tuple[OcrResult, ...] = ()
    code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise ValueError("report ok must be a boolean")
        if self.ok:
            if not isinstance(self.provenance, OcrProvenance) or self.code is not None:
                raise ValueError("a successful report carries provenance only")
            if not isinstance(self.results, tuple):
                raise ValueError("report results must be a tuple")
            _validate_results(self.results)
        else:
            if is_bounded_reason_code(self.code) is False:
                raise ValueError("a refusal report carries a bounded code only")
            if self.provenance is not None or self.results:
                raise ValueError("a refusal report carries no results")

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection. Never contains payload bytes or a path."""

        return {
            "ok": self.ok,
            "provenance": self.provenance.safe_dict() if self.provenance is not None else None,
            "results": [result.safe_dict() for result in self.results],
            "code": self.code,
        }


def _validate_results(results: tuple[OcrResult, ...]) -> None:
    """Enforce the count, text, box and score ceilings on a result sequence."""

    if len(results) > MAX_OCR_RESULTS:
        raise ValueError("result count exceeds the bounded maximum")
    total = 0
    for result in results:
        if not isinstance(result, OcrResult):
            raise ValueError("results must contain OcrResult values")
        if not isinstance(result.text, str) or len(result.text) > MAX_OCR_RESULT_TEXT_CHARS:
            raise ValueError("result text exceeds the bounded maximum")
        total += len(result.text)
        if not isinstance(result.score, (int, float)) or isinstance(result.score, bool):
            raise ValueError("result score must be a number")
        if not math.isfinite(float(result.score)) or not 0.0 <= float(result.score) <= MAX_OCR_SCORE:
            raise ValueError("result score is outside the unit interval")
        if not isinstance(result.boxes, tuple) or len(result.boxes) > MAX_OCR_BOXES_PER_RESULT:
            raise ValueError("result box count exceeds the bounded maximum")
        for box in result.boxes:
            _validate_box(box)
    if total > MAX_OCR_TOTAL_TEXT_CHARS:
        raise ValueError("total text exceeds the bounded maximum")


def _validate_box(box: OcrBox) -> None:
    """Enforce the point-count and coordinate ceilings on one box."""

    if not isinstance(box, OcrBox):
        raise ValueError("boxes must contain OcrBox values")
    if not box.points or len(box.points) > MAX_OCR_BOX_POINTS:
        raise ValueError("box point count is outside the bounded range")
    for point in box.points:
        if not isinstance(point, tuple) or len(point) != 2:
            raise ValueError("a box point must be a coordinate pair")
        for value in point:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("box coordinates must be integers")
            if abs(value) > MAX_OCR_BOX_COORD_ABS:
                raise ValueError("box coordinate exceeds the bounded maximum")


def _validate_model_dir(value: Any) -> bool:
    """Whether ``value`` is a bounded, absolute, explicit local directory path.

    Both sides of the boundary apply this, so a relative path, a traversal
    segment, a URL or a shell-looking token can never become a model source.
    """

    if not isinstance(value, str) or not value or len(value) > MAX_OCR_MODEL_DIR_CHARS:
        return False
    if "\x00" in value or "\n" in value or "\r" in value:
        return False
    # Windows accepts both separators, so both are rejected as traversal.
    normalized = value.replace("\\", "/")
    if not normalized.startswith("/") and not re.match(r"^[A-Za-z]:/", normalized):
        return False
    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return False
    return all(segment not in (".", "..") for segment in segments)


def validate_model_manifest(
    directory: Any, manifest: tuple[tuple[str, int, str], ...]
) -> bool:
    """Whether ``directory`` holds exactly the reviewed official model files.

    Checked on **both** sides of the boundary: the parent before it starts a
    process, and the child before it imports or builds PaddleOCR. A model
    directory is the one thing the child reads from disk, so an unreviewed or
    tampered weight set must not be loadable merely because the parent happened
    to be configured correctly.

    Every refusal here is structural, and the checks are ordered cheapest-first:

    1. the root is a bounded absolute path, an existing directory, and **not a
       symlink** — a link is how a "local" model source quietly becomes
       somewhere else;
    2. the file name set is *exactly* the manifest's, so a missing required
       file and an unrecognised extra file are both refused;
    3. each entry is a regular file and not a symlink;
    4. each file's byte count is exactly the manifest's, checked from the stat
       before a single byte is read; and
    5. each file's SHA-256 equals the manifest's, streamed in bounded chunks.

    Never raises: an unreadable, hostile or absent directory is ``False``.
    """

    if not _validate_model_dir(directory) or not manifest:
        return False
    try:
        if not os.path.isdir(directory) or os.path.islink(directory):
            return False
        required = {name: (size, digest) for name, size, digest in manifest}
        with os.scandir(directory) as entries:
            found: dict[str, os.DirEntry[str]] = {}
            for entry in entries:
                name = entry.name
                if name not in required:
                    # An unrecognised file in a model root is a second,
                    # unreviewed artifact; refuse rather than ignore it.
                    return False
                if name in found:
                    return False
                found[name] = entry
        if set(found) != set(required):
            return False
        for name, entry in found.items():
            expected_size, expected_digest = required[name]
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                return False
            stat_result = entry.stat(follow_symlinks=False)
            if stat_result.st_size != expected_size:
                return False
            if _streaming_sha256(entry.path) != expected_digest:
                return False
    except (OSError, ValueError):
        return False
    return True


def _streaming_sha256(path: str) -> str | None:
    """Bounded streaming SHA-256 of one file, or ``None`` when it cannot be read.

    Streaming rather than :func:`hashlib.file_digest` over a whole read: a
    bounded chunk is what keeps a hostile multi-terabyte "weight file" from
    becoming a memory exhaustion, and the caller has already refused a
    stat size that does not match the manifest.
    """

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            while True:
                chunk = stream.read(MAX_OCR_MODEL_READ_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except (OSError, ValueError):
        return None
    return digest.hexdigest()


#: The 8-byte PNG signature. Read as bytes, never sniffed with a decoder.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: The byte offset of the ``IHDR`` chunk header: 8 signature bytes, then a
#: 4-byte big-endian length that must be 13, then the 4-byte chunk type.
_PNG_IHDR_LENGTH_OFFSET = 8
_PNG_IHDR_LENGTH_BYTES = 4
_PNG_IHDR_TYPE_OFFSET = 12
_PNG_IHDR_TYPE = b"IHDR"
_PNG_IHDR_DIMENSIONS_OFFSET = 16
_PNG_IHDR_MIN_LENGTH = 24


@dataclass(frozen=True, slots=True)
class CanonicalPngFacts:
    """The bounded facts the parent validates on the canonical PNG, in-band.

    The child re-derives all four from the bytes it received and refuses the
    request when any of them disagrees, so these values are a wire contract
    rather than an assertion.
    """

    format: str
    width: int
    height: int
    sha256: str


def inspect_canonical_png(
    payload: Any, *, width: Any, height: Any
) -> CanonicalPngFacts | None:
    """Validate the canonical sanitized PNG structurally, without a decoder.

    ``SECOND_UNTRUSTED_IMAGE_DECODER=0``: nothing here decodes pixels. The
    format is the fixed ``PNG`` literal, the dimensions are read straight out of
    the ``IHDR`` header that the signature makes unambiguous, every PNG chunk is
    bounds- and CRC-checked, at least one ``IDAT`` plus a terminal ``IEND`` are
    required, and the digest is streamed. This is a bounded structural parser,
    not an image decode: it never inflates the compressed stream or allocates a
    pixel buffer.

    Returns ``None`` — a bounded refusal, never an exception — for a wrong
    format, a wrong signature, a malformed/truncated/CRC-invalid chunk sequence,
    a missing ``IDAT`` or ``IEND``, a non-positive or mismatched dimension, an
    over-ceiling byte count or an over-ceiling pixel count.
    """

    if not isinstance(payload, (bytes, bytearray)):
        return None
    for name, value in (("width", width), ("height", height)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
    body = bytes(payload)
    if not body or len(body) > MAX_IMAGE_BYTES:
        return None
    if not body.startswith(PNG_SIGNATURE):
        return None
    if len(body) < _PNG_IHDR_MIN_LENGTH:
        return None
    declared_length = int.from_bytes(
        body[_PNG_IHDR_LENGTH_OFFSET : _PNG_IHDR_LENGTH_OFFSET + _PNG_IHDR_LENGTH_BYTES],
        "big",
    )
    if declared_length != 13:
        return None
    if body[_PNG_IHDR_TYPE_OFFSET : _PNG_IHDR_TYPE_OFFSET + 4] != _PNG_IHDR_TYPE:
        return None
    header_width, header_height = struct.unpack(
        ">II", body[_PNG_IHDR_DIMENSIONS_OFFSET : _PNG_IHDR_DIMENSIONS_OFFSET + 8]
    )
    if header_width <= 0 or header_height <= 0:
        return None
    if header_width != width or header_height != height:
        return None
    if header_width * header_height > MAX_OCR_INPUT_PIXELS:
        return None

    # Walk the bounded chunk sequence without inflating IDAT or decoding pixels.
    # This refuses a forged 24-byte prefix before PaddleOCR can ever see it.
    offset = len(PNG_SIGNATURE)
    first_chunk = True
    seen_idat = False
    while offset < len(body):
        if len(body) - offset < 12:
            return None
        length = int.from_bytes(body[offset : offset + 4], "big")
        chunk_end = offset + 12 + length
        if chunk_end > len(body):
            return None
        chunk_type = body[offset + 4 : offset + 8]
        chunk_data = body[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(body[offset + 8 + length : chunk_end], "big")
        actual_crc = binascii.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            return None
        if first_chunk:
            if chunk_type != _PNG_IHDR_TYPE or length != 13:
                return None
            first_chunk = False
        elif chunk_type == _PNG_IHDR_TYPE:
            return None
        if chunk_type == b"IDAT":
            seen_idat = True
        if chunk_type == b"IEND":
            if length != 0 or not seen_idat or chunk_end != len(body):
                return None
            break
        offset = chunk_end
    else:
        return None

    return CanonicalPngFacts(
        format="PNG",
        width=header_width,
        height=header_height,
        sha256=hashlib.sha256(body).hexdigest(),
    )


def encode_envelope(
    *,
    detector_dir: Any,
    recognizer_dir: Any,
    payload: Any,
    width: Any,
    height: Any,
) -> bytes:
    """Encode one request envelope. Raises on programmer misuse only.

    The envelope carries the canonical PNG's ``format``, ``width``, ``height``
    and ``sha256`` beside the base64 body, so the child can re-derive all four
    from the bytes it received instead of trusting the parent.
    """

    if not _validate_model_dir(detector_dir) or not _validate_model_dir(recognizer_dir):
        raise ValueError("envelope model directories must be absolute local paths")
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError("envelope payload must be bytes")
    body = bytes(payload)
    facts = inspect_canonical_png(body, width=width, height=height)
    if facts is None:
        raise ValueError("envelope payload is not the validated canonical PNG")
    frame = {
        "detector_dir": detector_dir,
        "recognizer_dir": recognizer_dir,
        "format": facts.format,
        "width": facts.width,
        "height": facts.height,
        "sha256": facts.sha256,
        "base64": base64.b64encode(body).decode("ascii"),
    }
    encoded = json.dumps(frame, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_OCR_CHILD_ENVELOPE_BYTES:
        raise ValueError("envelope exceeds the bounded wire ceiling")
    return encoded


def decode_envelope(raw: Any) -> OcrEnvelope | None:
    """Decode and re-validate one request envelope, or ``None`` to refuse.

    This is the child side of ``ORIGINAL_SOURCE_BYTES_TO_OCR_CHILD=0``: the
    structural and hash re-validation happens *here*, on the bytes that actually
    arrived, rather than being assumed from the sender. A wrong format, a wrong
    digest, a width/height that disagrees with the ``IHDR`` header, a non-PNG
    signature, a relative or traversing model directory and malformed base64 all
    return ``None``, so a mismatched or forged fact can never reach a temp file.
    """

    if not isinstance(raw, (bytes, bytearray)):
        return None
    data = bytes(raw)
    if not data or len(data) > MAX_OCR_CHILD_ENVELOPE_BYTES:
        return None
    try:
        frame = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(frame, dict) or set(frame) != ENVELOPE_KEYS:
        return None
    detector_dir = frame["detector_dir"]
    recognizer_dir = frame["recognizer_dir"]
    declared_format = frame["format"]
    declared_width = frame["width"]
    declared_height = frame["height"]
    declared_digest = frame["sha256"]
    encoded = frame["base64"]
    if not isinstance(encoded, str):
        return None
    if declared_format != "PNG":
        return None
    if not isinstance(declared_digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}", declared_digest
    ):
        return None
    if not _validate_model_dir(detector_dir) or not _validate_model_dir(recognizer_dir):
        return None
    if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        return None
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not payload or len(payload) > MAX_IMAGE_BYTES:
        return None
    facts = inspect_canonical_png(payload, width=declared_width, height=declared_height)
    if facts is None or facts.sha256 != declared_digest:
        return None
    return OcrEnvelope(
        detector_dir=detector_dir,
        recognizer_dir=recognizer_dir,
        payload=payload,
        format=facts.format,
        width=facts.width,
        height=facts.height,
        sha256=facts.sha256,
    )


def encode_report(report: OcrReport) -> bytes:
    """Encode one child report. Raises on programmer misuse only."""

    if not isinstance(report, OcrReport):
        raise ValueError("report must be an OcrReport")
    if report.ok:
        frame: dict[str, Any] = {
            "ok": True,
            "provenance": report.provenance.safe_dict()
            if report.provenance is not None
            else None,
            "results": [result.safe_dict() for result in report.results],
        }
    else:
        frame = {"ok": False, "code": report.code}
    return json.dumps(frame, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _decode_provenance(raw: Any) -> OcrProvenance | None:
    """Decode a bounded provenance record, or ``None`` when it is not one.

    Every field is a bounded token. A host path, a traceback or an arbitrary
    runtime string can never survive this check, so provenance cannot become a
    path-leak channel.
    """

    if not isinstance(raw, dict) or set(raw) != PROVENANCE_KEYS:
        return None
    # Read by name, never by sorted position: a positional unpack here would
    # silently transpose the fields the moment the key set is reordered.
    for key in PROVENANCE_KEYS:
        value = raw[key]
        if not isinstance(value, str) or not value or len(value) > 128:
            return None
    if re.fullmatch(r"[0-9a-f]{64}", raw["canonical_png_sha256"]) is None:
        return None
    return OcrProvenance(
        runtime=raw["runtime"],
        runtime_revision=raw["runtime_revision"],
        detector_revision=raw["detector_revision"],
        recognizer_revision=raw["recognizer_revision"],
        canonical_png_sha256=raw["canonical_png_sha256"],
        mode=raw["mode"],
    )


def _decode_result(raw: Any) -> OcrResult | None:
    """Decode one bounded result, or ``None`` when its shape is not defensible."""

    if not isinstance(raw, dict) or set(raw) != RESULT_KEYS:
        return None
    text = raw["text"]
    score = raw["score"]
    boxes_raw = raw["boxes"]
    if not isinstance(text, str) or len(text) > MAX_OCR_RESULT_TEXT_CHARS:
        return None
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if not math.isfinite(float(score)) or not 0.0 <= float(score) <= MAX_OCR_SCORE:
        return None
    if not isinstance(boxes_raw, list) or len(boxes_raw) > MAX_OCR_BOXES_PER_RESULT:
        return None
    boxes: list[OcrBox] = []
    for box_raw in boxes_raw:
        if not isinstance(box_raw, dict) or set(box_raw) != {"points"}:
            return None
        points_raw = box_raw["points"]
        if not isinstance(points_raw, list) or not points_raw or len(points_raw) > MAX_OCR_BOX_POINTS:
            return None
        points: list[tuple[int, int]] = []
        for point_raw in points_raw:
            if not isinstance(point_raw, list) or len(point_raw) != 2:
                return None
            for value in point_raw:
                if isinstance(value, bool) or not isinstance(value, int):
                    return None
                if abs(value) > MAX_OCR_BOX_COORD_ABS:
                    return None
            points.append((point_raw[0], point_raw[1]))
        boxes.append(OcrBox(points=tuple(points)))
    return OcrResult(text=text, score=float(score), boxes=tuple(boxes))


def decode_report(raw: Any) -> OcrReport | None:
    """Decode a child report, or return ``None`` for a bounded refusal.

    A report is trusted only when it is a JSON object with exactly one of the two
    bounded shapes, a bounded provenance record and result items that each stay
    inside every count, text, box and coordinate ceiling. Anything else — a
    traceback string, a partial write, an extra key, a numpy scalar smuggled
    through as a non-JSON type, oversized text — is refused here so it can never
    be projected as an OCR outcome.
    """

    if not isinstance(raw, (bytes, bytearray)):
        return None
    data = bytes(raw)
    if not data or len(data) > MAX_OCR_CHILD_OUTPUT_BYTES:
        return None
    try:
        frame = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(frame, dict) or not isinstance(frame.get("ok"), bool):
        return None
    if frame["ok"] is False:
        if set(frame) != REPORT_REJECTION_KEYS or not is_bounded_reason_code(frame["code"]):
            return None
        return OcrReport(ok=False, code=frame["code"])

    if set(frame) != REPORT_SUCCESS_KEYS:
        return None
    provenance = _decode_provenance(frame["provenance"])
    if provenance is None:
        return None
    results_raw = frame["results"]
    if not isinstance(results_raw, list) or len(results_raw) > MAX_OCR_RESULTS:
        return None
    results: list[OcrResult] = []
    total = 0
    for item in results_raw:
        result = _decode_result(item)
        if result is None:
            return None
        total += len(result.text)
        if total > MAX_OCR_TOTAL_TEXT_CHARS:
            return None
        results.append(result)
    return OcrReport(ok=True, provenance=provenance, results=tuple(results))
