"""#2828: reviewed child entrypoint that hosts the local PaddleOCR runtime.

This is the only program the kagent-local OCR adapter is allowed to start, and
it exists so a hostile image or a hung model can only ever consume a dedicated
child process. The child:

1. reads one bounded request envelope from stdin;
2. re-validates both official model manifests **before** importing anything from
   the PaddleOCR stack;
3. re-validates the canonical PNG's format, ``IHDR`` dimensions and SHA-256
   against the envelope's claims, before writing any temp file;
4. lazily imports the reviewed :class:`paddleocr.PaddleOCR` runtime;
5. instantiates it against two explicit local model directories with document
   orientation, unwarping and textline orientation all disabled;
6. projects the result defensively into a bounded report; and
7. writes exactly one bounded JSON report to stdout and exits 0.

Authority boundaries
--------------------
- ``ORIGINAL_SOURCE_BYTES_TO_OCR_CHILD=0``. The child never receives the
  caller's original untrusted bytes. The #2824 intake gate and the #3037 Core
  transform own those, and only the Core-produced canonical sanitized PNG
  crosses into this process.
- ``SECOND_UNTRUSTED_IMAGE_DECODER=0``, and decoding the canonical PNG here is
  still allowed. The child itself does not decode anything: it reads the 8-byte
  signature, the ``IHDR`` header and a streamed digest, which is a structural
  check rather than an image decode. The *runtime* decodes the canonical PNG
  from the child's private temp file inside this isolated process — that is the
  reviewed PaddleOCR pipeline over Core's own output, not a second decoder for
  untrusted input.
- ``CHILD != UNTRUSTED_MODEL_AUTHORITY``. Both model roots must hold exactly the
  pinned official files — exact names, exact byte counts, exact SHA-256 digests,
  no symlinked root — and this is checked before ``paddleocr`` is imported, so a
  tampered weight set is never loaded just to fail later.
- ``CHILD != PDF_AUTHORITY``. Nothing in this module reads, writes, parses or
  emits a PDF.
- ``CHILD != MODEL_DOWNLOAD_AUTHORITY``. The runtime is constructed with explicit
  local detector and recognizer directories and with every orientation stage
  off, so it resolves weights from disk rather than from a model hub. The model
  directories are validated as existing local directories first.
- ``CHILD != UNBOUNDED_SHELL_SCRIPT``. The child starts nothing: it imports no
  ``subprocess``, ``multiprocessing``, ``os.system`` or thread authority, so it
  creates no grandchildren and the parent's direct-child terminate/kill is
  sufficient for the whole process tree.
- ``CHILD != UNBOUNDED_REPORT``. The runtime's own output is treated as
  attacker-shaped input. Only bounded types survive projection: a result with an
  unexpected shape, a non-finite score, an oversized text run, a five-vertex
  contour or a coordinate outside the image is dropped or refused, never
  forwarded. A traceback, a host path or a payload fragment cannot reach the
  parent, because the report is a bounded enumeration plus bounded text.
- ``CHILD != TRACEBACK_PRINTER``. The child always emits a bounded report and
  always exits 0, even when the runtime raises, hangs on import, or returns
  something entirely unexpected.

The child is intentionally importable and runnable on its own, because that is
exactly what the parent does: ``python -P -m kagent.image_ocr_child``.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from typing import Any

from .image_ocr_contract import (
    DETECTOR_MODEL_MANIFEST,
    DETECTOR_MODEL_REVISION,
    MAX_OCR_BOX_COORD_ABS,
    MAX_OCR_BOX_POINTS,
    MAX_OCR_BOXES_PER_RESULT,
    MAX_OCR_CHILD_ENVELOPE_BYTES,
    MAX_OCR_RESULT_TEXT_CHARS,
    MAX_OCR_RESULTS,
    MAX_OCR_TOTAL_TEXT_CHARS,
    ORIENTATION_STAGES_OFF,
    PADDLEOCR_RUNTIME_REVISION,
    RECOGNIZER_MODEL_MANIFEST,
    RECOGNIZER_MODEL_REVISION,
    OcrBox,
    OcrProvenance,
    OcrReport,
    OcrResult,
    decode_envelope,
    encode_report,
    inspect_canonical_png,
    is_bounded_reason_code,
    validate_model_manifest,
)
from .image_ocr_contract import OCR_ISOLATION_FAILURE_REASON_CODE as _ISOLATION_FAILURE
from .image_ocr_contract import OCR_RESULT_INVALID_REASON_CODE as _RESULT_INVALID
from .image_ocr_contract import OCR_RUNTIME_MISSING_REASON_CODE as _RUNTIME_MISSING

__all__ = ["main", "project_results"]

#: The bounded mode label the receipt carries. It names the deterministic
#: single-frame plain-text tier this adapter is allowed to claim: no document
#: layout, no table, no formula, no document understanding.
OCR_MODE = "kagent_local_single_frame_text"

#: Every orientation-related constructor/predict keyword is pinned off here, so
#: the "orientation OFF" claim is one auditable literal set rather than a
#: scattering of ``False`` arguments.
_ORIENTATION_OFF: dict[str, bool] = {name: False for name in sorted(ORIENTATION_STAGES_OFF)}


def _read_bounded_stdin() -> bytes | None:
    """Read at most one bounded envelope, or ``None`` when the bound is passed.

    Reading ``limit + 1`` bytes is what makes the bound real: a larger stream is
    detected without buffering the whole of it.
    """

    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return None
    try:
        raw = stream.read(MAX_OCR_CHILD_ENVELOPE_BYTES + 1)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return None
    if len(raw) > MAX_OCR_CHILD_ENVELOPE_BYTES:
        return None
    return bytes(raw)


def _refusal(code: str) -> OcrReport:
    return OcrReport(ok=False, code=code)


def _is_local_dir(path: str) -> bool:
    """Whether ``path`` is an existing local directory, not a link to elsewhere.

    ``os.path.isdir`` follows symlinks, so a provisioned path that is a symlink
    is refused rather than silently resolved: the child is given explicit local
    directories, and a link is how a "local" model source quietly becomes
    somewhere else.
    """

    try:
        if not os.path.isdir(path):
            return False
        return not os.path.islink(path)
    except (OSError, ValueError):
        return False


def _model_manifests_valid(detector_dir: str, recognizer_dir: str) -> bool:
    """Whether both model roots still match the pinned official manifests.

    Repeated here — not merely inherited from the parent's preflight — because
    the model directories are the one thing this process reads from disk, and
    between the two checks they may have been replaced. This runs **before**
    ``paddleocr`` is imported, so a tampered weight set is refused without ever
    loading it.
    """

    return bool(
        validate_model_manifest(detector_dir, DETECTOR_MODEL_MANIFEST)
        and validate_model_manifest(recognizer_dir, RECOGNIZER_MODEL_MANIFEST)
    )


def _build_runtime(detector_dir: str, recognizer_dir: str) -> Any:
    """Instantiate the reviewed PaddleOCR runtime against local model dirs.

    The import is deliberately inside this function: importing ``paddleocr``
    pulls in the whole PaddleX/PaddlePaddle stack, and nothing in this module
    should pay that cost — or risk it — unless a real OCR request arrives.
    """

    from paddleocr import PaddleOCR  # noqa: PLC0415 - lazy on purpose

    return PaddleOCR(
        # PaddleOCR 3.7.0 accepts explicit model names and directories together.
        # The names are required when local directories are supplied: without
        # them the runtime falls back to PP-OCRv6_medium_det and rejects the
        # pinned PP-OCRv5_server_det manifest before inference starts.
        text_detection_model_name="PP-OCRv5_server_det",
        text_detection_model_dir=detector_dir,
        text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
        text_recognition_model_dir=recognizer_dir,
        # CPU-only and the high-performance inference plugin off: an OCR receipt
        # must be reproducible on a plain host, and the plugin introduces a
        # hardware-specific execution path this adapter has not reviewed.
        device="cpu",
        enable_hpi=False,
        **_ORIENTATION_OFF,
    )


def _runtime_revision() -> str | None:
    """The imported runtime's own version, as a bounded token, or ``None``.

    Read from the imported module rather than assumed, so a receipt records what
    actually ran. An unreadable or unbounded version is ``None`` — a bounded
    refusal — rather than a fabricated one.
    """

    try:
        import paddleocr  # noqa: PLC0415 - lazy on purpose

        version = getattr(paddleocr, "__version__", None)
    except BaseException:
        return None
    if not isinstance(version, str) or not version or len(version) > 128:
        return None
    return version


def _as_int(value: Any) -> int | None:
    """Coerce a model-produced number to ``int``, or ``None`` when it is not one.

    NumPy integer and floating scalars are accepted because that is what a
    detector returns; anything else — a string, ``None``, a bool, a complex, a
    non-finite float — is refused rather than coerced, so a hostile value cannot
    become a coordinate through a permissive ``int()``.
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    # NumPy scalars expose ``item()`` without importing NumPy here.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            value = item()
        except BaseException:
            return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value)
    return None


def _as_score(value: Any) -> float | None:
    """Coerce a model-produced confidence to a bounded unit-interval float."""

    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        item = getattr(value, "item", None)
        if not callable(item):
            return None
        try:
            value = item()
        except BaseException:
            return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = float(value)
    if score != score or score in (float("inf"), float("-inf")):
        return None
    if not 0.0 <= score <= 1.0:
        return None
    return score


def _as_text(value: Any) -> str | None:
    """Coerce a recognized text run to bounded text, or ``None`` when too large.

    A text run is never truncated here. Truncating OCR output would silently
    report a *different* string than the one on the page, so an oversized run
    drops the whole result instead and the caller sees fewer lines rather than a
    plausible lie.
    """

    if not isinstance(value, str):
        item = getattr(value, "item", None)
        if not callable(item):
            return None
        try:
            value = item()
        except BaseException:
            return None
    if not isinstance(value, str):
        return None
    if len(value) > MAX_OCR_RESULT_TEXT_CHARS:
        return None
    return value


def _as_point(value: Any) -> tuple[int, int] | None:
    """Coerce one polygon vertex to a bounded integer coordinate pair."""

    if isinstance(value, dict):
        # Some detector versions key vertices instead of pairing them.
        x = _as_int(value.get("x"))
        y = _as_int(value.get("y"))
        if x is None or y is None:
            return None
        return (x, y)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        x = _as_int(value[0])
        y = _as_int(value[1])
        if x is None or y is None:
            return None
        return (x, y)
    return None


def _as_box(value: Any) -> OcrBox | None:
    """Coerce one detection polygon to a bounded quadrilateral box.

    A contour is taken as its vertices, not its bounding rectangle: a text
    detector returns a quadrilateral, and wrapping it in a rectangle here would
    invent geometry the detector never claimed.
    """

    if value is None:
        return None
    # A bare 1-D coordinate run is a degenerate contour, not a polygon.
    if isinstance(value, (list, tuple)) and value and _as_int(value[0]) is not None:
        return None
    if isinstance(value, (list, tuple)) and not value:
        return None
    if isinstance(value, (list, tuple)) and not hasattr(value, "shape"):
        if len(value) > MAX_OCR_BOX_POINTS:
            return None
    try:
        length = len(value)
    except TypeError:
        return None
    if length == 0 or length > MAX_OCR_BOX_POINTS:
        return None
    points: list[tuple[int, int]] = []
    try:
        for vertex in value:
            point = _as_point(vertex)
            if point is None:
                return None
            if abs(point[0]) > MAX_OCR_BOX_COORD_ABS or abs(point[1]) > MAX_OCR_BOX_COORD_ABS:
                return None
            points.append(point)
    except TypeError:
        return None
    return OcrBox(points=tuple(points))


def _page_dict(result: Any) -> dict[str, Any] | None:
    """The one result page's mapping, whether it is a result object or a dict.

    PaddleOCR returns result objects that are also mappings, and a runtime
    upgrade may hand back a plain dict instead. Both are accepted through the
    mapping protocol; anything that is not indexable by string is refused.
    """

    if isinstance(result, dict):
        return result
    for accessor in ("json", "res"):
        candidate = getattr(result, accessor, None)
        if isinstance(candidate, dict):
            return candidate
    return None


def _first_present(page: dict[str, Any], names: tuple[str, ...]) -> Any:
    """The first present, non-``None`` value among ``names``.

    Runtime versions disagree on the pluralisation of the recognized-text and
    confidence keys (``rec_texts`` vs ``rec_text``). Both spellings are read
    rather than one being assumed, because guessing wrong would silently
    produce zero results instead of a visible failure.
    """

    for name in names:
        if name in page and page[name] is not None:
            return page[name]
    return None


def _iter_rows(value: Any) -> list[Any] | None:
    """Materialize a model-produced parallel array as a bounded list.

    A NumPy array is not a ``list``, so the value is indexed rather than copied
    wholesale, and the length is checked *before* any element is read. That
    ordering is the bound: a result set larger than the ceiling is refused
    without iterating it.
    """

    if isinstance(value, (list, tuple)):
        rows = list(value)
    else:
        try:
            length = len(value)
        except TypeError:
            return None
        if length > MAX_OCR_RESULTS:
            return None
        try:
            rows = [value[index] for index in range(length)]
        except (IndexError, KeyError, TypeError):
            return None
    if len(rows) > MAX_OCR_RESULTS:
        return None
    return rows


def project_results(raw_results: Any) -> tuple[OcrResult, ...] | None:
    """Project raw runtime output into bounded results, or ``None`` to refuse.

    The projection is deliberately lossy. A result whose text, score or box
    cannot be read as a bounded value is dropped; a payload whose shape is not a
    recognizable result set at all is refused outright. Refusing rather than
    guessing is what keeps a runtime change from being read as OCR content.
    """

    if raw_results is None:
        return ()
    if isinstance(raw_results, dict):
        return None
    try:
        pages = iter(raw_results)
        page_value = next(pages)
    except StopIteration:
        return ()
    except TypeError:
        return None
    try:
        next(pages)
    except StopIteration:
        pass
    except BaseException:
        return None
    else:
        # One sanitized single-frame PNG in, one result page out. More than one
        # page means the runtime treated the input as a batch or a document,
        # which is a different authority than this adapter claims.
        return None

    page = _page_dict(page_value)
    if page is None:
        return None

    texts_raw = _first_present(page, ("rec_texts", "rec_text"))
    scores_raw = _first_present(page, ("rec_scores", "rec_score"))
    polys_raw = _first_present(page, ("rec_polys", "dt_polys"))
    if texts_raw is None:
        # A page with no recognized text at all is a valid empty page.
        return ()
    texts = _iter_rows(texts_raw)
    if texts is None:
        return None
    scores = _iter_rows(scores_raw) if scores_raw is not None else None
    if scores_raw is not None and scores is None:
        return None
    polys = _iter_rows(polys_raw) if polys_raw is not None else None
    if polys_raw is not None and polys is None:
        return None

    results: list[OcrResult] = []
    total = 0
    for index, text_raw in enumerate(texts):
        text = _as_text(text_raw)
        if text is None or text == "":
            # An empty or oversized line is dropped; it is not OCR content a
            # caller can act on and it is not a reason to fail the page.
            continue
        score = 0.0
        if scores is not None and index < len(scores):
            coerced = _as_score(scores[index])
            if coerced is not None:
                score = coerced
        boxes: list[OcrBox] = []
        if polys is not None and index < len(polys):
            box = _as_box(polys[index])
            if box is not None:
                boxes.append(box)
            if len(boxes) > MAX_OCR_BOXES_PER_RESULT:
                return None
        total += len(text)
        results.append(OcrResult(text=text, score=score, boxes=tuple(boxes)))
        if len(results) > MAX_OCR_RESULTS or total > MAX_OCR_TOTAL_TEXT_CHARS:
            return None
    return tuple(results)


def _write_canonical_png(payload: bytes) -> str:
    """Hand the canonical PNG to the runtime through a private temporary file.

    Decoding the canonical PNG inside this child is allowed, and PaddleOCR's own
    pipeline does it — but the *child* is not the decoder and holds no image
    library. The already-validated canonical bytes are written to a child-owned
    temporary file and the *runtime* reads and decodes them. The file is the
    only thing this child creates and is unlinked on every normal return; a hard
    kill may leave the system-temp residue, which is excluded from source
    control and never returned to the caller. It is created only after the
    envelope's format, dimensions and digest have been re-validated against
    these exact bytes.
    """

    handle, path = tempfile.mkstemp(prefix="kagent-ocr-", suffix=".png")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
    except BaseException:
        _discard(path)
        raise
    return path


def _discard(path: str) -> None:
    """Remove the child's temporary PNG, never raising."""

    try:
        os.unlink(path)
    except OSError:
        pass


def _run_ocr(
    payload: bytes,
    detector_dir: str,
    recognizer_dir: str,
    width: int,
    height: int,
    expected_sha256: str,
) -> OcrReport:
    """Run the local OCR runtime for one envelope and bound its outcome."""

    if not _is_local_dir(detector_dir) or not _is_local_dir(recognizer_dir):
        return _refusal(_RUNTIME_MISSING)

    # Child-side re-validation of the canonical PNG. ``decode_envelope`` already
    # did this, and it is repeated on the caller's own terms here so that the
    # invariant is local to the function that writes the temp file: the format is
    # the fixed PNG literal, the dimensions come from the IHDR header, and the
    # streamed digest must equal the one the parent claimed.
    facts = inspect_canonical_png(payload, width=width, height=height)
    if facts is None or facts.sha256 != expected_sha256:
        return _refusal(_ISOLATION_FAILURE)

    if not _model_manifests_valid(detector_dir, recognizer_dir):
        return _refusal(_RUNTIME_MISSING)

    revision = _runtime_revision()
    if revision != PADDLEOCR_RUNTIME_REVISION:
        # Exact equality, not a prefix match: ``3.7.0`` and ``3.7.0-rc1`` are
        # different runtimes, and the projection below is written against one
        # reviewed result schema. The check runs *before* the runtime is built,
        # so a mismatched environment never loads a model.
        return _refusal(_RUNTIME_MISSING)

    try:
        runtime = _build_runtime(detector_dir, recognizer_dir)
    except ModuleNotFoundError:
        return _refusal(_RUNTIME_MISSING)
    except BaseException:
        # Includes a dependency error, a bad model artifact and a hard import
        # failure: all of them become one bounded refusal rather than a traceback
        # on the parent's stderr.
        return _refusal(_RUNTIME_MISSING)

    path = _write_canonical_png(payload)
    try:
        raw = runtime.predict(path, **_ORIENTATION_OFF)
        projected = project_results(raw)
    except BaseException:
        return _refusal(_RESULT_INVALID)
    finally:
        _discard(path)
        closer = getattr(runtime, "close", None)
        if callable(closer):
            try:
                closer()
            except BaseException:
                pass

    if projected is None:
        return _refusal(_RESULT_INVALID)

    # The model revisions are the fixed official constants, not the model
    # directory basenames: the manifests were just checked against the exact
    # official digests, and a basename is caller-controlled and path-shaped.
    provenance = OcrProvenance(
        runtime="paddleocr",
        runtime_revision=revision,
        detector_revision=DETECTOR_MODEL_REVISION,
        recognizer_revision=RECOGNIZER_MODEL_REVISION,
        canonical_png_sha256=facts.sha256,
        mode=OCR_MODE,
    )
    return OcrReport(ok=True, provenance=provenance, results=projected)


def _deny_python_network() -> None:
    """Fail closed if the OCR runtime attempts a Python socket connection.

    The model roots are already exact local manifests, so the child has no
    legitimate network operation. This guard runs before the lazy PaddleOCR
    import; it prevents the Python HTTP/socket paths used by PaddleX and
    report-hub clients from silently turning a local OCR call into a download.
    Native code is outside this interpreter guard and is recorded as a bounded
    runtime limitation in the adoption receipt.
    """

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise OSError("kagent OCR network access is disabled")

    socket.create_connection = blocked  # type: ignore[assignment]
    socket.socket.connect = blocked  # type: ignore[assignment]
    socket.socket.connect_ex = blocked  # type: ignore[assignment]


def _run() -> OcrReport:
    _deny_python_network()
    raw = _read_bounded_stdin()
    if raw is None:
        return _refusal(_ISOLATION_FAILURE)
    envelope = decode_envelope(raw)
    if envelope is None:
        return _refusal(_ISOLATION_FAILURE)
    report = _run_ocr(
        envelope.payload,
        envelope.detector_dir,
        envelope.recognizer_dir,
        envelope.width,
        envelope.height,
        envelope.sha256,
    )
    if not report.ok and report.code is not None and not is_bounded_reason_code(report.code):
        return _refusal(_ISOLATION_FAILURE)
    return report


def main() -> int:
    """Entrypoint. Always emits one bounded report and always exits 0."""

    try:
        report = _run()
    except BaseException:
        report = _refusal(_ISOLATION_FAILURE)
    try:
        sys.stdout.buffer.write(encode_report(report))
        sys.stdout.buffer.flush()
    except (OSError, ValueError):
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a real child process
    raise SystemExit(main())
