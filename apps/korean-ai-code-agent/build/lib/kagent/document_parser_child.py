"""#2824-S3A: reviewed child entrypoint that hosts the Core document parser.

This is the only program the isolated parser boundary is allowed to start, and
it exists so a corrupt or adversarial document can only ever consume a
dedicated child process. The child:

1. reads one bounded request envelope from stdin;
2. calls ``padiem_ai_core.document_normalization.extract_binary_document``;
3. writes exactly one bounded JSON report to stdout and exits 0.

Authority boundaries
--------------------
- ``CHILD != UNBOUNDED_SHELL_SCRIPT``. The child starts nothing: it imports no
  ``subprocess``, ``multiprocessing``, ``os.system`` or thread authority, so it
  creates no grandchildren and the parent's direct-child terminate/kill
  semantics are sufficient for the whole process tree.
- ``CHILD != NETWORK_CLIENT``. No provider, no network, no credential and no
  URL handling; a document parse is a pure function of the envelope bytes.
- ``CHILD != FILESYSTEM_AUTHORITY``. The payload arrives on stdin as bytes. The
  child neither reads nor writes a host path, and it is never given one.
- ``CHILD != TRACEBACK_PRINTER``. The report is a bounded enumeration, so no
  payload, host path, secret or exception text can reach the parent even when
  the parser itself raises. The child always exits 0 with a bounded report
  rather than letting the interpreter print an unbounded diagnostic.
- ``CORE != DUPLICATED``. The child adds no parsing, no bounds and no document
  semantics of its own; it delegates to Core and reports Core's bounded code.

The child is intentionally importable and runnable on its own, because that is
exactly what the parent does:
``python -P -m kagent.document_parser_child``.
"""

from __future__ import annotations

import sys

from padiem_ai_core.document_normalization import (
    DocumentNormalizationError,
    extract_binary_document,
)

from .document_parser_contract import (
    MAX_CHILD_ENVELOPE_BYTES,
    PARSER_ISOLATION_FAILURE_REASON_CODE,
    ParserReport,
    decode_envelope,
    encode_report,
    is_bounded_reason_code,
)

__all__ = ["main"]


def _read_bounded_stdin() -> bytes | None:
    """Read at most one bounded envelope, or ``None`` when the bound is passed.

    Reading ``limit + 1`` bytes is what makes the bound real: a larger stream is
    detected without buffering the whole of it.
    """

    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return None
    try:
        raw = stream.read(MAX_CHILD_ENVELOPE_BYTES + 1)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return None
    if len(raw) > MAX_CHILD_ENVELOPE_BYTES:
        return None
    return bytes(raw)


def _refusal(code: str) -> ParserReport:
    return ParserReport(ok=False, code=code)


def _parse(envelope) -> ParserReport:
    """Run the Core parser for one decoded envelope and bound its outcome."""

    try:
        document = extract_binary_document(
            name=envelope.name,
            media_type=envelope.media_type,
            payload=envelope.payload,
        )
    except DocumentNormalizationError as exc:
        # Core already owns a bounded reason vocabulary; re-bounding it here
        # means an unexpected code can never be projected as free text.
        code = exc.code if is_bounded_reason_code(exc.code) else PARSER_ISOLATION_FAILURE_REASON_CODE
        return _refusal(code)
    except BaseException:
        # Includes a parser crash, a MemoryError and a hostile exit: all of
        # them become one bounded refusal instead of an unbounded diagnostic.
        return _refusal(PARSER_ISOLATION_FAILURE_REASON_CODE)
    return ParserReport(ok=True, text=document.text)


def _run() -> ParserReport:
    raw = _read_bounded_stdin()
    if raw is None:
        return _refusal(PARSER_ISOLATION_FAILURE_REASON_CODE)
    envelope = decode_envelope(raw)
    if envelope is None:
        return _refusal(PARSER_ISOLATION_FAILURE_REASON_CODE)
    return _parse(envelope)


def main() -> int:
    """Entrypoint. Always emits one bounded report and always exits 0."""

    try:
        report = _run()
    except BaseException:
        report = _refusal(PARSER_ISOLATION_FAILURE_REASON_CODE)
    try:
        sys.stdout.buffer.write(encode_report(report))
        sys.stdout.buffer.flush()
    except (OSError, ValueError):
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a real child process
    raise SystemExit(main())
