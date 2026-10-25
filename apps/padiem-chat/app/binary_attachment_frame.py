"""One binary-attachment request frame for the Chat and Claw lanes (#2505).

The browser cannot put a PDF/DOCX/PPTX/XLSX original into a JSON body without
Base64, so an attached binary document travels as ``application/octet-stream``:
a 4-byte big-endian header size, the JSON request metadata, then the original
bytes. Chat has owned that frame since #4379.

The contract lives here so the Claw lane reads the exact same frame instead of
growing a second decoder. Nothing about the authority changes: the media type,
the extension, the byte grammar and the document text are still validated by
``app/attachments.py`` / ``app/binary_documents.py`` after decoding.
"""

from __future__ import annotations

import json
from typing import Any

#: The metadata header is a bounded JSON envelope, not the document itself.
MAX_HEADER_BYTES = 65536


def decode_binary_attachment_frame(body: bytes) -> dict[str, Any]:
    """One bounded binary original plus JSON request metadata; no browser Base64."""
    if len(body) < 6:
        raise ValueError("invalid binary attachment frame")
    header_size = int.from_bytes(body[:4], "big")
    if not 0 < header_size <= MAX_HEADER_BYTES or len(body) <= 4 + header_size:
        raise ValueError("invalid binary attachment frame")
    raw = json.loads(body[4 : 4 + header_size].decode("utf-8"))
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("attachments"), list)
        or len(raw["attachments"]) != 1
    ):
        raise ValueError("invalid binary attachment metadata")
    item = raw["attachments"][0]
    if not isinstance(item, dict) or set(item) != {"type", "name", "media_type"}:
        raise ValueError("invalid binary attachment metadata")
    if item["type"] not in ("image", "document"):
        raise ValueError("invalid binary attachment type")
    item["raw_bytes"] = body[4 + header_size :]
    return raw


__all__ = ["MAX_HEADER_BYTES", "decode_binary_attachment_frame"]
