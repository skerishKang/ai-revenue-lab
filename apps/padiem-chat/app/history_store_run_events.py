"""명령·로컬 작업 결과 기록과 상관관계 (O구역 나머지, #7813 H6-2).

`app/history.py`의 `D1HistoryStore`에서 위치만 옮긴 실행 기록의 결과 기록·확정·
상관관계 메서드다. 동작·응답 형식·DB 쿼리 결과는 변하지 않으며, 기존 경로는
`app/history.py`가 `D1HistoryStore`를 조합으로 다시 내보낸다.
이 모듈은 `history.py`도 `history_store_runs.py`도 모듈 수준에서 import 하지 않는다.
"""
from __future__ import annotations

from typing import Any

from .history_append_reason import APPEND_REASON_ALREADY_COMPLETED, APPEND_REASON_SAME_MESSAGE, APPEND_REASON_SUMMARY_GUARD, APPEND_REASON_SUMMARY_SAME, refused as _refused, stored as _stored
from .history_constants import MAX_HISTORY_MESSAGE_CHARS
from .history_errors import HistoryError, HistoryForbidden
from .history_ids import _message_id
from .history_rows import _batch_returned_row
from .history_text import _bounded_text, _now_iso
from .history_run_summary import MAX_RUN_RESULT_SUMMARY_CHARS, _merge_run_result_summaries
from .history_store_core import StoreCore


class RunEventStore(StoreCore):
    """명령 결과·로컬 작업 상관관계 (O구역 나머지)."""

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
