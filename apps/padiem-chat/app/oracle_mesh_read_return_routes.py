"""#4139 — Oracle management-host MeshCentral read: intent, poll, result.

The Windows Resident trial stays a separate Draft experiment: nothing here
executes on, or requires, the trial PC. This is the product path, and it
executes on the Oracle management host, where the official ``meshctrl.js``
client talks to the local MeshCentral server directly.

Actual call path (no browser carriage of content, no manual copying, no
browser session handed to Oracle):

* Owner intent (browser, owner session + CSRF): ``POST .../mesh-reads/request``
  carries intent only — device, run, root/path, confirmation. The server
  verifies the full existing chain (session, workspace, consent, live broker
  binding, origin run, complete stored correlation, deployment mesh
  ownership) and stages one dispatch row. The browser learns only a
  dispatch id; it never sees content, nonces or secrets.
* Executor poll (Oracle, deployment channel secret): ``POST
  .../mesh-reads/poll`` returns the single oldest claimable dispatch with a
  fresh single-use nonce. The nonce is stored hashed; a database read cannot
  replay an execution.
* Executor submit (Oracle, channel secret + nonce): ``POST
  .../mesh-reads/result`` carries the execution outcome and, on a clean
  exited/0 run, the bytes. The server revalidates everything — secret,
  dispatch state, nonce, expiry, exact correlation against the broker-bound
  row, execution outcome, size, UTF-8, control characters, SHA-256 — and
  appends once through the existing history authority under the standard
  stable message id. A tampered body+hash, a replayed nonce, or a
  cross-command package fails closed; a non-clean execution is delivered to
  the conversation as a truthful bounded failure, never silence.

What these routes are NOT: they enqueue, admit, acknowledge or write nothing
on the broker. The destination conversation is read from the origin run row,
never taken from the caller. The executor identity
(``oracle_management_host``) and the absence of a broker acknowledgment are
reported explicitly: a management-host return never poses as a
device-acknowledged one.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.powershell_literal import ps_literal, ps_utf8_literal
from .oracle_mesh_log import (
    _RESULT_LOG,
    ensure_result_log_host_visible,
    _identity_bridge_failure_log_line,
    _PC_RESULT_ACTION_WORDS,
    _PC_RESULT_STATUS_WORDS,
    _PC_RESULT_REASON_WORDS,
    _pc_result_word,
    log_pc_result_store_stage,
)

from .pc_device_pairing_store import PcPairingError
from .pc_dispatch_ttl import chat_pc_dispatch_ttl, dispatch_ttl_seconds
from .pc_share_timeout import (
    PC_SHARE_UNAVAILABLE_CODE,
    PC_SHARE_UNAVAILABLE_MESSAGE_KO,
    share_command_prefix,
    share_roots_of,
)

from .auth_routes import current_user_id
from .claw_connector_enrollment_routes import _verified_owner_request
from .journal_host import ensure_journal_visible
from .claw_memory_routes import _resolve_memory_workspace
from .claw_pc_read_command import (
    pc_read_chunk_command,
    pc_read_length,
    pc_read_offset,
)
from .claw_pc_search_command import (
    PC_SEARCH_MAX_LIMIT,
    PC_SEARCH_SCAN_MAX_FILES,
    pc_search_command,
    pc_search_mode,
    pc_search_path,
    pc_search_query,
    pc_search_roots,
)
from .claw_local_task_result_projection import result_message_id
from .connector_account_shadow import mode_connector_read
from .control_plane_identity import IdentityBridgeError
from .desktop_typed_text import (
    MAX_TYPED_CHARS as _MAX_TYPED_TEXT_CHARS,
    deposit_typed_text,
    text_is_deliverable,
    type_marker_op,
)
from .history import (
    HistoryError,
    HistoryForbidden,
    MAX_HISTORY_MESSAGE_CHARS,
    is_multi_command_action,
    validate_conversation_id,
)
from .history_append_reason import last_append_reason
from .request_telemetry import emit_stage_event


from .oracle_mesh_contract import (
    ORACLE_MESH_READ_REQUEST_PATH,
    ORACLE_MESH_READ_POLL_PATH,
    ORACLE_MESH_READ_RESULT_PATH,
    ORACLE_MESH_READ_CANCEL_PATH,
    ORACLE_MESH_READ_BUSY_PATH,
    ORACLE_MESH_READ_CANCEL_POLL_PATH,
    ORACLE_MESH_READ_LANE_STATUS_PATH,
    ORACLE_MESH_READ_ORIGINAL_PATH,
    ORACLE_MESH_OWNERSHIP_MAP_ENV,
    ORACLE_MESH_LEGACY_MAP_LANE_ENV,
    RETIRED_OWNERSHIP_MAP,
    ORACLE_MESH_EXECUTION_MODE_ENV,
    EXECUTION_MODE_OFF,
    EXECUTION_MODE_MESH,
    EXECUTION_MODE_NATIVE,
    _EXECUTION_MODES,
    ORACLE_MESH_CHANNEL_SECRET_ENV,
    CONNECTOR_WATCH_READ_SECRET_ENV,
    ORACLE_MESH_CHANNEL_HEADER,
    _DISPATCH_TTL,
    _MAX_RESULT_BODY_BYTES,
    _MAX_BODY_BYTES,
    _MAX_DESKTOP_ENGINE_BODY_BYTES,
    _MAX_COMMAND_MESSAGE_CHARS,
    _MAX_COMMAND_MESSAGE_PARTS,
    _MAX_PATH_VALUE_CHARS,
    _SAFE_REF_CHARS,
    _PRESENCE_BODY_KEYS,
    _PRESENCE_ENTRY_KEYS,
    _PRESENCE_ENTRY_OPTIONAL_KEYS,
    _MAX_PRESENCE_BODY_BYTES,
    _MAX_FILE_TEXT_BYTES,
    _EXECUTOR,
    _COMMAND_ROOT_REF,
    _COMMAND_PATH_RELATIVE,
    _COMMAND_FILE_SENTINEL,
    _COMMAND_SHELL_LABEL,
    _COMMAND_ECHO_MARK,
    _COMMAND_ECHO_PREFIX,
    _REQUEST_KEYS,
    _RESULT_KEYS,
    _RESULT_BLOB_KEYS,
    _RESULT_OPTIONAL_KEYS,
    _DESKTOP_COMMAND_PREFIX,
    _DESKTOP_OPS,
    _DESKTOP_SHELL_LABEL,
    _DESKTOP_SCREENSHOT_MEDIA_TYPE,
    _DESKTOP_SCREENSHOT_MAGIC,
    _DESKTOP_ORIGINAL_MARKER_PREFIX,
    _EMPTY_RESULT_SHA256,
)

from .oracle_mesh_source import (
    legacy_map_lane_enabled,
    UnconfiguredOracleMeshReturnSource,
    OracleMeshReturnSource,
    _resolve_oracle_store_text,
    build_oracle_mesh_return_source,
    _mesh_source_unconfigured,
    _resolve_optional_secret,
    build_oracle_mesh_return_source_from_env,
    valid_claw_engine_desktop_secret,
    host_engine_lane_mount_marker,
)


from .oracle_mesh_execution import resolve_oracle_mesh_execution


from .oracle_mesh_http import (
    _NO_STORE,
    _response,
    _error,
    _BODY_REFUSAL,
    _refused,
    _invalid_body,
    _read_json,
    _text_value,
    _ref,
    _read_body,
    _read_result_body,
    _channel_source,
    _channel_proof,
    _watch_read_proof,
)


from .oracle_mesh_dispatch import (
    oracle_mesh_read_request,
    _dispatch_workspace_id,
    dispatch_oracle_mesh_read_intent,
    _active_owner_link_node,
    _owner_command_target,
    dispatch_oracle_mesh_command_intent,
    dispatch_oracle_mesh_file_read_intent,
    dispatch_oracle_mesh_desktop_intent,
    _deployment_target_for,
)


from .oracle_mesh_desktop_ops import (
    _DESKTOP_KEY_NAMES,
    _DESKTOP_KEY_MODIFIER_CODES,
    _DESKTOP_RESERVED_KEY_COMBOS,
    _desktop_key_combo_is_valid,
    _parse_desktop_op_text,
    _DESKTOP_TYPE_MARKER,
    _desktop_text_ref,
)


from .oracle_mesh_presence import (
    _read_presence,
    _PairingRefusalLog,
    _refusal_reason,
    _pairing_refusal_log,
    _record_mesh_presence,
)


from .oracle_mesh_poll import (
    _oracle_mesh_poll_max_bytes,
    _oracle_mesh_poll_granted_root,
    _oracle_mesh_poll_share_roots,
    oracle_mesh_read_poll,
    oracle_mesh_read_cancel_check,
    oracle_mesh_read_cancel_poll,
    oracle_mesh_read_busy_check,
    oracle_mesh_read_lane_status,
)


from .oracle_mesh_result_projection import (
    _verified_desktop_note,
    _verified_desktop_blob,
    _DESKTOP_OP_LABELS,
    _desktop_op_description,
    _desktop_head,
    _desktop_capture_content,
    _desktop_act_content,
    _desktop_failed_content,
    _verified_result_text,
    _verified_read_result_text,
    _pc_share_unavailable_output,
    _command_header,
    _command_result_content,
    _command_output_withheld_content,
    _command_original_stored_content,
    _command_part_messages,
    _file_read_part_messages,
    _file_read_stored_content,
    _command_markers,
    _command_part_budget,
    _command_head,
    _command_output_parts,
    _oracle_mesh_read_result_verify,
    _oracle_mesh_read_result_outcome,
)


from .oracle_mesh_result_routes import (
    _store_oracle_mesh_read_original,
    oracle_mesh_read_result,
    _oracle_mesh_read_result_store,
    oracle_mesh_read_original,
)


from .oracle_mesh_engine_auth import (
    _verify_engine_proof,
    _ENGINE_PC_FILES_SCOPE_OPS,
    _engine_pc_scope_claim,
    _engine_pc_files_owner,
    _DIRECTORY_UNUSABLE,
    _pc_files_directory_target,
    _engine_pc_files_target,
)


from .oracle_mesh_pc_paths import (
    PC_FILES_MAX_PATH_CHARS,
    PC_FILES_LIST_PAGE_SIZE,
    PC_FILES_READ_MAX_BYTES,
    PC_FILES_ERROR_PREFIX,
    _PC_FILES_READ_TOOL_MARKER,
    _PC_FILES_READ_ROOT_REF,
    _PC_FILES_SAFE_REF,
    _pc_files_text,
    _pc_files_approved_root,
    _pc_files_relative_path,
    _pc_files_roots_of_map_row,
    _DRIVE_REFERENCE,
    _ROOT_WORDS,
    _drive_reference,
    _pc_files_pick_root,
    _pc_files_powershell_literal,
    _PC_FILES_OPS,
    _PC_FILES_READ_OPS,
    _pc_files_read_only,
    _PC_WRITE_OPS,
    _pc_files_claim_op,
    _pc_files_search_roots,
)




#: The op ceilings the signed Engine scope claim may name, per admitted or
#: requested scope name. The names mirror the Engine's own table one-to-one
#: (``PC_REQUEST_SCOPE_TOOLS`` in kagent's pc_query_adapter) — #8098: the
#: three #8048 single-step scopes were missing here, so a recursive name
#: search (``admitted=files_search``) was refused 422 before the PC saw it.
#: The op values derive exactly like the Engine derives them: an op pairs
#: with its tool id, so a scope of only the chunk reader carries no named op
#: (``files_chunk`` → ``[]``). The browser scope is absent on purpose — a
#: browser claim verifies in claw_pc_browser_routes, never on this lane.
from .oracle_mesh_pc_write import (
    PC_BACKUP_FOLDER, PC_WRITE_ACCOUNT_PREFIX, _pc_backup_dir, _pc_ps_literal,
    _pc_write_backup_fragments, _pc_write_input_statements,
    _pc_write_scope_guard, _pc_write_operation_body,
    _pc_write_record_statements, _pc_write_command,
)
from .oracle_mesh_pc_read import (
    _PC_LIST_DEPTH_ROW_CAP, _FILTER_PREFILTER_SAFE,
    _pc_files_filter_prefilter, _pc_files_windows_folder, _pc_files_command,
)

from .oracle_mesh_engine_output import (
    _engine_pc_public_output,
    _engine_pc_job_response,
    _engine_pc_output_call,
    PC_IMAGE_ENVELOPE_PREFIX,
    PC_IMAGE_LONG_EDGE_MAX,
    PC_IMAGE_BYTE_CAP,
    _pc_image_projection,
)


from .oracle_mesh_engine_files import (
    _engine_pc_files_call,
    _engine_pc_files_call_dispatch,
    _engine_pc_files_call_verify,
    oracle_mesh_engine_claw_files_call,
    oracle_mesh_engine_chat_files_call,
)


from .oracle_mesh_engine_desktop import (
    oracle_mesh_engine_desktop_call,
    oracle_chat_engine_pc_drive_call,
)
