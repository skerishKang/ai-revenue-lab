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

class D1HistoryStore(RunStore, ConversationStore, AccountStore, ApprovalHandoffStore):
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

    async def append_command_result(
        self,
        *,
        user_id: str,
        run_id: str,
        message_id: str,
        command_id: str,
        summary: str,
        content: str,
        status: str,
        preserve_edges: bool = False,
    ) -> bool:
        """#5015 — append one bounded per-command result of a multi-tool-call run.

        A PC tool-call run stores every command it executed, correlated by the
        dispatch's existing ``command_id``. The command's own terminal record
        stays the dispatch row (state/termination/exit_code/result digest) and
        its message row; the run row carries only the aggregate. Individual
        command completion is therefore distinct from overall work completion,
        which only the run's owner may seal through :meth:`seal_run_terminal`.

        No new result store is introduced: the per-command projection is the
        message row the caller already derives from the command identity, and
        the aggregate lives on the existing run row.

        Same structural guarantees as :meth:`append_local_task_result`, scoped
        to the command rather than the run:

        * **Exactly once per command.** The message id is derived by the caller
          from the command identity and the insert is ``INSERT OR IGNORE``
          against the ``messages.id`` primary key, so a repeat append is a
          no-op rather than a second row.
        * **Per-command terminal immutability.** A command that already carries
          a different terminal outcome is refused before any statement is
          issued, so one command can never be rewritten by another outcome.
        * **Aggregate truthfulness.** A command result never seals the run:
          a completed command leaves the run ``running`` and a failed command
          leaves it ``failed``, so the overall completion stays the run
          owner's decision.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        if not isinstance(message_id, str) or not message_id or len(message_id) > 128:
            raise HistoryError("message_id must be a bounded safe reference")
        if not isinstance(command_id, str) or not command_id or len(command_id) > 128:
            raise HistoryError("command_id must be a bounded safe reference")
        if status not in ("completed", "failed"):
            raise HistoryError("command result status must be completed or failed")
        body = _bounded_text(content, "local_task_result", preserve_edges=preserve_edges)
        if len(body) > MAX_HISTORY_MESSAGE_CHARS:
            raise HistoryError("local_task_result is not bounded")
        owned = await self._first(
            "SELECT id, conversation_id, result_summary, status FROM claw_run_history "
            "WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            raise HistoryForbidden("claw run is not owned by current user")
        conversation_id = owned.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise HistoryError("claw run has no originating conversation")
        # The command scope must name a command this owner dispatched inside
        # this run: a result can never be attached to a command of another run
        # or of another owner.
        dispatched = await self._dispatch(
            "get_oracle_mesh_run_command", user_id=user_id, run_id=run_id,
            command_id=command_id)
        if dispatched is None:
            raise HistoryError("claw run command is not dispatched for this run")
        bounded_summary = summary[:MAX_RUN_RESULT_SUMMARY_CHARS]
        already = await self._first(
            "SELECT id, content FROM messages WHERE id=? AND conversation_id=?",
            message_id, conversation_id,
        )
        if already is not None:
            # The command's projection is already durable. The identical result
            # is inert; a different outcome for the same command is refused, so
            # one command can never carry two contradictory results.
            if str(already.get("content") or "") != body:
                raise HistoryError(
                    "claw run command already carries a different terminal result"
                )
            return _refused(APPEND_REASON_SAME_MESSAGE)
        now = _now_iso()
        aggregate_status = "failed" if status == "failed" else "running"
        aggregate_summary = _merge_run_result_summaries(
            owned.get("result_summary"), bounded_summary,
        )
        statements = [
            # The message insert is scoped to a conversation owned by user_id
            # through the conversations join, so a run pointing at someone
            # else's conversation inserts nothing and discloses nothing.
            self.db.prepare(
                "INSERT OR IGNORE INTO messages (id, conversation_id, sequence_number, role, content, created_at) "
                "SELECT ?, c.id, "
                "(SELECT COALESCE(MAX(sequence_number), -1) + 1 FROM messages WHERE conversation_id = c.id), "
                "'assistant', ?, ? FROM conversations c "
                "JOIN claw_run_history r ON r.id = ? "
                "WHERE c.id = ? AND c.user_id = ? AND c.deleted_at IS NULL"
            ).bind(message_id, body, now, str(owned.get("id")),
                   conversation_id, user_id),
            # The aggregate only moves when the command's own message actually
            # landed, so a refused insert can never leave a run claiming a
            # command result that was never stored. A run that is already
            # completed keeps that terminal: a late command result never
            # reopens it.
            self.db.prepare(
                "UPDATE claw_run_history SET status=CASE WHEN status='failed' THEN status ELSE ? END, updated_at=?, "
                "result_summary=CASE WHEN status='failed' AND result_summary='pc_read_failed' "
                "THEN result_summary ELSE ? END "
                "WHERE id=? AND status != 'completed' "
                "AND EXISTS (SELECT 1 FROM messages WHERE id=? AND conversation_id=?)"
            ).bind(aggregate_status, now, aggregate_summary, str(owned.get("id")),
                   message_id, conversation_id),
        ]
        results = await self.db.batch(statements)
        if _batch_returned_row(results, 1) is None:
            return _refused(APPEND_REASON_ALREADY_COMPLETED)
        await self._run(
            "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
            now, conversation_id, user_id,
        )
        return _stored()

    async def seal_run_terminal(
        self,
        *,
        user_id: str,
        run_id: str,
        message_id: str | None = None,
        summary: str,
        content: str | None = None,
        status: str,
    ) -> bool:
        """#5015 — record the overall completion of a multi-command run.

        Only the run's owner may seal the aggregate, and the seal is refused
        while the run's own commands have not all reached a terminal result or
        while one of them failed. A run can therefore never read as completed
        while a command is pending, and a failed command is never reported as
        an overall success.

        An already-completed run keeps its first terminal (terminal
        immutability). A run that already failed stays failed: a later success
        never upgrades it.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        if status not in ("completed", "failed"):
            raise HistoryError("run terminal status must be completed or failed")
        if message_id is not None and (
            not isinstance(message_id, str) or not message_id or len(message_id) > 128
        ):
            raise HistoryError("message_id must be a bounded safe reference")
        owned = await self._first(
            "SELECT id, conversation_id, result_summary, status FROM claw_run_history "
            "WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            raise HistoryForbidden("claw run is not owned by current user")
        conversation_id = owned.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise HistoryError("claw run has no originating conversation")
        if str(owned.get("status") or "") == "completed":
            # The first terminal of a completed run is never rewritten.
            return False
        if status == "completed":
            if str(owned.get("status") or "") == "failed":
                # A command of this run already failed: the work can never
                # read as an overall success.
                raise HistoryError("claw run carries a failed command")
            open_state = await self._dispatch(
                "get_oracle_mesh_run_open_state", user_id=user_id, run_id=run_id)
            if open_state.get("pending_dispatch_id"):
                raise HistoryError("claw run has commands without a terminal result")
            if open_state.get("failed_dispatch_id"):
                raise HistoryError("claw run carries a failed command")
        now = _now_iso()
        bounded_summary = summary[:MAX_RUN_RESULT_SUMMARY_CHARS]
        statements = [self.db.prepare(
            "UPDATE claw_run_history SET status=?, updated_at=?, "
            "result_summary=CASE WHEN ? = 'pc_read_failed' AND ? = 'failed' THEN ? "
            "WHEN result_summary IS NULL THEN ? ELSE result_summary END "
            "WHERE id=? AND status != 'completed'"
        ).bind(status, now, bounded_summary, status, bounded_summary, bounded_summary, str(owned.get("id")))]
        if message_id is not None and content is not None:
            body = _bounded_text(content, "local_task_result")
            if len(body) > MAX_HISTORY_MESSAGE_CHARS:
                raise HistoryError("local_task_result is not bounded")
            statements.append(self.db.prepare(
                "INSERT OR IGNORE INTO messages (id, conversation_id, sequence_number, role, content, created_at) "
                "SELECT ?, c.id, "
                "(SELECT COALESCE(MAX(sequence_number), -1) + 1 FROM messages WHERE conversation_id = c.id), "
                "'assistant', ?, ? FROM conversations c "
                "JOIN claw_run_history r ON r.id = ? "
                "WHERE c.id = ? AND c.user_id = ? AND c.deleted_at IS NULL"
            ).bind(message_id, body, now, str(owned.get("id")),
                   conversation_id, user_id))
        results = await self.db.batch(statements)
        if _batch_returned_row(results, 0) is None:
            return False
        await self._run(
            "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
            now, conversation_id, user_id,
        )
        return True

    async def append_local_task_result(
        self,
        *,
        user_id: str,
        run_id: str,
        message_id: str,
        summary: str,
        content: str,
        status: str,
        preserve_edges: bool = False,
        command_scope: str | None = None,
    ) -> bool:
        """#3139 — append one bounded Local Runner result to the run's conversation.

        Returns ``True`` when this call is the one that appended the message and
        ``False`` when the identical result was already durable, which is what an
        exact retry, a duplicate observation and a restart reread all produce.

        Two guarantees, both structural:

        * **Exactly once.** The message id is derived by the caller from the
          projection identity, and the insert is ``INSERT OR IGNORE`` against the
          ``messages.id`` primary key, so a repeat append is a no-op rather than
          a second row. The message insert is additionally scoped to a
          conversation owned by ``user_id`` through a ``SELECT`` on
          ``conversations``, so a run pointing at someone else's conversation
          inserts nothing and discloses nothing.
        * **Terminal immutability.** The run row is updated only when its stored
          summary is absent or identical, so a projected run cannot be rewritten
          with a different outcome.

        #5015: a command scope makes this a per-command result of a
        multi-tool-call run. Such a result is stored beside the other commands
        of the same run and never seals the run row; the run's overall
        completion is the run owner's own decision, sealed through
        :meth:`seal_run_terminal`. Without a command scope the single-command
        contract above is unchanged for every other lane.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        if not isinstance(message_id, str) or not message_id or len(message_id) > 128:
            raise HistoryError("message_id must be a bounded safe reference")
        if command_scope is not None:
            if (
                not isinstance(command_scope, str)
                or not command_scope
                or len(command_scope) > 128
            ):
                raise HistoryError("command_scope must be a bounded safe reference")
            return await self.append_command_result(
                user_id=user_id, run_id=run_id, message_id=message_id,
                command_id=command_scope, summary=summary, content=content,
                status=status, preserve_edges=preserve_edges,
            )
        body = _bounded_text(content, "local_task_result", preserve_edges=preserve_edges)
        if len(body) > MAX_HISTORY_MESSAGE_CHARS:
            raise HistoryError("local_task_result is not bounded")
        owned = await self._first(
            "SELECT id, conversation_id, result_summary FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            raise HistoryForbidden("claw run is not owned by current user")
        conversation_id = owned.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise HistoryError("claw run has no originating conversation")
        # A contradictory result must mutate nothing, so the refusal happens
        # before any statement is issued rather than after the batch.
        stored_summary = owned.get("result_summary")
        bounded_summary = summary[:MAX_RUN_RESULT_SUMMARY_CHARS]
        if stored_summary is not None and stored_summary != bounded_summary:
            raise HistoryError("claw run already carries a different terminal result")
        if stored_summary == bounded_summary:
            # The identical terminal result is already durable. Returning here
            # is what makes an exact retry genuinely inert: no run-row update,
            # no message, no conversation timestamp.
            already = await self._first(
                "SELECT id FROM messages WHERE id=? AND conversation_id=?",
                message_id, conversation_id,
            )
            if already is not None:
                return _refused(APPEND_REASON_SUMMARY_SAME)
        now = _now_iso()
        statements = [
            self.db.prepare(
                "UPDATE claw_run_history SET status=?, updated_at=?, result_summary=? "
                "WHERE id=? AND (result_summary IS NULL OR result_summary=?)"
            ).bind(status, now, summary[:MAX_RUN_RESULT_SUMMARY_CHARS], str(owned.get("id")), summary[:MAX_RUN_RESULT_SUMMARY_CHARS]),
            # The message insert carries the SAME guard as the run update, so a
            # second, contradictory outcome cannot append a contradicting
            # message even if a caller hands it a fresh message id.
            self.db.prepare(
                "INSERT OR IGNORE INTO messages (id, conversation_id, sequence_number, role, content, created_at) "
                "SELECT ?, c.id, "
                "(SELECT COALESCE(MAX(sequence_number), -1) + 1 FROM messages WHERE conversation_id = c.id), "
                "'assistant', ?, ? FROM conversations c "
                "JOIN claw_run_history r ON r.id = ? "
                "WHERE c.id = ? AND c.user_id = ? AND c.deleted_at IS NULL "
                "AND (r.result_summary IS NULL OR r.result_summary = ?)"
            ).bind(message_id, body, now, str(owned.get("id")), conversation_id, user_id, bounded_summary),
        ]
        results = await self.db.batch(statements)
        if _batch_returned_row(results, 1) is None:
            # The identical result was already durable: an exact retry touches
            # nothing at all — no message, no timestamp, no state.
            return _refused(APPEND_REASON_SUMMARY_GUARD)
        # The ordering touch runs only when a message actually landed, so a
        # retry can never reorder or restamp the conversation.
        await self._run(
            "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
            now, conversation_id, user_id,
        )
        return _stored()

    async def append_step_result_message(
        self, *, user_id: str, run_id: str, message_id: str, content: str,
    ) -> bool:
        """#6460 — one step's message of a model-driven PC loop.

        A loop step is evidence of what happened on the PC, not the run's
        overall outcome: it lands in the originating conversation and touches
        only the run's ``updated_at``. The run row's terminal stays the
        verified final answer, so an earlier step can neither seal the run nor
        refuse that answer as a contradictory result.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        if not isinstance(message_id, str) or not message_id or len(message_id) > 128:
            raise HistoryError("message_id must be a bounded safe reference")
        body = _bounded_text(content, "local_task_result")
        if len(body) > MAX_HISTORY_MESSAGE_CHARS:
            raise HistoryError("local_task_result is not bounded")
        owned = await self._first(
            "SELECT id, conversation_id FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            raise HistoryForbidden("claw run is not owned by current user")
        conversation_id = owned.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise HistoryError("claw run has no originating conversation")
        already = await self._first(
            "SELECT id, content FROM messages WHERE id=? AND conversation_id=?",
            message_id, conversation_id,
        )
        if already is not None:
            if str(already.get("content") or "") != body:
                raise HistoryError(
                    "claw run step already carries a different result"
                )
            return False
        now = _now_iso()
        statements = [
            self.db.prepare(
                "INSERT OR IGNORE INTO messages (id, conversation_id, sequence_number, role, content, created_at) "
                "SELECT ?, c.id, "
                "(SELECT COALESCE(MAX(sequence_number), -1) + 1 FROM messages WHERE conversation_id = c.id), "
                "'assistant', ?, ? FROM conversations c "
                "WHERE c.id = ? AND c.user_id = ? AND c.deleted_at IS NULL"
            ).bind(message_id, body, now, conversation_id, user_id),
            self.db.prepare(
                "UPDATE claw_run_history SET updated_at=? "
                "WHERE id=? AND user_id=? AND status!='completed'"
            ).bind(now, str(owned.get("id")), user_id),
        ]
        results = await self.db.batch(statements)
        appended = _batch_returned_row(results, 0) is not None
        if not appended:
            return False
        await self._run(
            "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
            now, conversation_id, user_id,
        )
        return True

    async def record_local_task_correlation(
        self,
        *,
        user_id: str,
        run_id: str,
        command_id: str,
        tool_request_ref: str,
        request_id: str,
        revision_ref: str,
        request_fingerprint: str,
        evidence_ref: str | None = None,
    ) -> bool:
        """#3139 — bind one run to the exact command the server obtained for it.

        This is the smallest bounded server-side mapping the return leg needs:
        the canonical correlations a terminal projection must echo are written
        once, here, and never by a browser or a device. A second record for the
        same owner+run+command is a no-op; a *different* one for the same
        owner+run fails closed, because two commands claiming one run is
        precisely the confusion this mapping exists to prevent.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        for name, value in (
            ("command_id", command_id),
            ("tool_request_ref", tool_request_ref),
            ("request_id", request_id),
            ("revision_ref", revision_ref),
            ("request_fingerprint", request_fingerprint),
        ):
            if not isinstance(value, str) or not value or len(value) > 512:
                raise HistoryError(f"{name} must be a bounded reference")
        if evidence_ref is not None and (not isinstance(evidence_ref, str) or len(evidence_ref) > 512):
            raise HistoryError("evidence_ref must be a bounded reference or absent")
        owned = await self._first(
            "SELECT id FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            raise HistoryForbidden("claw run is not owned by current user")
        existing = await self.get_local_task_correlation(user_id, run_id)
        candidate = {
            "command_id": command_id,
            "tool_request_ref": tool_request_ref,
            "request_id": request_id,
            "revision_ref": revision_ref,
            "evidence_ref": evidence_ref,
            "request_fingerprint": request_fingerprint,
        }
        if existing is not None:
            # One correlation per run. An identical rebinding is a no-op; any
            # difference is two commands claiming one run, which is exactly the
            # confusion this mapping prevents.
            same = all(existing.get(name) == value for name, value in candidate.items())
            if same:
                return False
            if (
                existing.get("evidence_ref") is None
                and isinstance(candidate.get("evidence_ref"), str)
                and candidate["evidence_ref"]
                and all(
                    existing.get(name) == value
                    for name, value in candidate.items()
                    if name != "evidence_ref"
                )
            ):
                # #4139: the trigger pre-writes the correlation before Broker
                # admission mints the evidence; the first verified identity
                # afterwards fills exactly that one unknown field. Anything
                # else differing is still two commands claiming one run.
                await self._run(
                    "UPDATE claw_local_task_correlation SET evidence_ref=? "
                    "WHERE user_id=? AND run_id=? AND command_id=? AND evidence_ref IS NULL",
                    candidate["evidence_ref"], user_id, run_id, command_id,
                )
                return True
            raise HistoryError("claw run is already bound to a different command correlation")
        await self._run(
            "INSERT INTO claw_local_task_correlation "
            "(id, user_id, run_id, command_id, tool_request_ref, request_id, revision_ref, evidence_ref, request_fingerprint, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _message_id(), user_id, run_id, command_id, tool_request_ref,
            request_id, revision_ref, evidence_ref, request_fingerprint, _now_iso(),
        )
        return True

    async def get_local_task_correlation(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        """#3139 — the exact command correlation bound to one run, if any."""

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        return await self._first(
            "SELECT command_id, tool_request_ref, request_id, revision_ref, evidence_ref, request_fingerprint "
            "FROM claw_local_task_correlation WHERE user_id=? AND run_id=?",
            user_id, run_id,
        )

    async def create_oracle_mesh_dispatch(
        self,
        *,
        user_id: str,
        run_id: str,
        command_id: str,
        tool_request_ref: str,
        request_id: str,
        revision_ref: str,
        evidence_ref: str | None,
        request_fingerprint: str,
        account_ref: str,
        workspace_ref: str,
        device_id: str,
        binding_ref: str | None,
        node_ref: str,
        root_ref: str,
        path_relative: str,
        file_path: str,
        expires_at: str,
        kind: str = "read",
        command_text: str | None = None,
        tool_call_ref: str | None = None,
        user_mode: bool = False,
        read_only: bool | None = None,
    ) -> dict[str, Any]:
        """#4139 — stage one Oracle management-host execution for one run.

        The row snapshots the broker-bound correlation when Broker admission
        exists, plus the deployment-verified Mesh target. An identical pending
        row is reused, a terminal (done/failed) row refuses any second
        execution of the *same* correlation, and an expired pending row is
        replaced. Every statement is owner-scoped; cross-owner existence is
        never disclosed.

        ``tool_call_ref`` narrows the correlation key from the legacy one
        dispatch per owner+run to one dispatch per tool call inside that run.
        A bounded multi-tool turn (for example list then read) therefore stages
        a distinct row for each call, while re-staging the exact same call still
        finds its terminal row and refuses a second execution.

        The stored ``tool_call_ref`` (NULL for the legacy lane) is what 063's
        indexes enforce, and it is the database — not this read-then-write —
        that decides a concurrent staging: the loser of an INSERT race re-reads
        the winner's row and returns it only when it is the same payload, never
        when a different call won. The legacy lane is correlated to the
        run-scoped rows only, so a trusted file call staged in the same run is
        never selected, reused or replaced by it; the trusted lane keeps
        correlating on ``tool_request_ref`` so a row written before 063 (which
        has no scope column) is still found and still refuses a replay.

        ``evidence_ref`` and ``binding_ref`` are nullable on purpose. A PC that
        has never completed the native PC offer has no Broker binding and no
        Broker-minted evidence, and this table stores NULL for both rather than
        inventing a reference that would read as one.
        """
        if read_only is not None and type(read_only) is not bool:
            raise HistoryError("read_only must be a boolean or null")
        read_only_flag = None if read_only is None else (1 if read_only else 0)
        fields = {
            "user_id": user_id, "run_id": run_id, "command_id": command_id,
            "tool_request_ref": tool_request_ref, "request_id": request_id,
            "revision_ref": revision_ref, "evidence_ref": evidence_ref,
            "request_fingerprint": request_fingerprint,
            "account_ref": account_ref, "workspace_ref": workspace_ref,
            "device_id": device_id, "binding_ref": binding_ref,
            "node_ref": node_ref, "root_ref": root_ref,
            "path_relative": path_relative, "file_path": file_path,
            "kind": kind, "command_text": command_text,
        }
        if kind not in ("read", "command", "desktop"):
            raise HistoryError("kind must be read, command or desktop")
        if kind in ("command", "desktop"):
            # #4139 terminal lane: the command is the execution target, so it is
            # mandatory and it is ordinary text — Korean, quotes, tabs and
            # several lines. There is no product length rule; the bound is the
            # row it is written into. Only the characters that break the lane
            # are refused: NUL and the other C0 controls except tab and LF
            # (CR is refused because the exit-code sentinel is parsed per line).
            # The desktop lane carries its op in the same field
            # (``desktop:<op>`` plus an optional argument line) under the same
            # text rules, verified again by the executor before the PC acts.
            if not isinstance(command_text, str) or not command_text.strip():
                raise HistoryError("command_text is required for a command dispatch")
            if any(
                ord(ch) < 32 and ch not in "\t\n" for ch in command_text
            ) or "\x7f" in command_text:
                raise HistoryError("command_text carries a control character")
        elif command_text is not None:
            raise HistoryError("command_text is only valid for a command dispatch")
        for name, value in fields.items():
            if value is None:
                if name not in ("evidence_ref", "binding_ref", "command_text"):
                    raise HistoryError(f"{name} must be a bounded reference")
                continue
            if not isinstance(value, str) or not value:
                raise HistoryError(f"{name} must be a bounded reference")
            if name in _MESH_PATH_FIELDS:
                if len(value) > MAX_MESH_PATH_CHARS:
                    raise HistoryError(f"{name} exceeds the Windows path bound")
                if any(ord(ch) < 32 for ch in value):
                    raise HistoryError(f"{name} carries a control character")
                continue
            if name == "command_text":
                continue  # text, not a reference: bounded by the row below
            if len(value) > MAX_MESH_REFERENCE_CHARS:
                raise HistoryError(f"{name} must be a bounded reference")
        row_bytes = sum(
            len(value.encode("utf-8"))
            for value in fields.values() if isinstance(value, str)
        )
        if row_bytes > MAX_MESH_ROW_BYTES:
            raise HistoryError("oracle mesh dispatch row exceeds the storage row bound")
        if not isinstance(expires_at, str) or not expires_at:
            raise HistoryError("expires_at must be a bounded timestamp")
        if tool_call_ref is not None:
            if (
                not isinstance(tool_call_ref, str)
                or not tool_call_ref
                or len(tool_call_ref) > 128
                or any(ord(ch) < 33 or ord(ch) > 126 for ch in tool_call_ref)
            ):
                raise HistoryError(
                    "tool_call_ref must be a bounded safe reference"
                )
            correlation_sql = "user_id=? AND run_id=? AND tool_request_ref=?"
            correlation_params = (user_id, run_id, tool_call_ref)
        else:
            # The legacy single-command lane owns the run-scoped rows and
            # nothing else. Selecting by run alone would read a trusted file
            # call of the same run as if it were the legacy dispatch, and an
            # expired pending file row would then be replaced — losing the
            # file call's own replay protection.
            correlation_sql = "user_id=? AND run_id=? AND tool_call_ref IS NULL"
            correlation_params = (user_id, run_id)
        # The owner is established by the layer that holds the run rows: on D1 that is
        # `claw_run_history`; on the 컴2 queue it is the Worker, whose route already fetched
        # this run for this user and answered 404 before forwarding (see `run_ownership`).
        if not await self._run_is_owned(run_id, user_id):
            raise HistoryForbidden("claw run is not owned by current user")
        existing = await self._first(
            "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
            "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
            "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
            f"state, expires_at, COALESCE(user_mode,0) AS user_mode FROM oracle_mesh_dispatch WHERE {correlation_sql}",
            *correlation_params,
        )
        def same_payload(row: dict[str, Any]) -> bool:
            return all(
                row.get(name) == value
                for name, value in fields.items()
                if name not in ("user_id", "run_id")
            )

        now = _now_iso()
        if existing is not None:
            same = same_payload(existing)
            if same and existing.get("state") == "pending" and existing.get("expires_at", "") > now:
                return dict(existing)
            if same and existing.get("state") in ("done", "failed"):
                raise HistoryError("oracle mesh run already executed")
            if not (existing.get("state") == "pending" and existing.get("expires_at", "") <= now):
                raise HistoryError("oracle mesh run already dispatched")
            if kind in ("command", "desktop") and (
                existing.get("nonce_sha256") is not None
                or existing.get("state") in ("received", "store_failed")
            ):
                # A terminal command — or a desktop input, which also mutates
                # the PC — may ALREADY have run: the row was handed to the
                # executor (a nonce was minted) or its result was received but
                # never stored. Re-staging it would let a restart execute the
                # same action again, so the row is left exactly as it is — an
                # uncertain state, never a silent second execution.
                raise HistoryError("oracle mesh command execution is uncertain")
            await self._run(
                "UPDATE oracle_mesh_dispatch SET command_id=?, tool_request_ref=?, "
                "request_id=?, revision_ref=?, evidence_ref=?, request_fingerprint=?, "
                "account_ref=?, workspace_ref=?, device_id=?, binding_ref=?, node_ref=?, "
                "root_ref=?, path_relative=?, file_path=?, kind=?, command_text=?, "
                "tool_call_ref=?, user_mode=?, read_only=?, nonce_sha256=NULL, "
                "claimed_until=NULL, state=?, expires_at=?, created_at=? WHERE "
                f"{correlation_sql} AND state=? AND expires_at<=?",
                command_id, tool_request_ref, request_id, revision_ref,
                evidence_ref, request_fingerprint, account_ref, workspace_ref,
                device_id, binding_ref, node_ref, root_ref, path_relative,
                file_path, kind, command_text, tool_call_ref, 1 if user_mode else 0,
                read_only_flag, "pending", expires_at, now,
                *correlation_params, "pending", now,
            )
            replaced = await self._first(
                "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
                "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
                "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
                f"state, expires_at, COALESCE(user_mode,0) AS user_mode FROM oracle_mesh_dispatch WHERE {correlation_sql}",
                *correlation_params,
            )
            if replaced is None:
                raise HistoryError("oracle mesh dispatch unavailable")
            return dict(replaced)
        dispatch_id = "dsp_" + uuid.uuid4().hex
        try:
            await self._run(
                "INSERT INTO oracle_mesh_dispatch "
                "(dispatch_id, user_id, run_id, command_id, tool_request_ref, request_id, "
                "revision_ref, evidence_ref, request_fingerprint, account_ref, workspace_ref, "
                "device_id, binding_ref, node_ref, root_ref, path_relative, file_path, "
                "kind, command_text, tool_call_ref, "
                "read_only, nonce_sha256, state, expires_at, created_at, user_mode) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                dispatch_id, user_id, run_id, command_id, tool_request_ref,
                request_id, revision_ref, evidence_ref, request_fingerprint,
                account_ref, workspace_ref, device_id, binding_ref, node_ref,
                root_ref, path_relative, file_path, kind, command_text,
                tool_call_ref, read_only_flag, "pending", expires_at, now,
                1 if user_mode else 0,
            )
        except Exception:
            # 063 makes the database the decider of a concurrent staging: two
            # requests can both read no row and then race to INSERT, and only
            # one of them can win. The loser resolves to the winner's row when
            # it is the exact same payload, and is refused otherwise — it never
            # reports a dispatch it did not stage, and it never retries the
            # INSERT.
            raced = await self._first(
                "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, "
                "revision_ref, evidence_ref, request_fingerprint, account_ref, workspace_ref, "
                "device_id, binding_ref, node_ref, root_ref, path_relative, file_path, "
                "nonce_sha256, state, expires_at, COALESCE(user_mode,0) AS user_mode FROM oracle_mesh_dispatch "
                f"WHERE {correlation_sql}",
                *correlation_params,
            )
            if raced is None:
                raise
            if (
                same_payload(raced)
                and raced.get("state") == "pending"
                and raced.get("expires_at", "") > now
            ):
                return dict(raced)
            if same_payload(raced) and raced.get("state") in ("done", "failed"):
                raise HistoryError("oracle mesh run already executed") from None
            raise HistoryError("oracle mesh run already dispatched") from None
        created = await self._first(
            "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
            "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
            "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
            f"state, expires_at, COALESCE(user_mode,0) AS user_mode FROM oracle_mesh_dispatch WHERE {correlation_sql}",
            *correlation_params,
        )
        if created is None:
            raise HistoryError("oracle mesh dispatch unavailable")
        return dict(created)

    async def oldest_pending_oracle_mesh_dispatch(self) -> dict[str, Any] | None:
        """#4139 — the single oldest claimable Oracle execution, if any.

        Claimable means pending, unexpired and either never handed out or — for a
        ``read`` the owner has not stopped — handed out under a lease that has run
        out (#5895). A run-out lease cannot tell "the response never reached the
        executor" from "the executor ran it and restarted", so a row that changes
        the PC is settled as uncertain first instead of being offered again
        (#7562). The caller (the poll route, under the channel secret) re-claims
        atomically before responding; this read hands out nothing.
        """
        await self.settle_unredeliverable_oracle_mesh_claims()
        now = _now_iso()
        row = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at, tool_call_ref, COALESCE(user_mode,0) AS user_mode "
            "FROM oracle_mesh_dispatch WHERE state=? AND expires_at>? "
            f"AND {ORACLE_MESH_CLAIMABLE_SQL} "
            "ORDER BY created_at ASC LIMIT 1",
            "pending", now, now,
        )
        return dict(row) if row is not None else None

    async def settle_unredeliverable_oracle_mesh_claims(self) -> int:
        """#7562 — end the handed-out rows a run-out lease must not hand out again.

        A ``command`` or ``desktop`` row that already carries a nonce may have run
        on the PC, so it ends as ``failed`` with ``termination='no_reply'``: the PC
        sent no result and whether it ran is not known. That is the same honest
        "uncertain" the re-staging guard keeps, and it is never a second run. A row
        the owner stopped ends as ``cancelled``, the word the owner's own stop
        already uses for a row nobody claimed.

        One conditional statement: a result that lands first (state leaves
        ``pending``) or a renewal that lands first (``claimed_until`` moves on) is
        left alone, and a late submission under the old nonce is then refused by
        the existing ``state='pending'`` gate instead of attaching to a row that
        has been settled. A ``read`` that nobody stopped is not touched: it is
        still re-delivered by the claim below.
        """
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET state='failed', termination=CASE "
            "WHEN COALESCE(termination,'')='cancelled' THEN 'cancelled' ELSE 'no_reply' END "
            f"WHERE {ORACLE_MESH_UNREDELIVERABLE_SQL}",
            _now_iso(),
        )
        return _changed_rows(written)

    async def claim_oracle_mesh_dispatch(
        self, *, dispatch_id: str, nonce_sha256: str
    ) -> bool:
        """#4139 — atomically hand one pending dispatch to the executor.

        The conditional update is the single-claim gate: exactly one poll wins
        one round. #5895 makes the hand-out a lease — the same UPDATE records the
        instant the claim may be handed out again, under the same condition the
        yield uses — so a claim whose response never reached the executor is not
        a permanent loss. Re-claiming rolls the nonce, so a submission still
        carrying the superseded nonce is refused by the existing nonce comparison
        instead of attaching a second result. Returns False when another poll won
        this round, when it expired, or when it left pending meanwhile.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        if not isinstance(nonce_sha256, str) or not nonce_sha256:
            raise HistoryError("nonce_sha256 is required")
        moment = datetime.now(timezone.utc)
        now = _iso(moment)
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET nonce_sha256=?, claimed_until=? "
            "WHERE dispatch_id=? AND state=? AND expires_at>? "
            f"AND {ORACLE_MESH_CLAIMABLE_SQL}",
            nonce_sha256,
            _iso(moment + timedelta(seconds=ORACLE_MESH_CLAIM_LEASE_SECONDS)),
            dispatch_id, "pending", now, now,
        )
        return _changed_rows(written) == 1

    async def renew_oracle_mesh_claim(
        self, *, dispatch_id: str, nonce_sha256: str,
    ) -> str | None:
        """#5997 — extend the lease of a command this executor is still running.

        The condition is the same proof a submission carries: the row is still
        pending and still names this nonce. A renewal whose claim was lost — the
        lease ran out and a later poll re-rolled the nonce — changes nothing and is
        told so, so the executor stops renewing instead of resurrecting a claim the
        lane has already given to somebody else. A running executor that keeps
        renewing is never handed out again; one that dies stops renewing, and the
        lease expiry re-delivers a read or settles anything that changes the PC as
        uncertain (#7562) — a settled row is no longer pending, so it cannot be
        renewed back to life either.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        if not isinstance(nonce_sha256, str) or not nonce_sha256:
            raise HistoryError("nonce_sha256 is required")
        moment = datetime.now(timezone.utc)
        until = _iso(moment + timedelta(seconds=ORACLE_MESH_CLAIM_LEASE_SECONDS))
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET claimed_until=? "
            "WHERE dispatch_id=? AND state=? AND nonce_sha256=?",
            until, dispatch_id, "pending", nonce_sha256,
        )
        return until if _changed_rows(written) == 1 else None

    async def cancel_oracle_mesh_dispatches_for_run(
        self, *, user_id: str, run_id: str,
    ) -> int:
        """#5895 — stop one owner run's PC work, whether it is queued or running.

        ``pending`` with no claim nonce is exactly "no executor has ever seen
        this": stopping it removes the work from the queue, and the existing poll
        — which yields only ``pending`` rows — never hands it out again, so the
        next request the owner makes is claimed straight away instead of sitting
        behind it.

        A row that already carries a nonce is the case the owner is really asking
        about: the PC has the command and the wait has no deadline (#5995 took the
        client ceiling away, and a command the customer's shell never finishes -
        measured on 2026-10-28 - holds every later operation on that PC behind it).
        That row is not failed here. Its ``termination`` is set to ``cancelled``
        and its ``state`` stays ``pending``, so the executor can read the owner's
        stop through the existing channel, end its own child, and land its result
        through the nonce gate it already holds. The row stays submittable on
        purpose: a refused submission would be resent until quarantined, which
        holds the queue longer than the stop the owner asked for.

        The terminal row says ``cancelled`` in the column that already records how
        a command ended, so an owner's own stop is never reported back as a PC
        failure. Both the read and the write are owner-scoped in the WHERE clause,
        so another account's dispatch is not addressable, and each update is one
        conditional statement: a claim that won the race is not cancelled as
        queued work, and a cancel that won is never claimed twice.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        stopped = await self._run(
            "UPDATE oracle_mesh_dispatch SET state=?, termination=? "
            "WHERE user_id=? AND run_id=? AND state=? AND nonce_sha256 IS NULL",
            "failed", "cancelled", user_id, run_id, "pending",
        )
        running = await self._run(
            "UPDATE oracle_mesh_dispatch SET termination=? "
            "WHERE user_id=? AND run_id=? AND state=? AND nonce_sha256 IS NOT NULL",
            "cancelled", user_id, run_id, "pending",
        )
        return _changed_rows(stopped) + _changed_rows(running)

    async def oracle_mesh_dispatch_cancellation(self, *, dispatch_id: str) -> bool:
        """Whether the owner stopped one already-claimed dispatch, for the executor.

        One bounded read on a single column, addressed only by the dispatch id the
        executor already holds. It never claims, never writes, and answers ``False``
        for anything it cannot read: an unreachable store must not look like an
        owner's stop, because ``False`` leaves the running command alone while
        ``True`` ends it.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        row = await self._first(
            "SELECT termination FROM oracle_mesh_dispatch "
            "WHERE dispatch_id=? AND state=?",
            dispatch_id, "pending",
        )
        return isinstance(row, dict) and row.get("termination") == "cancelled"

    async def oracle_mesh_node_live_claims(
        self, *, node_ref: str, except_dispatch_id: str = "",
    ) -> int:
        """How many dispatches are claimed on one PC right now, for the executor.

        #6106 leaves a held console line only when nothing on that PC is working.
        The connector's own map covers the host that runs it, and this row set is
        the only view that also covers the failover partner (#5462): during a
        handover both hosts can hold a claim, and a sweep that ended the partner's
        running command would break standard rule 1 — the work on a PC is never
        cut short.

        The claim is read from the same real columns the lease already uses: a row
        still ``pending``, unexpired, handed out (``nonce_sha256`` set) and not yet
        yielded (``claimed_until`` in the future). Nothing is inferred from text.
        ``except_dispatch_id`` removes the asker's own claim, which is live for
        exactly as long as it is asking, so without it the answer would always be
        "busy" and no wedged line could ever be cleared.

        It never claims, never writes, and raises on an unreadable row like every
        other reader here: the route turns that into the safe answer, which is
        "busy", because the alternative ends a real command on a customer machine.
        """
        if not isinstance(node_ref, str) or not node_ref or len(node_ref) > 256:
            raise HistoryError("node_ref is required")
        if not isinstance(except_dispatch_id, str):
            raise HistoryError("except_dispatch_id must be text")
        now = _now_iso()
        sql = (
            "SELECT COUNT(*) AS n FROM oracle_mesh_dispatch "
            "WHERE node_ref=? AND state=? AND expires_at>? "
            "AND nonce_sha256 IS NOT NULL AND claimed_until>?"
        )
        params: list[Any] = [node_ref, "pending", now, now]
        if except_dispatch_id:
            sql += " AND dispatch_id<>?"
            params.append(except_dispatch_id)
        row = await self._first(sql, *params)
        if not isinstance(row, dict):
            raise HistoryError("oracle mesh claim read unavailable")
        count = row.get("n")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise HistoryError("oracle mesh claim read is not a count")
        return count


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

