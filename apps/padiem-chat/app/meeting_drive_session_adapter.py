"""#4647 Drive upload-session adapter — an injection seam, not a Drive grant.

What is actually available on current main, measured rather than assumed:

- no Google Drive WRITE scope is registered in the canonical connector/Control Plane
  grant authority, and no code anywhere mints a resumable session URI;
- Engine ships `DriveReadPort` (`drive_port_httpx`, `drive_port_cp_lease`) — READ only;
- `claw_durable_drive_output_pipeline` states `drive_write_enabled_by_this_service: False`.

So a real upload producer cannot be built inside the meeting lane without a
WRITE-scoped lease from Control Plane plus one Drive `files?uploadType=resumable`
POST. This module is the shape that production plugs into: it validates the
server-owned inputs, forwards to a trusted injected client, and returns exactly the
one field the route consumes. It never fabricates a session, never accepts browser
input as authority, and keeps the route's fail-closed 503 for every unconfigured or
failing state.

Required client contract (for the Connector/Control Plane owner to implement):

    start_resumable_session(*, owner_id, workspace_ref, filename, mime_type,
                            byte_size) -> Mapping with key "session_uri"

The returned value must be a Google-owned `https://www.googleapis.com/upload/drive/v3/
files?uploadType=resumable&upload_id=...` URI for THIS owner's own Drive. The route, not
this adapter, validates its shape, and the URI is a capability: do not log or store it.
"""
from __future__ import annotations

import inspect
from typing import Any

from .meeting_drive_upload_routes import _MEDIA_TYPES

_OWNER_MAX = 160
_WORKSPACE_MAX = 160
_FILENAME_MAX = 200


class MeetingDriveSessionUnavailable(RuntimeError):
    """Trusted producer missing or refused. The route turns this into its bounded 503."""


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class MeetingDriveSessionAdapter:
    """Satisfies `meeting_drive_upload_session_port` for one verified Drive WRITE client."""

    def __init__(self, session_client: Any):
        start = getattr(session_client, "start_resumable_session", None)
        if not callable(start):
            raise ValueError("Drive WRITE upload-session client is required")
        self._client = session_client

    async def begin_authorized_upload(self, *, owner_id: Any, workspace_ref: Any,
                                      filename: Any, mime_type: Any,
                                      byte_size: Any) -> dict[str, str]:
        if (not isinstance(owner_id, str) or not (1 <= len(owner_id) <= _OWNER_MAX)
                or not isinstance(workspace_ref, str)
                or not (1 <= len(workspace_ref) <= _WORKSPACE_MAX)):
            raise MeetingDriveSessionUnavailable("meeting Drive owner scope unresolved")
        if (not isinstance(filename, str) or not (1 <= len(filename) <= _FILENAME_MAX)
                or "/" in filename or "\\" in filename):
            raise MeetingDriveSessionUnavailable("meeting Drive filename unresolved")
        # The media vocabulary belongs to the route; this is a pass-through guard,
        # not a second table of allowed types.
        if mime_type not in _MEDIA_TYPES:
            raise MeetingDriveSessionUnavailable("meeting Drive media type unsupported")
        ceiling = _MEDIA_TYPES[mime_type][0]
        if type(byte_size) is not int or not 1 <= byte_size <= ceiling:
            raise MeetingDriveSessionUnavailable("meeting Drive size unsupported")
        try:
            result = await _await(self._client.start_resumable_session(
                owner_id=owner_id, workspace_ref=workspace_ref, filename=filename,
                mime_type=mime_type, byte_size=byte_size))
        except MeetingDriveSessionUnavailable:
            raise
        except Exception as exc:
            # Never propagate a provider message: it can carry token or grant text.
            raise MeetingDriveSessionUnavailable("meeting Drive session refused") from exc
        uri = result.get("session_uri") if isinstance(result, dict) else None
        if not isinstance(uri, str) or not uri:
            raise MeetingDriveSessionUnavailable("meeting Drive session refused")
        return {"session_uri": uri}
