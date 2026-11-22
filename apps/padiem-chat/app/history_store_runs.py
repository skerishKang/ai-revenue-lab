"""실행 기록 첫 묶음 (#7813 H6-1).

`app/history.py`의 `D1HistoryStore`에서 위치만 옮긴 실행 기록(Claw·채팅 스트림·
PC 확인·명령 결과 조회) 메서드다. 동작·응답 형식·DB 쿼리 결과는 변하지 않으며,
기존 경로는 `app/history.py`가 `D1HistoryStore`를 조합으로 다시 내보낸다.
이 모듈은 `history.py`를 모듈 수준에서 import 하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .pc_command_confirmation import STATUS_AWAITING_CONFIRMATION, STATUS_EXPIRED
from .workspace_storage import _safe_identifier
from .history_constants import (
    MAX_CLAW_RUNS,
    MAX_HISTORY_TITLE_CHARS,
    PC_CONFIRMATION_CARD_ACTIONS,
    PC_SCOPE_NOTICE_LABELS,
    PRODUCT_SCOPE_CHAT,
    _APPEND_USER_MESSAGE_SQL,
    _require_product_scope,
    pc_scope_notice,
)
from .history_errors import HistoryContextIncomplete, HistoryError, HistoryForbidden
from .history_ids import (
    MODEL_ONLY_RUN_ACTION,
    _chat_id,
    _message_id,
    _message_reference,
    _run_history_id,
    general_answer_message_id,
    validate_chat_pc_run_id,
    validate_conversation_id,
)
from .history_rows import _changed_rows, _run_history_public
from .history_run_summary import MAX_RUN_RESULT_SUMMARY_CHARS
from .history_text import (
    _bounded_text,
    _confirmation_card_cutoff,
    _expire_stale_confirmation_cards_rule,
    _is_bounded_preview,
    _iso,
    _now_iso,
    _title_from_user_text,
)
from .history_store_core import StoreCore


class RunStore(StoreCore):
    """실행 기록 (O구역 첫 묶음)."""

    async def record_txt_pending_run(
        self, *, user_id: str, run_id: str, workspace_id: str,
        user_text: str, conversation_id: str | None, action: str = "txt_read",
        status: str = "pending",
    ) -> str:
        """Stage a real owner conversation + pending local run, never an answer.

        The verified Broker result alone is allowed to insert the assistant
        message later. This uses the existing conversation/messages/run tables.

        #7566: a PC command confirmation card is staged as ``waiting_approval``
        so it can never be mistaken for a command that is already running.
        """
        if not isinstance(action, str) or action not in {
            "txt_read", "pc_browser_query", "desktop_task", "pc_command",
            "desktop_type",
        }:
            raise HistoryError("unsupported pending PC action")
        # #7561: the typed-value card waits for the owner the same way.
        if status != "pending" and not (
            status == "waiting_approval" and action in PC_CONFIRMATION_CARD_ACTIONS
        ):
            raise HistoryError("unsupported pending PC run status")
        # #7603: staging the next card is one of the two moments an old, never
        # answered card is retired. The read paths do the same before listing.
        if status == STATUS_AWAITING_CONFIRMATION:
            await self.expire_stale_confirmation_cards(user_id)
        workspace = _safe_identifier("workspace_id", workspace_id)
        content = _bounded_text(user_text, "user_text")
        cid = validate_conversation_id(conversation_id)
        creating = cid is None
        project_id = None
        if creating:
            cid = _chat_id()
        else:
            owned = await self._first(
                "SELECT id,project_id FROM conversations WHERE id=? AND user_id=? AND product_scope=? "
                "AND deleted_at IS NULL",
                cid, user_id, PRODUCT_SCOPE_CHAT,
            )
            if not owned:
                raise HistoryForbidden("conversation is not owned by current user")
            project_id = owned.get("project_id")
        now = _now_iso()
        msg_id = _message_id()
        key = await self._put_full_message(cid, msg_id, user_text.strip())
        persisted = False
        try:
            if creating:
                await self._run(
                    "INSERT INTO conversations (id,user_id,project_id,title,created_at,updated_at,product_scope) "
                    "VALUES (?,?,NULL,?,?,?,?)",
                    cid, user_id, _title_from_user_text(content), now, now, PRODUCT_SCOPE_CHAT,
                )
            # #5226: the same atomic sequence rule as a Chat exchange — the
            # turn number is allocated inside the write that stores the turn.
            await self._run(
                _APPEND_USER_MESSAGE_SQL,
                cid,
                msg_id, cid, content, now,
            )
            persisted = True
            await self.record_claw_run(
                user_id=user_id, run_id=run_id, channel="web",
                action=action, title=("Claw: " + content)[:MAX_HISTORY_TITLE_CHARS],
                status=status, conversation_id=cid, workspace_id=workspace,
            )
            await self._run(
                "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                now, cid, user_id,
            )
        except Exception:
            # Only a turn that never landed may lose its R2 original.
            if not persisted and key is not None:
                await self._delete_full_keys([key])
            raise
        return cid

    async def create_web_xlsx_p01_run(
        self, *, user_id: str, workspace_id: str, filename: str,
        product_scope: str,
    ) -> str:
        """Create a real owner-bound conversation/run for web file approval.

        This is a metadata-only waiting workflow: no fake assistant message,
        model call, file read, or caller-supplied execution identity.
        """
        import uuid
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("authenticated owner required")
        scope = _safe_identifier("workspace_id", workspace_id)
        if not isinstance(filename, str) or not filename.lower().endswith(".xlsx"):
            raise HistoryError("XLSX filename required")
        cid = _chat_id()
        run_id = "web_p01_" + uuid.uuid4().hex
        now = _now_iso()
        await self._run(
            "INSERT INTO conversations (id,user_id,project_id,title,created_at,updated_at,product_scope) "
            "VALUES (?,?,NULL,?,?,?,?)",
            cid, user_id, ("웹 XLSX 원본 승인: " + filename)[:80], now, now,
            _require_product_scope(product_scope),
        )
        await self.record_claw_run(
            user_id=user_id, run_id=run_id, channel="web", action="xlsx_p01",
            title=("XLSX 원본 확인: " + filename)[:120], status="running",
            conversation_id=cid, workspace_id=scope,
        )
        return run_id

    async def _chat_stream_turn(self, user_id: str, run_id: str) -> dict | None:
        validate_chat_pc_run_id(run_id)
        return await self._first(
            "SELECT m.conversation_id,m.content FROM messages m "
            "JOIN conversations c ON c.id=m.conversation_id "
            "WHERE m.id=? AND m.role='user' AND c.user_id=? AND c.product_scope=? "
            "AND NOT EXISTS (SELECT 1 FROM messages a WHERE a.id IN (?,?,?))",
            general_answer_message_id(run_id + ":chat-stream-user"), user_id,
            PRODUCT_SCOPE_CHAT, general_answer_message_id(run_id + ":chat-stream-answer"),
            run_id + "_answer", run_id + "_final",
        )

    async def begin_chat_stream_turn(
        self, *, user_id: str, run_id: str, workspace_id: str,
        user_text: str, conversation_id: str | None,
    ) -> str:
        """Persist the real user turn, never a PC run before a tool is selected."""
        if (await self.get_claw_run(user_id, run_id) is not None
                or await self._first("SELECT id FROM messages WHERE id=?",
                    general_answer_message_id(run_id + ":chat-stream-user")) is not None):
            raise HistoryForbidden("Chat stream turn already exists")
        validate_chat_pc_run_id(run_id)
        return await self.record_chat_pc_drive_run(
            user_id=user_id, run_id=run_id, workspace_id=workspace_id,
            user_text=user_text, conversation_id=conversation_id, stage_run=False,
            user_message_id=general_answer_message_id(run_id + ":chat-stream-user"),
        )

    async def read_pc_session_confirmation_turn(self, *, user_id: str, run_id: str) -> str | None:
        """The private, exact staged user turn of an unanswered owner card."""
        validate_chat_pc_run_id(run_id)
        row = await self._first(
            "SELECT m.id,m.content,m.conversation_id FROM messages m "
            "JOIN claw_run_history r ON r.conversation_id=m.conversation_id "
            "JOIN conversations c ON c.id=m.conversation_id AND c.user_id=r.user_id "
            "WHERE r.run_id=? AND r.user_id=? AND m.id=? AND m.role='user' "
            "AND r.action IN ('pc_session_start','pc_session_input') "
            "AND r.status='waiting_approval' AND c.product_scope=? AND c.deleted_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM messages newer WHERE newer.conversation_id=m.conversation_id "
            "AND newer.role='user' AND newer.sequence_number>m.sequence_number)",
            run_id, user_id, general_answer_message_id(run_id + ":chat-stream-user"), PRODUCT_SCOPE_CHAT,
        )
        return await self._read_full_message(row["conversation_id"], row) if row else None

    async def promote_chat_stream_pc_run(
        self, *, user_id: str, run_id: str, workspace_id: str, action: str,
    ) -> dict | None:
        """Called only after a signed Engine tool call revalidates its owner."""
        if action not in ("pc_files_query", "pc_drive_query", "pc_browser_query"):
            raise HistoryForbidden("Invalid PC run action")
        turn = await self._chat_stream_turn(user_id, run_id)
        if turn is None:
            return None
        await self.record_claw_run(
            user_id=user_id, run_id=run_id, channel="web", action=action,
            title=("PC: " + turn["content"])[:MAX_HISTORY_TITLE_CHARS], status="pending",
            conversation_id=turn["conversation_id"], workspace_id=_safe_identifier("workspace_id", workspace_id),
        )
        return await self.get_claw_run(user_id, run_id)

    async def finish_chat_stream_turn(
        self, *, user_id: str, run_id: str, answer: str,
    ) -> str | None:
        """Append one answer to the already stored user turn, without duplication."""
        turn = await self._chat_stream_turn(user_id, run_id)
        if turn is None:
            raise HistoryForbidden("Chat stream turn is not pending")
        cid = turn["conversation_id"]
        run = await self.get_claw_run(user_id, run_id)
        if run is not None:
            # Reuse the existing PC completion invariants and verified summary.
            from .chat_pc_drive import _append_lane_answer
            if not await _append_lane_answer(None, self, uid=user_id, run_id=run_id, content=answer):
                return cid
        else:
            content = _bounded_text(answer, "assistant_text")
            message_id = general_answer_message_id(run_id + ":chat-stream-answer")
            key = await self._put_full_message(cid, message_id, answer.strip())
            try:
                await self._run(
                    _APPEND_USER_MESSAGE_SQL.replace("'user'", "'assistant'"),
                    cid, message_id, cid, content, _now_iso(),
                )
            except Exception:
                if key is not None:
                    await self._delete_orphan_full_keys([(message_id, key)])
                raise
        await self._run("UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                        _now_iso(), cid, user_id)
        return cid

    async def record_chat_pc_drive_run(
        self, *, user_id: str, run_id: str, workspace_id: str,
        user_text: str, conversation_id: str | None,
        action: str = "pc_drive_query",
        title_prefix: str = "PC 드라이브 조회: ",
        stage_run: bool = True, user_message_id: str | None = None,
    ) -> str:
        """Stage a real b62 Chat owner conversation + pending PC tool run.

        Chat-product twin of :meth:`record_txt_pending_run` for the #5015
        model-driven PC lanes: same conversation/user-message/run shape and
        the same PRODUCT_SCOPE_CHAT ownership, with the lane's own action and
        title so a Chat turn never reads as a Claw turn. The verified Mesh
        result alone is allowed to insert the assistant message later.
        """
        if action not in ("pc_drive_query", "pc_files_query", "pc_browser_query", "pc_session", "pc_maintenance"):
            raise HistoryError("unsupported Chat PC action")
        if not isinstance(title_prefix, str) or not title_prefix:
            raise HistoryError("Chat PC title prefix is required")
        workspace = _safe_identifier("workspace_id", workspace_id)
        content = _bounded_text(user_text, "user_text")
        cid = validate_conversation_id(conversation_id)
        creating = cid is None
        project_id = None
        if creating:
            cid = _chat_id()
        else:
            owned = await self._first(
                "SELECT id,project_id FROM conversations WHERE id=? AND user_id=? AND product_scope=? "
                "AND deleted_at IS NULL",
                cid, user_id, PRODUCT_SCOPE_CHAT,
            )
            if not owned:
                raise HistoryForbidden("conversation is not owned by current user")
            project_id = owned.get("project_id")
        now = _now_iso()
        msg_id = _message_reference(user_message_id) if user_message_id is not None else _message_id()
        key = await self._put_full_message(cid, msg_id, user_text.strip())
        persisted = False
        try:
            if creating:
                await self._run(
                    "INSERT INTO conversations (id,user_id,project_id,title,created_at,updated_at,product_scope) "
                    "VALUES (?,?,NULL,?,?,?,?)",
                    cid, user_id, _title_from_user_text(content), now, now, PRODUCT_SCOPE_CHAT,
                )
            # #5226: the same atomic sequence rule as a Chat exchange.
            await self._run(
                _APPEND_USER_MESSAGE_SQL,
                cid,
                msg_id, cid, content, now,
            )
            persisted = True
            if stage_run:
                await self.record_claw_run(
                    user_id=user_id, run_id=run_id, channel="web",
                    action=action, title=(title_prefix + content)[:MAX_HISTORY_TITLE_CHARS],
                    status="pending", conversation_id=cid, workspace_id=workspace,
                )
            await self._run(
                "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                now, cid, user_id,
            )
        except Exception:
            # Only a turn that never landed may lose its R2 original.
            if not persisted and key is not None:
                await self._delete_full_keys([key])
            raise
        return cid

    async def ensure_claw_automation_conversation(
        self, *, user_id: str, rule_id: str, rule_name: str,
    ) -> str:
        """대표 결정(2026-11-07): 예약 자동화 하나는 대화 하나를 소유한다.

        The conversation id is derived deterministically from the rule id, so
        the first terminal projection creates the conversation and every later
        run of the same rule reuses it — no mapping table, no second write
        authority. A rule rename keeps the same conversation on purpose.
        """

        rule_ref = _safe_identifier("rule_id", rule_id)
        digest = hashlib.sha256(
            ("claw-automation-conversation:" + rule_ref).encode("utf-8")
        ).hexdigest()
        conversation_id = validate_conversation_id("chat_" + digest[:32])
        existing = await self.get_conversation(
            user_id, conversation_id, product_scope=PRODUCT_SCOPE_CHAT
        )
        if existing is not None:
            return conversation_id
        now = _now_iso()
        await self._run(
            "INSERT OR IGNORE INTO conversations (id, user_id, project_id, title, created_at, updated_at, product_scope) "
            "VALUES (?, ?, NULL, ?, ?, ?, ?)",
            conversation_id,
            user_id,
            (rule_name or "자동화")[:MAX_HISTORY_TITLE_CHARS],
            now,
            now,
            PRODUCT_SCOPE_CHAT,
        )
        return conversation_id

    async def record_claw_run(
        self,
        user_id: str,
        run_id: str,
        channel: str,
        action: str,
        title: str,
        status: str,
        result_summary: str | None = None,
        artifact_document_id: str | None = None,
        artifact_filename: str | None = None,
        artifact_media_type: str | None = None,
        conversation_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        # #2829 Phase B: defensive shape validation at the store boundary.
        # Owner authority remains with the route-level get_conversation() lookup;
        # this only prevents malformed values from reaching persistence.
        if conversation_id is not None:
            conversation_id = validate_conversation_id(conversation_id)
        # #2833 S2F3A: workspace linkage reuses the canonical safe-id grammar.
        if workspace_id is not None:
            workspace_id = _safe_identifier("workspace_id", workspace_id)
        summary = result_summary[:MAX_RUN_RESULT_SUMMARY_CHARS] if result_summary else None
        now = _now_iso()
        existing = await self._first(
            "SELECT id, created_at, conversation_id, workspace_id FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if existing is not None:
            # #2829 Phase B: run→conversation linkage is immutable once set.
            # existing NULL + new valid id  → backfill allowed
            # existing id A + new id A      → no-op
            # existing id A + new NULL      → preserve A
            # existing id A + new id B      → fail closed (no transfer)
            existing_ref = existing.get("conversation_id")
            incoming_ref = conversation_id
            if existing_ref is not None:
                if incoming_ref is not None and incoming_ref != existing_ref:
                    raise HistoryError(
                        f"claw run {run_id} is already linked to conversation {existing_ref}; "
                        "transfer to a different conversation is not allowed"
                    )
                persisted_ref = existing_ref
            else:
                persisted_ref = incoming_ref
            # #2833 S2F3A: workspace linkage is immutable once set, mirroring the
            # conversation linkage above.
            # existing NULL + incoming workspace -> one-time backfill allowed
            # existing W + same W                -> update allowed
            # existing W + incoming None         -> preserve W (never erase to NULL)
            # existing W_A + incoming W_B        -> fail closed (no transfer)
            existing_workspace = existing.get("workspace_id")
            if existing_workspace is not None:
                if workspace_id is not None and workspace_id != existing_workspace:
                    raise HistoryError(
                        f"claw run {run_id} is already linked to workspace {existing_workspace}; "
                        "transfer to a different workspace is not allowed"
                    )
                persisted_workspace = existing_workspace
            else:
                persisted_workspace = workspace_id
            await self._run(
                "UPDATE claw_run_history SET channel=?, action=?, title=?, status=?, updated_at=?, "
                "result_summary=?, artifact_document_id=?, artifact_filename=?, artifact_media_type=?, "
                "conversation_id=?, workspace_id=? "
                "WHERE run_id=? AND user_id=?",
                channel, action, title, status, now,
                summary, artifact_document_id, artifact_filename, artifact_media_type,
                persisted_ref, persisted_workspace,
                run_id, user_id,
            )
            return
        await self._run(
            "INSERT INTO claw_run_history (id, user_id, run_id, channel, action, title, status, created_at, updated_at, result_summary, artifact_document_id, artifact_filename, artifact_media_type, conversation_id, workspace_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _run_history_id(), user_id, run_id, channel, action, title, status, now, now,
            summary, artifact_document_id, artifact_filename, artifact_media_type,
            conversation_id, workspace_id,
        )

    async def list_recent_claw_runs(
        self, user_id: str, limit: int = MAX_CLAW_RUNS, workspace_id: str | None = None
    ) -> list[dict[str, Any]]:
        # #7603: reading the run history retires a card whose window has passed,
        # so an unanswered card can never keep reading as ``waiting_approval``.
        if isinstance(user_id, str) and user_id:
            await self.expire_stale_confirmation_cards(user_id)
        bounded = max(1, min(int(limit), MAX_CLAW_RUNS))
        columns = (
            "SELECT run_id, channel, action, title, status, created_at, updated_at, result_summary, "
            "artifact_document_id, artifact_filename, artifact_media_type, conversation_id "
            "FROM claw_run_history "
        )
        if workspace_id is not None:
            # #2833 S2F3A: the tenant workspace filter is exact. A legacy row with
            # workspace_id IS NULL is never mixed into a tenant workspace result.
            scoped = _safe_identifier("workspace_id", workspace_id)
            rows = await self._all(
                columns + "WHERE user_id=? AND workspace_id=? ORDER BY created_at DESC LIMIT ?",
                user_id, scoped, bounded,
            )
        else:
            # No workspace filter: preserve the legacy user-scoped behaviour.
            rows = await self._all(
                columns + "WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                user_id, bounded,
            )
        return [_run_history_public(row) for row in rows]

    async def update_claw_run_status(
        self,
        user_id: str,
        run_id: str,
        status: str,
        result_summary: str | None = None,
    ) -> bool:
        """Narrow, guarded status-only update of one owner-scoped Claw run row (#2961). (#5015r)

        An owner approve/deny must not rewrite channel, action, title, session or
        workspace linkage, so this touches only ``status`` / ``updated_at`` and
        the bounded result summary. Rows are addressed by owner + run id, so a
        caller can never mutate another owner's run.

        The write is one atomic conditional UPDATE:

        - a row already at ``completed`` can never be overwritten by a later
          failure/cancel settle, and
        - an existing ``result_summary`` is never blanked to NULL by a
          summary-free settle call.

        ``False`` therefore also reports "the guarded write matched nothing",
        e.g. a late settle racing a verified completion.
        """
        if not isinstance(user_id, str) or not user_id:
            return False
        if not isinstance(run_id, str) or not run_id:
            return False
        summary = result_summary[:MAX_RUN_RESULT_SUMMARY_CHARS] if result_summary else None
        result = await self._run(
            "UPDATE claw_run_history SET status=?, updated_at=?, "
            "result_summary=CASE WHEN ? IS NULL THEN result_summary ELSE ? END "
            "WHERE run_id=? AND user_id=? AND status<>'completed' "
            "AND (? <> 'running' OR action NOT IN ('pc_files_query','pc_browser_query') OR status NOT IN ('failed', 'cancelled', 'timed_out'))",
            status, _now_iso(), summary, summary, run_id, user_id, status,
        )
        return _changed_rows(result) > 0

    async def consume_pc_command_confirmation(
        self, user_id: str, run_id: str, action: str = "pc_command", *,
        now: datetime | None = None,
    ) -> bool:
        """#7566 — take one PC command card, exactly once.

        One conditional UPDATE: only a ``pc_command`` row that is still
        ``waiting_approval`` (a card nobody has answered) matches, and it leaves
        that state in the same statement. Two "네" that race each other both
        read the card, but only one of them changes it; the other gets ``False``
        and dispatches nothing. A command that ran straight away was recorded
        as ``pending`` and never matches, so a "네" after it runs nothing.

        Unlike ``update_claw_run_status`` (``status<>'completed'``) the
        condition names the one state it consumes, so an already consumed card
        (``cancelled``) is not consumed again.

        #7561: ``action`` names which card is taken. A typed-value card
        (``desktop_type``) is consumed by the same statement; a card of one
        kind is never consumed as the other.

        #7603: the same condition also requires the card to be younger than the
        confirm window. A selection made just before expiry can therefore not
        consume (and dispatch) after expiry. A stale card is retired to the
        existing terminal ``timed_out`` status by a second conditional UPDATE,
        so even a direct consumer leaves no ``waiting_approval`` row behind.
        """
        if not isinstance(user_id, str) or not user_id:
            return False
        if not isinstance(run_id, str) or not run_id:
            return False
        if action not in PC_CONFIRMATION_CARD_ACTIONS:
            return False
        moment = now if now is not None else datetime.now(timezone.utc)
        cutoff = _confirmation_card_cutoff(moment)
        result = await self._run(
            "UPDATE claw_run_history SET status='cancelled', updated_at=? "
            "WHERE run_id=? AND user_id=? AND action=? "
            "AND status=? AND created_at>=?",
            _iso(moment), run_id, user_id, action, STATUS_AWAITING_CONFIRMATION,
            cutoff,
        )
        if _changed_rows(result) == 1:
            return True
        # Not consumable. If it was a card that outlived the window, retire it
        # now; a racing winner, another owner or a non-card row matches nothing.
        await self._run(
            "UPDATE claw_run_history SET status=?, updated_at=? "
            "WHERE run_id=? AND user_id=? AND action=? "
            "AND status=? AND created_at<?",
            STATUS_EXPIRED, _iso(moment), run_id, user_id, action,
            STATUS_AWAITING_CONFIRMATION, cutoff,
        )
        return False

    async def expire_stale_confirmation_cards(
        self, user_id: str, *, now: datetime | None = None,
    ) -> int:
        """#7603 — retire unanswered confirmation cards past their window.

        One conditional UPDATE. Two concurrent readers may both run it; only
        the first changes a given row, and the ``waiting_approval`` condition
        keeps a card that was answered in between untouched. The statement is
        the one builder shared with the daily purge's all-owners pass (#7631);
        this read path keeps narrowing it to the calling owner and stays
        unbounded.
        """
        if not isinstance(user_id, str) or not user_id:
            return 0
        moment = now if now is not None else datetime.now(timezone.utc)
        condition, rule_values = _expire_stale_confirmation_cards_rule(moment)
        result = await self._run(
            "UPDATE claw_run_history SET status=?, updated_at=? "
            f"WHERE user_id=? AND {condition}",
            STATUS_EXPIRED, _iso(moment), user_id, *rule_values,
        )
        return _changed_rows(result)

    async def get_pc_run_scope(self, *, user_id: str, run_id: str) -> dict[str, Any] | None:
        """The immutable scope notice in the run's existing conversation."""
        row = await self._first(
            "SELECT m.content FROM messages m JOIN claw_run_history r "
            "ON r.conversation_id=m.conversation_id "
            "JOIN conversations c ON c.id=m.conversation_id AND c.user_id=r.user_id "
            "WHERE r.user_id=? AND r.run_id=? AND m.id=?",
            user_id, run_id, run_id + "_scope",
        )
        if row is None:
            return None
        try:
            content = row["content"]
            claim = json.loads(content.split("\n<!--pc_scope:", 1)[1].removesuffix("-->"))
            if not isinstance(claim, dict):
                raise ValueError("invalid scope")
            return claim
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HistoryError("stored PC scope is invalid") from exc

    async def get_pc_run_scope_notice(self, *, user_id: str, run_id: str) -> str | None:
        """The stored scope's notice wording, or None when nothing is pinned.

        An absent, foreign or malformed record is simply "no notice": the
        live answer and the recovery GET keep their existing shape.
        """
        try:
            claim = await self.get_pc_run_scope(user_id=user_id, run_id=run_id)
        except Exception:
            return None
        return pc_scope_notice(claim)

    async def pin_pc_run_scope(self, *, user_id: str, run_id: str, claim: dict[str, Any]) -> None:
        """Record before dispatch, once per owner/run; never alter its terminal."""
        owned = await self.get_claw_run(user_id, run_id)
        if not isinstance(owned, dict) or not owned.get("conversation_id"):
            raise HistoryForbidden("PC run is not owned")
        message_id = run_id + "_scope"
        if len(message_id) > 128:
            raise HistoryError("PC scope message id is invalid")
        encoded = json.dumps(claim, sort_keys=True, separators=(",", ":"))
        if claim.get("admitted") not in PC_SCOPE_NOTICE_LABELS or len(encoded) > 1024:
            raise HistoryError("PC scope claim is invalid")
        content = PC_SCOPE_NOTICE_LABELS[claim["admitted"]] + "\n<!--pc_scope:" + encoded + "-->"
        cid = owned["conversation_id"]
        # A concurrent conflicting admission loses INSERT OR IGNORE and the
        # read-back comparison refuses it. Existing messages carry the record;
        # no new authority table, migration, or terminal-status write is needed.
        await self._run(
            "INSERT OR IGNORE INTO messages (id,conversation_id,role,content,created_at,sequence_number) "
            "SELECT ?,c.id,'assistant',?,?,COALESCE((SELECT MAX(sequence_number) "
            "FROM messages WHERE conversation_id=c.id),0)+1 FROM conversations c "
            "JOIN claw_run_history r ON r.conversation_id=c.id AND r.user_id=c.user_id "
            "WHERE c.id=? AND r.user_id=? AND c.deleted_at IS NULL AND r.run_id=?",
            message_id, content, _now_iso(), cid, user_id, run_id,
        )
        if await self.get_pc_run_scope(user_id=user_id, run_id=run_id) != claim:
            raise HistoryForbidden("PC run scope is already fixed")

    async def get_claw_run(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        """#3139 — the owner-scoped origin row for one Claw run.

        The conversation this run returns to is the one already linked on the run
        row. It is read, never supplied: a browser or a device cannot choose which
        conversation receives a Local Runner result.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        return await self._first(
            "SELECT id, run_id, status, result_summary, conversation_id, workspace_id, "
            "updated_at, action FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )

    async def get_claw_run_for_artifact_document(
        self, user_id: str, document_id: str
    ) -> dict[str, Any] | None:
        """#2952 follow-up — the owner row that minted one generated document.

        ``claw_document_metadata`` carries no owner column, so the only existing
        canonical authority binding a document to a product user is the run row
        that recorded ``artifact_document_id``. A read that finds nothing here has
        no verified owner and must fail closed.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(document_id, str) or not document_id:
            raise HistoryError("document_id is required")
        return await self._first(
            "SELECT run_id, artifact_document_id, artifact_filename, artifact_media_type "
            "FROM claw_run_history WHERE artifact_document_id=? AND user_id=?",
            document_id, user_id,
        )

    async def get_claw_run_result_message(
        self, user_id: str, run_id: str, conversation_id: str,
    ) -> str | None:
        """Return only the correlated terminal message, never a later run's text."""
        from .claw_local_task_result_projection import result_message_id
        # Prefer the actual Oracle receipt. Claw may also have a preliminary
        # local correlation under the same run; it is not the completed Mesh
        # command/revision that minted the persisted assistant message.
        correlation = await self._dispatch(
            "get_oracle_mesh_run_correlation", user_id=user_id, run_id=run_id)
        if not isinstance(correlation, dict):
            correlation = await self.get_local_task_correlation(user_id, run_id)
        if not isinstance(correlation, dict):
            return None
        command_id = correlation.get("command_id")
        revision_ref = correlation.get("revision_ref")
        if not isinstance(command_id, str) or not isinstance(revision_ref, str):
            return None
        message_id = result_message_id(
            conversation_id=conversation_id,
            command_id=command_id, revision_ref=revision_ref,
        )
        # D1 rejects a LIKE pattern longer than 50 characters as "too complex",
        # and this exact id plus the split-part marker is already 51. A prefix
        # comparison keeps the same membership without the LIKE pattern.
        part_prefix = message_id + "_p"
        # #5015: a run that held more than one PC tool call answers with its
        # own final answer beside the command outputs, so the final message of
        # such a run is read too. The id belongs to that lane alone, so a
        # single-command run reads exactly what it read before.
        final_id = run_id + "_final"
        rows = await self._all(
            "SELECT m.id, m.content FROM messages m JOIN conversations c "
            "ON c.id=m.conversation_id WHERE m.role='assistant' "
            "AND m.conversation_id=? AND c.user_id=? AND c.product_scope=? "
            "AND (m.id=? OR substr(m.id, 1, ?)=? OR m.id=?) "
            "ORDER BY m.sequence_number LIMIT 16",
            conversation_id, user_id, PRODUCT_SCOPE_CHAT,
            message_id, len(part_prefix), part_prefix, final_id,
        )
        return "\n".join(row["content"] for row in rows) if rows else None

    async def get_claw_run_result(
        self, user_id: str, run_id: str, conversation_id: str,
    ) -> dict[str, str] | None:
        """The owner's completed run result, correlated to the actual message.

        Two proven sources, and never a summary substitution:

        * a completed Mesh / Local Runner command run resolves through the
          dispatch correlation to the assistant message that holds the verified
          PC command result (``pc_command_result``);
        * a completed model-only run resolves through the run-scoped answer
          message the general lane stored for exactly that run
          (``model_reply``).

        Both branches are bounded by the owner's own run row, its conversation
        and the message row itself, so a later turn's text can never be
        returned for an older run. An unverified run returns ``None`` so the
        caller keeps its truthful state instead of claiming a success.

        A model reply is only ever returned for a run the server itself
        recorded as a model-only execution. A run with a PC execution
        correlation keeps its existing unavailable state when its own verified
        result is missing, and a run whose recorded action is not the
        model-only action is never answered from a model reply.

        A model reply is the run's *actual* stored answer: a long answer is
        kept as a bounded D1 preview plus the private original, so the
        original is restored before it is returned. The bounded preview is
        never presented as the answer.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        correlation = await self._dispatch(
            "get_oracle_mesh_run_correlation", user_id=user_id, run_id=run_id)
        if not isinstance(correlation, dict):
            # #5015: the legacy local-runner correlation table comes from a
            # source migration that a deployment may never have applied. The
            # Mesh dispatch row above is the authority for a PC execution, so
            # an unavailable legacy table can only mean "this deployment holds
            # no local-runner correlation" - it must never turn a model-only
            # run into an unavailable result. A PC run stays unavailable
            # through its own action record instead.
            try:
                correlation = await self.get_local_task_correlation(user_id, run_id)
            except Exception:
                correlation = None
        pc_correlated = (
            isinstance(correlation, dict)
            and isinstance(correlation.get("command_id"), str)
            and isinstance(correlation.get("revision_ref"), str)
        )
        if pc_correlated:
            # #5015: a PC execution run keeps its own verified-result contract.
            # The correlation may point at a dispatch whose message is stored
            # under the dispatch identity, so the established lookup is reused
            # unchanged. A PC run without its own verified result keeps the
            # truthful unavailable state; it is never answered from a model
            # reply.
            answer = await self.get_claw_run_result_message(
                user_id, run_id, conversation_id
            )
            if isinstance(answer, str) and answer:
                return {"answer": answer, "answer_source": "pc_command_result"}
            return None
        run_row = await self._first(
            "SELECT id, action, status, conversation_id FROM claw_run_history "
            "WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if not isinstance(run_row, dict):
            return None
        # Only a run the store itself recorded as a completed model-only
        # execution may answer with a model reply. A PC, desktop or staged run
        # keeps its own action and is never answered from one.
        if run_row.get("action") != MODEL_ONLY_RUN_ACTION:
            return None
        # A run that the store did not record as completed stays unverified.
        if run_row.get("status") != "completed":
            return None
        if run_row.get("conversation_id") != conversation_id:
            return None
        message_id = general_answer_message_id(run_id)
        rows = await self._all(
            "SELECT m.id, m.content FROM messages m JOIN conversations c "
            "ON c.id=m.conversation_id WHERE m.id=? AND m.role='assistant' "
            "AND m.conversation_id=? AND c.user_id=? AND c.product_scope=? "
            "ORDER BY m.sequence_number LIMIT 16",
            message_id, conversation_id, user_id, PRODUCT_SCOPE_CHAT,
        )
        if not rows:
            return None
        # #5015: a long model answer is stored as a bounded D1 preview plus the
        # private R2 original, so the D1 row is NOT the answer. The stored
        # original is restored through the same authority the model-context
        # read uses, inside the owner / run / conversation / assistant-message
        # scope the query above already proved. A row whose original is
        # unavailable stays unverified instead of answering with a truncated
        # preview body.
        contents: list[str] = []
        for row in rows:
            content = str(row.get("content", ""))
            if _is_bounded_preview(content):
                try:
                    content = await self._read_full_message(conversation_id, row)
                except HistoryContextIncomplete:
                    return None
            contents.append(content)
        answer = "\n".join(contents)
        if not answer:
            return None
        return {
            "answer": answer,
            "answer_source": "model_reply",
        }
