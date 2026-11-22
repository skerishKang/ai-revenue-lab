from __future__ import annotations

import base64
import binascii
import hashlib
import inspect
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .history_append_reason import APPEND_REASON_ALREADY_COMPLETED, APPEND_REASON_SAME_MESSAGE, APPEND_REASON_SUMMARY_GUARD, APPEND_REASON_SUMMARY_SAME, refused as _refused, stored as _stored
from .workspace_storage import _safe_identifier
from .pc_command_confirmation import (
    PENDING_PC_COMMAND_MAX_AGE_SECONDS,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_EXPIRED,
)
from .history_errors import (
    HistoryConflict,
    HistoryContextIncomplete,
    HistoryError,
    HistoryForbidden,
    HistoryPinUnavailable,
)
from .history_text import HISTORY_PREVIEW_SUFFIX, _bounded_text, _confirmation_card_cutoff, _expire_stale_confirmation_cards_rule, _is_bounded_preview, _iso, _lane_count_age, _lane_node, _lane_seconds, _now_iso, _title_from_user_text, expire_stale_confirmation_cards_for_all_owners
from .history_types import (
    HistoryStore,
    PasswordCredential,
    ProjectProfile,
    UserProfile,
    VerifiedDispatch,
    _VERIFIED_FOR,
)
from .history_constants import (
    MAX_CLAW_HANDOFF_TRUSTED_REQUEST_CHARS,
    MAX_CLAW_RUNS,
    MAX_HISTORY_MESSAGE_CHARS,
    MAX_HISTORY_TITLE_CHARS,
    MAX_MODEL_CONTEXT_BYTES,
    MAX_PROJECTS,
    MAX_PROJECT_NAME_CHARS,
    MAX_RECENT_CONVERSATIONS,
    MULTI_COMMAND_RUN_ACTIONS,
    ORACLE_MESH_CLAIM_LEASE_SECONDS,
    ORACLE_MESH_CLAIMABLE_SQL,
    ORACLE_MESH_READ_ONLY_SQL,
    ORACLE_MESH_UNREDELIVERABLE_SQL,
    PC_CONFIRMATION_CARD_ACTIONS,
    PRODUCT_SCOPE_B66,
    PRODUCT_SCOPE_CHAT,
    KNOWN_PRODUCT_SCOPES,
    PC_SCOPE_NOTICE_LABELS,
    _APPEND_EXCHANGE_SQL,
    _APPEND_USER_MESSAGE_SQL,
    _require_product_scope,
    is_multi_command_action,
    pc_scope_notice,
    strip_pc_scope_marker,
    strip_pc_session_confirmation_marker,
)
from .history_ids import (
    GENERAL_ANSWER_MESSAGE_SALT,
    MODEL_ONLY_RUN_ACTION,
    _CLAW_HANDOFF_TRUSTED_REQUEST_KEYS,
    _chat_id,
    _handoff_expired,
    _handoff_id,
    _handoff_trusted_request_json,
    _message_id,
    _message_reference,
    _parse_handoff_expiry,
    _password_user_id,
    _project_id,
    _run_history_id,
    _user_id,
    _validate_hex_id,
    build_project_context,
    general_answer_message_id,
    validate_chat_pc_run_id,
    validate_conversation_id,
    validate_project_fields,
    validate_project_id,
)
from .history_rows import (
    _batch_returned_row,
    _changed_rows,
    _project_from_row,
    _row_to_dict,
    _rows_from_result,
    _run_history_public,
    _run_history_session,
    _tagged,
)
from .history_store_core import StoreCore
from .history_store_handoff import ApprovalHandoffStore
from .history_store_accounts import AccountStore
from .history_store_conversations import ConversationStore
from .history_store_runs import RunStore
from .history_store_run_events import RunEventStore
from .history_store_mesh import MeshDispatchStore

from .history_search import (
    MAX_CONVERSATION_SEARCH_QUERY_CHARS,
    MAX_CONVERSATION_SEARCH_RESULTS,
    MAX_CONVERSATION_SEARCH_SCAN_ROWS,
    MAX_CONVERSATION_SEARCH_SNIPPET_CHARS,
    _normalize_search_query,
    _search_snippet,
)

from .history_pinned import _PINNED_COLUMN_MISSING, _pinned_column_missing
from .history_project_cursor import (
    PROJECT_CURSOR_MAX_CHARS,
    ProjectCursorError,
    decode_project_cursor,
    encode_project_cursor,
)
from .history_run_summary import (
    MAX_RUN_RESULT_SUMMARY_CHARS,
    _merge_run_result_summaries,
)
from .history_mesh_original import (
    MAX_MESH_PATH_CHARS,
    MAX_MESH_REFERENCE_CHARS,
    MAX_MESH_ROW_BYTES,
    ORACLE_MESH_ORIGINAL_MAX_BYTES,
    _MESH_PATH_FIELDS,
    _MESH_RESULT_MESSAGE_ID_RE,
    _oracle_mesh_original_max_bytes,
)

__all__ = [
    "hashlib", "inspect", "datetime", "timezone",
    "_iso", "_lane_count_age", "_lane_node",
    "_changed_rows", "_tagged",
    "ORACLE_MESH_ORIGINAL_MAX_BYTES", "_oracle_mesh_original_max_bytes",
]


class D1HistoryStore(RunStore, RunEventStore, MeshDispatchStore, ConversationStore, AccountStore, ApprovalHandoffStore):
    """Cloudflare D1 adapter. All dynamic values use prepared statement binds."""

    async def get_oracle_mesh_dispatch_pin(self, *, user_id: str, dispatch_id: str):
        """The owner-scoped pin: who dispatched it and what result was already accepted."""

        if not isinstance(user_id, str) or not user_id:
            return None
        if not isinstance(dispatch_id, str) or not dispatch_id:
            return None
        row = await self._first(
            "SELECT user_id, result_sha256, result_bytes, kind, root_ref FROM oracle_mesh_dispatch "
            "WHERE dispatch_id=?",
            dispatch_id,
        )
        return self._verified(row, user_id)

    async def get_oracle_mesh_run_correlation(self, *, user_id: str, run_id: str):
        """The terminal receipt of one run, read wherever dispatch rows live."""

        if not isinstance(user_id, str) or not user_id:
            return None
        if not isinstance(run_id, str) or not run_id:
            return None
        row = await self._first(
            "SELECT user_id, command_id, revision_ref, dispatch_id FROM oracle_mesh_dispatch "
            "WHERE user_id=? AND run_id=? AND state='done'",
            user_id, run_id,
        )
        return self._verified(row, user_id)

    async def get_oracle_mesh_run_command(self, *, user_id: str, run_id: str, command_id: str):
        """Whether one command was dispatched by this owner inside this run."""

        row = await self._first(
            "SELECT user_id, dispatch_id FROM oracle_mesh_dispatch "
            "WHERE user_id=? AND run_id=? AND command_id=? LIMIT 1",
            user_id, run_id, command_id,
        )
        return self._verified(row, user_id)

    async def get_oracle_mesh_run_open_state(self, *, user_id: str, run_id: str) -> dict:
        """Which of this run's dispatches still lack a terminal result, and which failed."""

        pending = await self._first(
            "SELECT dispatch_id FROM oracle_mesh_dispatch "
            "WHERE user_id=? AND run_id=? AND state NOT IN ('done', 'failed') LIMIT 1",
            user_id, run_id,
        )
        failed = await self._first(
            "SELECT dispatch_id FROM oracle_mesh_dispatch "
            "WHERE user_id=? AND run_id=? AND state='failed' LIMIT 1",
            user_id, run_id,
        )
        return {
            "pending_dispatch_id": (pending or {}).get("dispatch_id"),
            "failed_dispatch_id": (failed or {}).get("dispatch_id"),
        }

    async def _mesh_dispatch_pin(self, *, user_id: str, dispatch_id: str,
                                 expected_sha256: str, expected_bytes: int,
                                 verified: Any = None):
        """The owner + pin check the original stores share, without a D1 re-read.

        A handle is honoured only when it is the tagged dict an owner-scoped read produced
        for this same user; a plain dict — however well shaped — falls back to the
        authoritative lookup, so a caller cannot talk its way past the check by inventing a
        row. Forgery of the pin and another owner's dispatch stay refused either way.
        """

        row: Any = verified if isinstance(verified, VerifiedDispatch) else None
        if row is not None and (row.verified_for != user_id
                                or row.get("user_id") not in (None, user_id)):
            raise HistoryForbidden("mesh dispatch is not owned by current user")
        if row is None:
            row = await self._dispatch("get_oracle_mesh_dispatch_pin",
                                        user_id=user_id, dispatch_id=dispatch_id)
        if row is None:
            raise HistoryForbidden("mesh dispatch is not owned by current user")
        if row.get("result_sha256") != expected_sha256 or row.get("result_bytes") != expected_bytes:
            raise HistoryError("mesh original does not match the pinned result")
        return row

    async def _run_is_owned(self, run_id: str, user_id: str) -> bool:
        if self.run_ownership is not None:
            owned = self.run_ownership(run_id, user_id)
            if hasattr(owned, "__await__"):
                owned = await owned
            return bool(owned)
        row = await self._first(
            "SELECT id FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        return row is not None


