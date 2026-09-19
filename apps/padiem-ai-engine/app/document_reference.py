"""Document-specific reference and error authority for Engine E8C-B (#2741).

This module owns the canonical ``doc_*`` reference grammar for original
document bytes. The ``doc_*`` namespace is deliberately separate from the
multimodal image ``att_*`` namespace owned by ``app.attachment_authority``:
same grammar != same storage, and a document reference must never be
resolvable against the image attachment store (or vice versa). This module
must not grow image grammar, storage semantics, media allowlists or scope
derivation; those stay with their existing owners.

It also freezes the safe resolver error vocabulary once (the S2
``DocumentResolutionError``) so the durable document store seam can map
failure modes into one authority language rather than two competing
vocabularies. Error messages are static per code: they never echo payload
bytes, references-as-locators, storage state or scope values.
"""

from __future__ import annotations

import re

# Canonical document reference grammar: opaque, server-minted, never a
# locator, never a client choice. Length class mirrors the image
# attachment grammar so both namespaces share one collision-safe shape.
DOC_REFERENCE_PATTERN = re.compile(r"^doc_[A-Za-z0-9_-]{16,120}$")

# Logical D1 binding alias declared in wrangler.toml; the composition slice
# reads it through the deployment-owned binding lookup. Declaration only:
# no provisioning, no composition and no activation live in this module.
DOCUMENT_STORE_BINDING_NAME = "ENGINE_DOCUMENT_STORE"

# Safe resolver/store error codes for the document read path.
# "expired" and "terminal" extend the frozen S2 set for durable-retention
# failure modes; every other code keeps its S2 meaning unchanged.
RESOLUTION_ERROR_CODES = frozenset(
    {
        "invalid_reference",
        "invalid_scope",
        "unauthorized",
        "not_found",
        "integrity_mismatch",
        "decode_failed",
        "unsupported_media_type",
        "expired",
        "terminal",
        "store_unavailable",
    }
)


class DocumentResolutionError(ValueError):
    """Fail-closed document resolution error safe for first-party products."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or code not in RESOLUTION_ERROR_CODES:
            raise ValueError("document resolution error code must be a known safe code")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def require_document_reference(value: object) -> str:
    """Accept only opaque references matching the ``doc_*`` document grammar."""

    if not isinstance(value, str) or not DOC_REFERENCE_PATTERN.fullmatch(value):
        raise DocumentResolutionError(
            "invalid_reference",
            "Document reference is invalid.",
        )
    return value
