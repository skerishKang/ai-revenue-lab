"""Engine-side COM2 file-lane text window read for #5881 stage 3.

The file lane owns the original bytes and their parsing; the Engine reads only
the extracted text, from the one deployment-configured HTTPS origin. The read
ticket is Chat's own signed claim: the Engine forwards the three
``X-Padiem-File-*`` header values verbatim and interprets nothing, so no
file-lane signing secret is ever held here. A browser-supplied ``file_id``
selects a path under the configured origin and nothing else.

``FILE_LANE_ORIGIN`` unset means the composition root passes no port: the
inline document admission path stays exactly as it was, and a reference-shaped
request fails closed instead of reading a caller-named host.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from urllib.parse import urlsplit, urlunsplit
from typing import Any

import httpx

from app.cloudflare_external_transport import CloudflareExternalHttpTransport
from app.document_context_projection import MAX_CONTEXT_PREVIEW_CHARS

FILE_LANE_ORIGIN_ENV = "FILE_LANE_ORIGIN"

# Same grammar the lane itself mints (padiem_file_lane.storage.FILE_PATTERN).
FILE_ID_PATTERN = re.compile(r"\Afile_[a-f0-9]{32}\Z")
_SOURCE_DIGEST_PATTERN = re.compile(r"\A[a-f0-9]{64}\Z")

# Names are fixed; values pass through untouched. Printable ASCII only, so a
# request-supplied value can never inject a header or crash the transport.
FILE_TICKET_HEADER_NAMES = frozenset(
    {"X-Padiem-File-Ticket", "X-Padiem-File-Time", "X-Padiem-File-Proof"}
)
_TICKET_VALUE_SAFE_RE = re.compile(r"\A[\x20-\x7e]+\Z")
_ERROR_CODE_RE = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")

TEXT_WINDOW_EOF_HEADER = "X-File-Lane-EOF"
TEXT_WINDOW_NEXT_OFFSET_HEADER = "X-File-Lane-Next-Offset"

# One window is the largest text the existing context projection can mount at
# all; the remainder stays readable from ``next_offset`` on the lane.
DEFAULT_TEXT_WINDOW_CHARS = MAX_CONTEXT_PREVIEW_CHARS

_STATUS_CODES: dict[int, tuple[str, int]] = {
    400: ("file_lane_request_rejected", 400),
    401: ("file_lane_ticket_rejected", 401),
    404: ("file_lane_file_not_found", 404),
    413: ("file_lane_ticket_rejected", 413),
    415: ("file_lane_unsupported", 415),
    422: ("file_lane_parse_failed", 422),
}


class FileLaneTextError(ValueError):
    """Fail-closed file-lane read error carrying a safe code for the wire."""

    def __init__(self, code: str, *, status_code: int = 503) -> None:
        super().__init__("COM2 file lane text could not be read.")
        if not isinstance(code, str) or not _ERROR_CODE_RE.fullmatch(code):
            raise ValueError("file lane error code must be a safe identifier")
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class FileLaneTextWindow:
    """One window of lane-extracted text plus its continuation coordinates.

    ``total_chars`` is exact only once the lane reports end of file: a window
    that stops mid-document proves the document is longer, never how long.
    """

    text: str
    next_offset: int
    eof: bool
    total_chars: int | None


def normalize_file_lane_origin(value: Any) -> str:
    """Accept only a bare HTTPS origin: no path, credentials, query or port."""

    origin = value.strip() if isinstance(value, str) else ""
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.strip("/")
    ):
        raise FileLaneTextError("file_lane_origin_invalid", status_code=503)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def file_lane_worker_transport(origin: str) -> httpx.AsyncBaseTransport | None:
    """Worker-native transport pinned to the configured file-lane host.

    Off the Pyodide runtime the ordinary httpx transport is kept, exactly as
    the Drive/Calendar ports do, so MockTransport injection and network-free
    composition tests stay valid.
    """

    import sys

    if sys.platform != "emscripten":
        return None
    return CloudflareExternalHttpTransport(
        allowed_hosts=frozenset({urlsplit(origin).hostname})
    )


class FileLaneTextPort:
    """Bounded GET of the lane's cached text window for one origin."""

    def __init__(
        self,
        *,
        origin: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._origin = normalize_file_lane_origin(origin)
        self._transport = transport

    @property
    def origin(self) -> str:
        return self._origin

    async def read_window(
        self,
        *,
        file_id: object,
        sha256: object,
        ticket: object,
        offset: int = 0,
        max_chars: int = DEFAULT_TEXT_WINDOW_CHARS,
    ) -> FileLaneTextWindow:
        self._require_reference(file_id=file_id, sha256=sha256)
        headers = self._ticket_headers(ticket)
        url = f"{self._origin}/files/{file_id}/text"
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=None,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET",
                    url,
                    params={"offset": str(offset), "max_chars": str(max_chars)},
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        raise self._failure(response.status_code)
                    parts = [part async for part in response.aiter_text()]
                    eof_header = response.headers.get(TEXT_WINDOW_EOF_HEADER)
                    next_offset_header = response.headers.get(
                        TEXT_WINDOW_NEXT_OFFSET_HEADER
                    )
        except FileLaneTextError:
            raise
        except httpx.HTTPError:
            # Transport exception text can carry the request URL and headers.
            raise FileLaneTextError("file_lane_unavailable") from None
        return self._window(
            text="".join(parts),
            offset=offset,
            eof_header=eof_header,
            next_offset_header=next_offset_header,
        )

    @staticmethod
    def _require_reference(*, file_id: object, sha256: object) -> None:
        if not isinstance(file_id, str) or not FILE_ID_PATTERN.fullmatch(file_id):
            raise FileLaneTextError("invalid_file_reference", status_code=400)
        # The caller's asserted source digest: grammar only, never interpreted.
        if not isinstance(sha256, str) or not _SOURCE_DIGEST_PATTERN.fullmatch(sha256):
            raise FileLaneTextError("invalid_source_digest", status_code=400)

    @staticmethod
    def _ticket_headers(ticket: object) -> dict[str, str]:
        if not isinstance(ticket, Mapping) or set(ticket) != FILE_TICKET_HEADER_NAMES:
            raise FileLaneTextError("invalid_file_ticket", status_code=400)
        headers = {}
        for name, value in ticket.items():
            if not isinstance(value, str) or not _TICKET_VALUE_SAFE_RE.fullmatch(value):
                raise FileLaneTextError("invalid_file_ticket", status_code=400)
            headers[name] = value
        return headers

    @staticmethod
    def _failure(status: int) -> FileLaneTextError:
        # Only the status is read: the lane's error body is not parsed here.
        code, engine_status = _STATUS_CODES.get(status, ("file_lane_read_failed", 502))
        return FileLaneTextError(code, status_code=engine_status)

    @staticmethod
    def _window(
        *, text: str, offset: int, eof_header: object, next_offset_header: object
    ) -> FileLaneTextWindow:
        if not isinstance(next_offset_header, str) or not next_offset_header.isdigit():
            raise FileLaneTextError("file_lane_invalid_response", status_code=502)
        if eof_header not in ("true", "false"):
            raise FileLaneTextError("file_lane_invalid_response", status_code=502)
        next_offset = int(next_offset_header)
        if next_offset != offset + len(text):
            # A misreported continuation offset would silently skip document
            # text on the next window, so the window is refused, not mounted.
            raise FileLaneTextError("file_lane_invalid_response", status_code=502)
        eof = eof_header == "true"
        return FileLaneTextWindow(
            text=text,
            next_offset=next_offset,
            eof=eof,
            total_chars=next_offset if eof else None,
        )


__all__ = [
    "DEFAULT_TEXT_WINDOW_CHARS",
    "FILE_ID_PATTERN",
    "FILE_LANE_ORIGIN_ENV",
    "FILE_TICKET_HEADER_NAMES",
    "FileLaneTextError",
    "FileLaneTextPort",
    "FileLaneTextWindow",
    "file_lane_worker_transport",
    "normalize_file_lane_origin",
]
