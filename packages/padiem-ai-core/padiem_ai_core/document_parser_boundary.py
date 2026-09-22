"""One reviewed parser-authority boundary for binary document parsing (#2824 S3-B).

Why this module exists
----------------------
The Core binary parser (``pypdf``/``openpyxl``-backed extraction inside
``padiem_ai_core.document_normalization.extract_binary_document``) is
synchronous CPU work. A Cloudflare Python Worker (Pyodide) has no
``subprocess`` and no ``multiprocessing``, so that work cannot be bounded or
killed from inside the Worker. This slice therefore does not pretend to
isolate it: when the runtime cannot offer a reviewed isolated parser
authority, binary document parsing fails **closed before** the Core parser is
invoked.

This module is the single authority decision shared by every Worker-side
binary document path (Chat attachments, Chat project files, Engine trusted
document resolution). Callers never choose a parser implementation.

What this module deliberately does NOT do
-----------------------------------------
* No provider, service, service binding, sandbox, Durable Object, container
  runtime or new runtime dependency is introduced, and nothing is spawned.
* ``asyncio.wait_for``, thread timeouts, future timeouts, soft/cooperative
  cancellation and fake subprocess abstractions cannot stop synchronous CPU
  work, so none of them is accepted here as isolation authority.
* Runtime classification is server-derived from ``sys.platform``. No request
  body, header, query string, file name, media type or attachment metadata
  selects the parser implementation or the runtime mode, and the production
  Worker never falls back to the in-process parser.

#1405 remains the separate gate for any real sandbox/provider authority.
"""

from __future__ import annotations

import sys
from typing import Any, Protocol, runtime_checkable

from .document_normalization import NormalizedDocument, extract_binary_document
from .document_semantics import DocumentNormalizationError

#: ``sys.platform`` value reported by the Pyodide / Cloudflare Workers runtime.
#: The Engine already keys Workerd-only behaviour off this exact value
#: (see ``apps/padiem-ai-engine/app/cloudflare_external_transport.py``).
PRODUCTION_WORKER_PLATFORM = "emscripten"

#: Bounded, deterministic failure code for "no isolated parser authority here".
DOCUMENT_PARSER_ISOLATION_UNAVAILABLE = "document_parser_isolation_unavailable"

_DOCUMENT_PARSER_ISOLATION_UNAVAILABLE_MESSAGE = (
    "Binary document parsing requires a reviewed isolated parser authority "
    "that this runtime does not provide."
)


class DocumentParserAuthorityUnavailable(DocumentNormalizationError):
    """Fail-closed boundary error: this runtime has no isolated parser authority.

    Carries only the bounded code and a static safe message. It never embeds a
    traceback, host path, raw exception text, payload bytes or document body.
    """

    def __init__(self) -> None:
        super().__init__(
            DOCUMENT_PARSER_ISOLATION_UNAVAILABLE,
            _DOCUMENT_PARSER_ISOLATION_UNAVAILABLE_MESSAGE,
        )


@runtime_checkable
class BinaryDocumentParserPort(Protocol):
    """A reviewed binary document parser authority.

    Parameter-only surface: the port takes the document identity and payload
    and returns the canonical Core document. It accepts no launcher hook, no
    timeout policy and no caller-supplied parser selection.
    """

    def parse_binary_document(
        self,
        *,
        name: Any,
        media_type: Any,
        payload: Any,
    ) -> NormalizedDocument: ...


class _LocalReviewedBinaryDocumentParser:
    """Trusted local/test authority: the reviewed Core parser, in-process.

    Only reachable outside the production Worker runtime. This is the local
    KAgent/CPython path, where the reviewed Core parser is the authority and
    KAgent additionally runs its own killable child-process isolation.
    """

    __slots__ = ()

    def parse_binary_document(
        self,
        *,
        name: Any,
        media_type: Any,
        payload: Any,
    ) -> NormalizedDocument:
        return extract_binary_document(name=name, media_type=media_type, payload=payload)


_LOCAL_REVIEWED_PARSER: BinaryDocumentParserPort = _LocalReviewedBinaryDocumentParser()


def production_worker_runtime() -> bool:
    """Server-derived runtime classification for the production Worker.

    Read from the interpreter, never from request input, so no client can
    influence which authority is used or whether the fail-closed gate applies.
    """

    return sys.platform == PRODUCTION_WORKER_PLATFORM


def resolve_binary_document_parser_authority() -> BinaryDocumentParserPort:
    """Return the parser authority for this runtime, or fail closed.

    Production Worker -> no reviewed isolated parser authority exists, so this
    raises ``DocumentParserAuthorityUnavailable`` *before* the Core parser can
    run. CPython local/test -> the trusted local reviewed parser authority.
    There is deliberately no production-Worker fallback to the in-process
    parser.
    """

    if production_worker_runtime():
        raise DocumentParserAuthorityUnavailable()
    return _LOCAL_REVIEWED_PARSER


def parse_binary_document_via_authority(
    *,
    name: Any,
    media_type: Any,
    payload: Any,
) -> NormalizedDocument:
    """Parse one binary document through the shared authority decision.

    The only binary document parse entry point for Worker-side callers. The
    authority is resolved first, so an unavailable authority fails closed
    before ``extract_binary_document`` is reached.
    """

    authority = resolve_binary_document_parser_authority()
    return authority.parse_binary_document(name=name, media_type=media_type, payload=payload)


__all__ = [
    "DOCUMENT_PARSER_ISOLATION_UNAVAILABLE",
    "PRODUCTION_WORKER_PLATFORM",
    "BinaryDocumentParserPort",
    "DocumentParserAuthorityUnavailable",
    "parse_binary_document_via_authority",
    "production_worker_runtime",
    "resolve_binary_document_parser_authority",
]
