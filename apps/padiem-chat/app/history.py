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

    #: #82 monitoring reads this to answer "is anything waiting that nobody is
    #: claiming" without a log line and without a string match. The node list is
    #: bounded the same way the presence beat is (#5553 shares the number).
    LANE_STATUS_NODE_LIMIT = 8

    async def oracle_mesh_lane_status(
        self, *, node_limit: int = LANE_STATUS_NODE_LIMIT,
    ) -> dict[str, Any]:
        """The dispatch lane's own state, as counts and ages.

        Three questions, all of them answerable from the columns the lane already
        writes: work that no executor has claimed (`state='pending'`, unexpired, no
        nonce or a lease that has run out — the exact condition the poll yields on),
        work a claim is held for right now (the lease columns #5997 renews), and,
        per PC, how long its oldest unanswered dispatch has been waiting.

        Ages are computed here from the stored timestamps rather than in SQL, so the
        D1 and the local SQLite dialect answer the same way and one number cannot
        drift between environments.
        """
        if (isinstance(node_limit, bool) or not isinstance(node_limit, int)
                or not 1 <= node_limit <= 64):
            raise HistoryError("node_limit is out of range")
        moment = datetime.now(timezone.utc)
        now = _iso(moment)
        waiting = await self._first(
            "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM oracle_mesh_dispatch "
            "WHERE state=? AND expires_at>? "
            "AND (nonce_sha256 IS NULL OR (claimed_until IS NOT NULL AND claimed_until<=?))",
            "pending", now, now,
        )
        claimed = await self._first(
            "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM oracle_mesh_dispatch "
            "WHERE state=? AND expires_at>? AND nonce_sha256 IS NOT NULL AND claimed_until>?",
            "pending", now, now,
        )
        # Per PC, two different questions, because the owner standard keeps them
        # apart: `open` is everything still unfinished there (a long command under a
        # live claim is that, and nothing may call it a stop), while `waiting` is
        # only the work no claim covers. A silence verdict reads `waiting` alone.
        nodes = await self._all(
            "SELECT node_ref, COUNT(*) AS n, MIN(created_at) AS oldest, "
            "SUM(CASE WHEN nonce_sha256 IS NULL "
            "OR (claimed_until IS NOT NULL AND claimed_until<=?) THEN 1 ELSE 0 END) "
            "AS waiting, "
            "MIN(CASE WHEN nonce_sha256 IS NULL "
            "OR (claimed_until IS NOT NULL AND claimed_until<=?) THEN created_at "
            "ELSE NULL END) AS waiting_oldest "
            "FROM oracle_mesh_dispatch WHERE state=? AND expires_at>? "
            "AND node_ref IS NOT NULL AND node_ref<>'' "
            "GROUP BY node_ref ORDER BY oldest ASC LIMIT ?",
            now, now, "pending", now, node_limit,
        )
        return {
            "unclaimed": _lane_count_age(waiting, moment),
            "claimed": _lane_count_age(claimed, moment),
            "nodes": [_lane_node(row, moment) for row in nodes if isinstance(row, dict)],
        }

    async def consume_oracle_mesh_dispatch(
        self, *, dispatch_id: str, nonce: str, node_ref: str | None = None
    ) -> dict[str, Any] | None:
        """#4139 — accept one result submission for one dispatch, atomically.

        Two clearly separated paths:

        * **First submission.** A conditional ``pending -> received`` update
          is the single-winner gate. Only the request whose update actually
          changed the row is accepted; every concurrent loser updates nothing
          and receives ``None`` (409), so a duplicate delivery can never look
          like the winner.
        * **Retry after a transient conversation-store failure.** A prior
          attempt parked the row in ``store_failed`` with its claim intact.
          That state is not a race — the winner already finished — so the same
          nonce is accepted again as ``claim="retry"``. The append itself is
          idempotent, so a retry can never add a second message, and the PC
          file is never read again.

        Anything else — unknown dispatch, expired claim, foreign nonce,
        already ``done``/``failed`` — is refused.

        When the executor names the PC it claimed (``node_ref``), it must be the
        row's own target. A result produced on another PC is never attached to
        this dispatch, even with a valid nonce.
        """
        import hashlib as _hashlib
        import hmac as _hmac

        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        if not isinstance(nonce, str) or not nonce:
            return None
        if node_ref is not None:
            if not isinstance(node_ref, str) or not node_ref:
                raise HistoryError("node_ref must be a bounded reference")
        row = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at, tool_call_ref, COALESCE(user_mode,0) AS user_mode "
            "FROM oracle_mesh_dispatch WHERE dispatch_id=?",
            dispatch_id,
        )
        if row is None:
            return None
        expected = row.get("nonce_sha256")
        if not isinstance(expected, str) or not expected:
            return None
        if node_ref is not None and row.get("node_ref") != node_ref:
            return None
        # Owner decision 2026-10-28: the dispatch TTL does not expire a result.
        # A run whose lease is being extended (#5997 renew) may finish late; the
        # nonce still proves this is the claimed executor, and the claim/lease
        # gate above still decides delivery. Only a foreign or stale nonce is
        # refused here.
        presented = _hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        if not _hmac.compare_digest(presented, expected):
            return None
        state = row.get("state")
        if state == "store_failed":
            # The winner already failed to store; this is its retry. Move the
            # row back to received under a guarded update so the close below
            # stays a single uniform transition.
            written = await self._run(
                "UPDATE oracle_mesh_dispatch SET state=? "
                "WHERE dispatch_id=? AND state=? AND nonce_sha256=?",
                "received", dispatch_id, "store_failed", expected,
            )
            if _changed_rows(written) != 1:
                return None
            return _tagged({**dict(row), "state": "received", "claim": "retry"})
        if state != "pending":
            return None
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET state=? "
            "WHERE dispatch_id=? AND state=? AND nonce_sha256=?",
            "received", dispatch_id, "pending", expected,
        )
        if _changed_rows(written) != 1:
            # A concurrent submission won this dispatch.
            return None
        accepted = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at, tool_call_ref, COALESCE(user_mode,0) AS user_mode "
            "FROM oracle_mesh_dispatch WHERE dispatch_id=?",
            dispatch_id,
        )
        if accepted is None or accepted.get("state") != "received":
            return None
        return _tagged({**dict(accepted), "claim": "first"})

    async def record_oracle_mesh_first_result(
        self, *, dispatch_id: str, content_sha256: str, content_bytes: int,
        termination: str | None = None, exit_code: int | None = None,
    ) -> bool:
        """#4139 — pin the first accepted result fingerprint for one dispatch.

        A resend after a transient store failure must be the *same* result: the
        executor never re-reads the PC file, so the server pins what arrived
        first and compares every retry against it. A mismatch is refused instead
        of appending a second, different body to the same conversation.
        """
        for name, value in (("dispatch_id", dispatch_id),
                            ("content_sha256", content_sha256)):
            if not isinstance(value, str) or not value:
                raise HistoryError(f"{name} is required")
        if isinstance(content_bytes, bool) or not isinstance(content_bytes, int):
            raise HistoryError("content_bytes must be an integer")
        if termination is not None and not isinstance(termination, str):
            raise HistoryError("termination must be a string")
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int)
        ):
            raise HistoryError("exit_code must be an integer or null")
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET result_sha256=?, result_bytes=? "
            "WHERE dispatch_id=? AND result_sha256 IS NULL",
            content_sha256, content_bytes, dispatch_id,
        )
        if _changed_rows(written) != 1:
            pinned = await self._first(
                "SELECT result_sha256, result_bytes FROM oracle_mesh_dispatch "
                "WHERE dispatch_id=?",
                dispatch_id,
            )
            return (
                pinned is not None
                and pinned.get("result_sha256") == content_sha256
                and pinned.get("result_bytes") == content_bytes
            )
        if termination is not None:
            # #5015: the executor-observed termination/exit_code travels with
            # the pinned result so the model lane re-feeds the exact evidence
            # instead of inventing one. The additive 049 columns must exist:
            # a missing-column failure here stays a retryable 503 upstream and
            # never a silent deploy success — apply the 049 gate first.
            await self._run(
                "UPDATE oracle_mesh_dispatch SET termination=?, exit_code=? "
                "WHERE dispatch_id=?",
                termination, exit_code, dispatch_id,
            )
        return True

    async def mark_oracle_mesh_store_failed(self, *, dispatch_id: str) -> bool:
        """#4139 — park a received dispatch so the same result can be resent.

        Only a transient conversation-store failure reaches here. The claim and
        expiry stay intact, the PC file is not read again, and the retry is
        still single-delivery because the append is idempotent.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        await self._run(
            "UPDATE oracle_mesh_dispatch SET state=? "
            "WHERE dispatch_id=? AND state=?",
            "store_failed", dispatch_id, "received",
        )
        parked = await self._first(
            "SELECT state FROM oracle_mesh_dispatch WHERE dispatch_id=?",
            dispatch_id,
        )
        return parked is not None and parked.get("state") == "store_failed"

    async def finish_oracle_mesh_dispatch(
        self, *, dispatch_id: str, outcome: str
    ) -> bool:
        """#4139 — close one received (or retried) dispatch, once.

        A retry submission parks the row back in ``received``, so both the
        first and the retry path close through the same guarded transition.
        """
        if outcome not in ("done", "failed"):
            raise HistoryError("outcome must be done or failed")
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET state=? "
            "WHERE dispatch_id=? AND state=?",
            outcome, dispatch_id, "received",
        )
        return _changed_rows(written) == 1

    async def store_oracle_mesh_original(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str, raw: str, expected_sha256: str, expected_bytes: int,
        verified: Any = None,
    ) -> str:
        """#4139 — keep one over-budget command output in the private R2
        original store under a server-derived key.

        The dispatch row is owner-scoped and its pin (SHA + byte length, set
        before this call) must match the presented bytes: a stored original
        that disagrees with the pin is a corruption signal, not a second
        truth. The key reuses the existing full-context layout
        (conversation + deterministic result id), so no browser-supplied key
        or foreign-account result can address it. Bytes are verified again on
        every read against the same pin.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(raw, str) or not raw:
            raise HistoryError("original text is required")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise HistoryError("expected digest is required")
        row = await self._mesh_dispatch_pin(
            user_id=user_id, dispatch_id=dispatch_id, expected_sha256=expected_sha256,
            expected_bytes=expected_bytes, verified=verified,
        )
        data = raw.encode("utf-8")
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise HistoryError("mesh original bytes do not match the pinned result")
        key = await self._put_full_message(
            conversation_id, message_id, raw, max_bytes=_oracle_mesh_original_max_bytes(row, self.mesh_command_output_max_bytes),
        )
        if key is None:
            # _put_full_message only skips short texts; an over-budget output
            # always exceeds one message, so a skip here means the caller
            # passed the wrong body rather than a stored one.
            raise HistoryError("mesh original was not stored")
        return key

    async def store_oracle_mesh_command_result(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str, raw: str, expected_sha256: str, expected_bytes: int,
        verified: Any = None,
    ) -> str:
        """#5015 — keep one small verified command output for Engine re-feed.

        Same owner/pin checks as :meth:`store_oracle_mesh_original`, but the
        short-text gate of the over-budget path does not apply: a typical
        drive inventory is a few hundred bytes and still needs exact bytes for
        the model lane. Large outputs keep using the over-budget method so the
        existing non-delivery/retry contract for ``output_too_large`` is
        unchanged. Empty bodies are never stored here; the withheld-body notice
        path owns those.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(raw, str) or not raw:
            raise HistoryError("original text is required")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise HistoryError("expected digest is required")
        row = await self._mesh_dispatch_pin(
            user_id=user_id, dispatch_id=dispatch_id, expected_sha256=expected_sha256,
            expected_bytes=expected_bytes, verified=verified,
        )
        data = raw.encode("utf-8")
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise HistoryError("mesh original bytes do not match the pinned result")
        limit = _oracle_mesh_original_max_bytes(row, self.mesh_command_output_max_bytes)
        if limit is not None and len(data) > limit:
            raise HistoryError("mesh original exceeds the bounded storage envelope")
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "put", None)):
            raise HistoryError("private full model-context storage is unavailable")
        import inspect as _inspect
        key = self._context_key(conversation_id, message_id)
        result = bucket.put(key, data, httpMetadata={"contentType": "text/plain; charset=utf-8"})
        if _inspect.isawaitable(result):
            await result
        return key

    async def store_oracle_mesh_original_bytes(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str, raw: bytes, media_type: str,
        expected_sha256: str, expected_bytes: int,
    ) -> str:
        """#4139 — keep one desktop screenshot in the private R2 original store.

        The binary twin of :meth:`store_oracle_mesh_original`: same
        server-derived key layout, same dispatch-pin verification before the
        put and the same pin check on every read. The only blob type this
        lane produces is the composited screenshot JPEG; anything else is
        refused rather than stored under an evidence key.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            raise HistoryError("original bytes are required")
        if media_type != "image/jpeg":
            raise HistoryError("unsupported mesh original media type")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise HistoryError("expected digest is required")
        row = await self._mesh_dispatch_pin(
            user_id=user_id, dispatch_id=dispatch_id, expected_sha256=expected_sha256,
            expected_bytes=expected_bytes, verified=verified,
        )
        data = bytes(raw)
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise HistoryError("mesh original bytes do not match the pinned result")
        if len(data) > ORACLE_MESH_ORIGINAL_MAX_BYTES:
            raise HistoryError("mesh original exceeds the bounded storage envelope")
        if not data.startswith(b"\xff\xd8\xff"):
            raise HistoryError("mesh original is not a JPEG screenshot")
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "put", None)):
            raise HistoryError("private full model-context storage is unavailable")
        key = self._context_key(conversation_id, message_id)
        result = bucket.put(key, data, httpMetadata={"contentType": "image/jpeg"})
        if inspect.isawaitable(result):
            await result
        return key

    async def read_oracle_mesh_original(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str,
    ) -> tuple[bytes, str] | None:
        """#4139 — read one stored command original for its owning account.

        Unknown ids and foreign accounts return None so the route answers
        404 without disclosing which part failed. A pin with no stored
        object, or stored bytes that disagree with the dispatch pin, raises
        instead of serving missing or corrupt bytes.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        row = await self._dispatch(
            "get_oracle_mesh_dispatch_pin", user_id=user_id, dispatch_id=dispatch_id)
        if row is None:
            return None
        pinned_sha = row.get("result_sha256")
        pinned_bytes = row.get("result_bytes")
        if not isinstance(pinned_sha, str) or not pinned_sha:
            return None
        try:
            key = self._context_key(conversation_id, message_id)
        except HistoryError:
            return None
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "get", None)):
            raise HistoryError("private full model-context storage is unavailable")
        try:
            obj = bucket.get(key)
            if inspect.isawaitable(obj):
                obj = await obj
            if obj is None:
                raise HistoryError("mesh original missing from store")
            from .workspace_storage import _read_r2_object_bytes
            payload = await _read_r2_object_bytes(obj)
        except HistoryError:
            raise
        except Exception as exc:
            raise HistoryError("mesh original read failed") from exc
        if len(payload) != pinned_bytes or hashlib.sha256(payload).hexdigest() != pinned_sha:
            raise HistoryError("mesh original does not match the pinned result")
        return payload, pinned_sha

    async def get_oracle_mesh_dispatch_for_owner(
        self, *, user_id: str, dispatch_id: str
    ) -> dict[str, Any] | None:
        """#4139 — one dispatch row for its owning account, or None.

        The retrieval route re-derives the conversation and the result id
        from this row; an unknown id or a foreign account both return None
        so the route answers 404 without disclosing which part failed.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        if not isinstance(dispatch_id, str) or not dispatch_id:
            return None
        # #5015: the 049 termination/exit_code columns are required. A database
        # without them raises here and every caller fails closed (503), so a
        # missing migration can never read as a successful deploy.
        row = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_id, revision_ref, tool_request_ref, "
            "result_sha256, result_bytes, termination, exit_code, state "
            "FROM oracle_mesh_dispatch WHERE dispatch_id=? AND user_id=?",
            dispatch_id, user_id,
        )
        if row is None:
            return None
        return _tagged(row)

