"""Shared Oracle Mesh wire constants."""
from __future__ import annotations

import hashlib
from datetime import timedelta

from .history import MAX_HISTORY_MESSAGE_CHARS

ORACLE_MESH_READ_REQUEST_PATH = "/api/claw/connector/mesh-reads/request"
ORACLE_MESH_READ_POLL_PATH = "/api/claw/connector/mesh-reads/poll"
ORACLE_MESH_READ_RESULT_PATH = "/api/claw/connector/mesh-reads/result"
#: Executor read of one owner's stop. The dispatch id the executor already holds
#: is the only value it sends, nothing is claimed or written here, and the answer
#: is one boolean: has the owner asked for this running command to end?
ORACLE_MESH_READ_CANCEL_PATH = "/api/claw/connector/mesh-reads/cancel"
#: Executor read of one PC's live claims. The node reference the executor is about
#: to sweep, plus its own dispatch id so its own claim is not counted, in; one
#: boolean out. Nothing is claimed or written here either.
ORACLE_MESH_READ_BUSY_PATH = "/api/claw/connector/mesh-reads/busy"
#: #7215: a PUBLIC, per-dispatch-token read of one dispatch's cancel flag. The
#: user-mode PC client (SYSTEM) polls it so an owner's stop reaches a command that
#: has already left the queue — the PC's MeshAgent console lane echoes input instead
#: of running it, so the executor's taskkill never fires (R4 #7188 wires the process
#: lane). No channel secret (the token is the only authority), no new port.
ORACLE_MESH_READ_CANCEL_POLL_PATH = "/api/claw/connector/mesh-reads/cancel-poll"
#: #82 monitoring read: the lane's own counts and ages, plus how recently each named
#: device last reported its presence beat. Read-only, same channel proof as poll, and
#: it claims nothing — a monitor may ask every few minutes forever.
ORACLE_MESH_READ_LANE_STATUS_PATH = "/api/claw/connector/mesh-reads/lane-status"
#: Owner-scoped read of one stored over-budget command original. The dispatch
#: id is the only browser-supplied value; the object key, the conversation and
#: the message id are all re-derived server-side, so no browser-chosen object
#: path or foreign-account result is addressable here.
ORACLE_MESH_READ_ORIGINAL_PATH = "/api/claw/connector/mesh-results/{dispatch_id}"
#: Deployment-owned ownership map, read from Worker env by the worker root.
#: JSON list of {account_ref, device_id, node_ref, root_ref, path_relative,
#: file_path}. Absent or invalid keeps the source unconfigured; the routes
#: stay unmounted.
ORACLE_MESH_OWNERSHIP_MAP_ENV = "ORACLE_MESH_OWNERSHIP_MAP"
#: #5573 follow-up: retire the legacy map lane. "off" means a TXT request that would have
#: been answered from the deployment map is refused with a guidance error (never a 403),
#: and the channel source composes **without** the map at all - so a deployment that has
#: no ownership map (or no V2 to build) still runs poll/renew/cancel/busy. Any other value
#: or absence keeps today's behaviour, which is also the rollback.
ORACLE_MESH_LEGACY_MAP_LANE_ENV = "ORACLE_MESH_LEGACY_MAP_LANE"
#: One inert row, valid by the source's own rules and authorizing nobody: classify() says
#: "none" for every request and command_target() finds no grant, which is exactly the
#: retired lane's meaning. It exists because the channel source cannot be built without
#: rows, and it is never written anywhere.
RETIRED_OWNERSHIP_MAP = (
    {"account_ref": "__retired__", "node_ref": "__retired__",
     "root_ref": "__retired__", "path_relative": "__retired__.txt",
     "file_path": "__retired__.txt", "command_exec": False},
)


#: Which execution lane a TXT request takes:
#:   "off"    — Mesh execution disabled; the request stays on the native lane.
#:   "mesh"   — the request runs on the management host through the Mesh
#:              ownership map, whether or not the PC has a native binding.
#:   "native" — the request always stays on the native device lane.
ORACLE_MESH_EXECUTION_MODE_ENV = "ORACLE_MESH_EXECUTION_MODE"
EXECUTION_MODE_OFF = "off"
EXECUTION_MODE_MESH = "mesh"
EXECUTION_MODE_NATIVE = "native"
_EXECUTION_MODES = (EXECUTION_MODE_OFF, EXECUTION_MODE_MESH, EXECUTION_MODE_NATIVE)
#: Deployment channel secret for the Oracle executor (Worker env on Chat,
#: operator-held file on Oracle). Compared constant-time, never logged.
ORACLE_MESH_CHANNEL_SECRET_ENV = "ORACLE_MESH_CHANNEL_SECRET"
#: #82: a READ-ONLY secret for the connector watch. It opens the lane-status read and
#: nothing else. poll, renew, cancel, busy and result keep the channel secret, because
#: that value can claim a dispatch and submit a result on a customer PC — a workflow
#: holding it could take work away from the executor or plant a result for work that
#: never ran. The two secrets must differ: two names for one value is a comment, not
#: a boundary.
CONNECTOR_WATCH_READ_SECRET_ENV = "CONNECTOR_WATCH_READ_SECRET"
#: Header carrying the channel secret on poll/submit.
ORACLE_MESH_CHANNEL_HEADER = "X-Oracle-Mesh-Secret"
#: How long one dispatch stays claimable/submittable.
_DISPATCH_TTL = timedelta(seconds=600)
#: #4139 result wire envelope on this connector.
#: The result JSON buffers PC file content; use the Owner's 32MiB memory
#: exception so a 20MB read is not rejected at the old 6MB channel envelope.
#: Other request bodies and verified non-PC-read contents keep 6MB.
#: Owner decision 2026-10-28: no PADIEM request-body ceiling. The
#: platform's own request limit (~100MB on Workers) is the bound; a
#: rejected oversized result is reported as 'result too large for this
#: path' by the caller that receives the platform refusal.
_MAX_RESULT_BODY_BYTES: int | None = None
_MAX_BODY_BYTES = 6_000_000
#: #6460 step 3 — the signed desktop lane's proof envelope. A typed value is
#: bounded at 20000 characters by the one-shot store; worst-case JSON escaping
#: is six bytes per BMP character and twelve per astral character, so 256 KB
#: holds the largest allowed value. Every field is parsed and bounded again
#: after the proof check.
_MAX_DESKTOP_ENGINE_BODY_BYTES = 256_000
#: One stored conversation message. Reuses the existing product bound
#: (``history.MAX_HISTORY_MESSAGE_CHARS``); a larger output is split across
#: several messages, never truncated.
_MAX_COMMAND_MESSAGE_CHARS = MAX_HISTORY_MESSAGE_CHARS
#: Resource guard, not a data limit: how many message rows one run may create.
#: Above it the verified original goes to the private store and the
#: conversation carries one preview plus the owner-scoped retrieval reference,
#: so the bytes are never lost — only the row count is bounded.
_MAX_COMMAND_MESSAGE_PARTS = 256
#: A Windows path is ordinary input: Korean, spaces and any printable character
#: are allowed. The ceiling is the documented extended-length path maximum
#: (32,767 characters, Microsoft "Maximum Path Length Limitation"); the former
#: 1,024-character trial bound rejected a legal long path. Only control
#: characters are refused.
_MAX_PATH_VALUE_CHARS = 32_767
_SAFE_REF_CHARS = frozenset(
    # "$" is part of a MeshCentral node id, and node_ref is read here.
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:@+-$"
)
#: #5553 optional executor presence beat carried on the poll. It is additive:
#: the poll body, response and authorization are unchanged when it is absent
#: or malformed, and every derived identity is resolved server-side.
_PRESENCE_BODY_KEYS = frozenset({"presence"})
_PRESENCE_ENTRY_KEYS = frozenset({"device_id", "connected"})
# #5573: one optional key carries the observed agent NAME. A beta PC cannot
# name its own composed node identity, so the pairing tag the installer stamped
# into that name is what lets the server finish the claim it was given a code
# for. The name is read, never stored.
_PRESENCE_ENTRY_OPTIONAL_KEYS = frozenset({"agent_name"})
# The requested device-id list has no arbitrary count cap (#5882 2차): the
# caller is the trusted executor naming its own devices, and the 8KiB
# request-body ceiling below is the real bound on how many can arrive.
_MAX_PRESENCE_BODY_BYTES = 8192
#: #4139 read lane envelope, shared with the command lane and the executor.
#: No PADIEM text ceiling on a verified result (Owner decision 2026-10-28).
_MAX_FILE_TEXT_BYTES: int | None = None
_EXECUTOR = "oracle_management_host"
#: #4139 terminal lane. A command dispatch has no file, so the 047 file
#: columns carry these fixed, self-describing sentinels instead of a bogus
#: Windows path; a read-lane use of a command row therefore fails loudly.
_COMMAND_ROOT_REF = "mesh_terminal"
_COMMAND_PATH_RELATIVE = "command"
_COMMAND_FILE_SENTINEL = "command"
#: How a command result is labelled in the conversation. The execution
#: method is recorded verbatim because MeshCentral runs it through the
#: device shell (PowerShell here), not through this server.
_COMMAND_SHELL_LABEL = "PowerShell (MeshCentral runcommand --reply)"
#: The result message echoes the command that ran. When that echo cannot fit
#: beside at least one output character, it is marked instead of pushing the
#: output out of the message: the full command stays in the user's own turn and
#: in the dispatch row, so the mark discloses nothing but a display bound.
_COMMAND_ECHO_MARK = "…(전체 명령은 보낸 메시지와 dispatch에 보존)"
_COMMAND_ECHO_PREFIX = "명령: "

_REQUEST_KEYS = frozenset({"device_id", "run_id", "root_ref", "path_relative", "confirmed"})
_RESULT_KEYS = frozenset({
    "dispatch_id", "nonce", "termination", "exit_code",
    "content_utf8", "content_sha256", "content_bytes",
})
#: The screenshot blob rides beside the note on capture turns only; input
#: turns carry no blob keys at all. Optional, never required, never trusted
#: without the digest check below.
_RESULT_BLOB_KEYS = frozenset({
    "content_blob_base64", "content_blob_sha256", "content_blob_bytes",
    "content_blob_media_type",
})
#: ``node_ref`` is the executor's own claim target. A submission that carries
#: it is compared with the dispatch row; an executor from before this field is
#: still readable, and the row's nonce remains the gate for it.
_RESULT_OPTIONAL_KEYS = _RESULT_BLOB_KEYS | {"node_ref"}
#: #4139 desktop lane. A desktop dispatch carries its op in the command_text
#: field (``desktop:<op>`` plus an optional argument line) with the same file
#: sentinels as a command dispatch, so neither lane can retarget the read
#: lane's file authority.
_DESKTOP_COMMAND_PREFIX = "desktop:"
_DESKTOP_OPS = ("capture", "type", "keys", "click")
_DESKTOP_SHELL_LABEL = "COM1 데스크톱 릴레이 (MeshCentral meshrelay p=2 + MSC)"
#: The only screenshot media type the executor produces. The browser renders
#: it; anything else is refused, never stored or served as an image.
_DESKTOP_SCREENSHOT_MEDIA_TYPE = "image/jpeg"
_DESKTOP_SCREENSHOT_MAGIC = b"\xff\xd8\xff"
#: Server-shaped screenshot reference marker. The conversation carries this
#: exact line and the frontend renderer fetches only this same-origin path,
#: so no browser-chosen URL can ever become an image in the conversation.
_DESKTOP_ORIGINAL_MARKER_PREFIX = "화면 캡처 원문: GET /api/claw/connector/mesh-results/"

#: Canonical fingerprint of zero bytes. Earlier executors pin an empty
#: string for an empty read, but the pin column requires a value; the
#: result route normalizes that exact legacy shape below instead of
#: stranding every resend on 409.
_EMPTY_RESULT_SHA256 = hashlib.sha256(b"").hexdigest()
