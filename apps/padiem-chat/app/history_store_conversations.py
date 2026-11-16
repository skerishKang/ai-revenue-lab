"""대화·프로젝트 저장·조회·검색 (N구역, #7813 H5-2).

`app/history.py`의 `D1HistoryStore`에서 위치만 옮긴 대화 목록·조회·수정·
삭제·검색, 프로젝트와 대화 산출물 등록·확인이다. 동작·응답 형식·DB 쿼리
결과는 변하지 않으며, 기존 경로는 `app/history.py`가 `D1HistoryStore`를
조합으로 다시 내보낸다.
"""
from __future__ import annotations

from typing import Any

from .history_constants import MAX_HISTORY_TITLE_CHARS, MAX_PROJECTS, MAX_RECENT_CONVERSATIONS, _APPEND_EXCHANGE_SQL, _require_product_scope, strip_pc_scope_marker
from .history_errors import HistoryError, HistoryForbidden, HistoryPinUnavailable
from .history_ids import _chat_id, _message_id, _message_reference, _project_id, validate_conversation_id, validate_project_fields
from .history_pinned import _pinned_column_missing
from .history_project_cursor import decode_project_cursor, encode_project_cursor
from .history_rows import _changed_rows, _project_from_row
from .history_search import MAX_CONVERSATION_SEARCH_RESULTS, MAX_CONVERSATION_SEARCH_SCAN_ROWS, _normalize_search_query, _search_snippet
from .history_store_core import StoreCore
from .history_text import _bounded_text, _now_iso, _title_from_user_text
from .history_types import ProjectProfile
from .workspace_storage import _safe_identifier


class ConversationStore(StoreCore):
    """대화·프로젝트 (N구역)."""

    async def _all_with_pinned(self, sql: str, fallback: str, *values: Any) -> list[dict[str, Any]]:
        """#7175: the pinned projection with a pre-migration-104 fallback.

        A database that has not applied migration 104 still answers the same
        owner/product-scoped read (pinned reported as false), so the sidebar
        list never fails because the schema is one migration behind.
        """
        try:
            return await self._all(sql, *values)
        except Exception as exc:
            if not _pinned_column_missing(exc):
                raise
            return await self._all(fallback, *values)

    async def list_conversations(
        self, user_id: str, *, product_scope: str, limit: int = MAX_RECENT_CONVERSATIONS,
    ) -> list[dict[str, Any]]:
        scope = _require_product_scope(product_scope)
        bounded = max(1, min(int(limit), MAX_RECENT_CONVERSATIONS))
        rows = await self._all_with_pinned(
            "SELECT id, title, project_id, created_at, updated_at, pinned FROM conversations "
            "WHERE user_id=? AND product_scope=? AND deleted_at IS NULL "
            "ORDER BY pinned DESC, updated_at DESC LIMIT ?",
            "SELECT id, title, project_id, created_at, updated_at FROM conversations "
            "WHERE user_id=? AND product_scope=? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?",
            user_id, scope, bounded,
        )
        return [{
            "id": str(row.get("id", "")), "title": str(row.get("title", "")),
            "project_id": str(row.get("project_id")) if row.get("project_id") is not None else None,
            "created_at": str(row.get("created_at", "")), "updated_at": str(row.get("updated_at", "")),
            # #7175: a database without migration 104 lists every conversation
            # as unpinned instead of failing the read.
            "pinned": row.get("pinned") is not None and bool(row.get("pinned")),
        } for row in rows]

    async def search_conversations(
        self, user_id: str, query: str, *, product_scope: str,
        limit: int = MAX_CONVERSATION_SEARCH_RESULTS,
    ) -> list[dict[str, Any]]:
        """Owner-scoped search over the signed-in user's own conversations.

        Matches conversation titles and recent message text. Every value is a
        bound parameter and the query is always a literal substring. Results and
        scanned rows are bounded. Stored conversations are never truncated.

        Membership is `instr`, not `LIKE`. D1 refuses a LIKE pattern longer than
        50 bytes as "too complex", and a 17-character Korean query is already 53
        bytes once wrapped in `%…%` — the store accepts 80 characters. `instr`
        takes an ordinary bound value, so no query length can reach that
        ceiling; the run-result read below uses the same route for the same
        reason. `lower()` on both sides keeps the ASCII case-insensitivity that
        `LIKE` gave, and there is no wildcard left to escape.
        """
        needle = _normalize_search_query(query)
        if not needle:
            return []
        scope = _require_product_scope(product_scope)
        bounded = max(1, min(int(limit), MAX_CONVERSATION_SEARCH_RESULTS))
        rows = await self._all_with_pinned(
            "SELECT c.id, c.title, c.project_id, c.created_at, c.updated_at, c.pinned, "
            "(SELECT m.content FROM messages m WHERE m.conversation_id = c.id "
            " AND instr(lower(m.content), lower(?)) > 0 ORDER BY m.sequence_number ASC LIMIT 1) AS hit "
            "FROM conversations c "
            "WHERE c.user_id=? AND c.product_scope=? AND c.deleted_at IS NULL AND (instr(lower(c.title), lower(?)) > 0 OR EXISTS ("
            "  SELECT 1 FROM (SELECT m.content FROM messages m WHERE m.conversation_id = c.id "
            "  ORDER BY m.sequence_number DESC LIMIT ?) scan WHERE instr(lower(scan.content), lower(?)) > 0)) "
            "ORDER BY c.pinned DESC, c.updated_at DESC LIMIT ?",
            "SELECT c.id, c.title, c.project_id, c.created_at, c.updated_at, "
            "(SELECT m.content FROM messages m WHERE m.conversation_id = c.id "
            " AND instr(lower(m.content), lower(?)) > 0 ORDER BY m.sequence_number ASC LIMIT 1) AS hit "
            "FROM conversations c "
            "WHERE c.user_id=? AND c.product_scope=? AND c.deleted_at IS NULL AND (instr(lower(c.title), lower(?)) > 0 OR EXISTS ("
            "  SELECT 1 FROM (SELECT m.content FROM messages m WHERE m.conversation_id = c.id "
            "  ORDER BY m.sequence_number DESC LIMIT ?) scan WHERE instr(lower(scan.content), lower(?)) > 0)) "
            "ORDER BY c.updated_at DESC LIMIT ?",
            needle, user_id, scope, needle, MAX_CONVERSATION_SEARCH_SCAN_ROWS, needle, bounded,
        )
        return [{
            "id": str(row.get("id", "")),
            "title": str(row.get("title", "")),
            "project_id": str(row.get("project_id")) if row.get("project_id") is not None else None,
            "created_at": str(row.get("created_at", "")),
            "updated_at": str(row.get("updated_at", "")),
            "pinned": row.get("pinned") is not None and bool(row.get("pinned")),
            "snippet": _search_snippet(strip_pc_scope_marker(str(row.get("hit") or "")), query),
        } for row in rows]

    async def list_project_conversations(
        self, user_id: str, project_id: str, *, product_scope: str,
        limit: int = MAX_RECENT_CONVERSATIONS,
    ) -> list[dict[str, Any]]:
        scope = _require_product_scope(product_scope)
        bounded = max(1, min(int(limit), MAX_RECENT_CONVERSATIONS))
        rows = await self._all(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations "
            "WHERE user_id=? AND project_id=? AND product_scope=? AND deleted_at IS NULL "
            "ORDER BY updated_at DESC LIMIT ?",
            user_id, project_id, scope, bounded,
        )
        return [{
            "id": str(row.get("id", "")), "title": str(row.get("title", "")), "project_id": project_id,
            "created_at": str(row.get("created_at", "")), "updated_at": str(row.get("updated_at", "")),
        } for row in rows]

    async def get_conversation(
        self, user_id: str, conversation_id: str, *, product_scope: str,
    ) -> dict[str, Any] | None:
        scope = _require_product_scope(product_scope)
        conv = await self._first(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations "
            "WHERE id=? AND user_id=? AND product_scope=? AND deleted_at IS NULL",
            conversation_id, user_id, scope,
        )
        if not conv:
            return None
        messages = await self._all(
            "SELECT role, content, sequence_number, created_at FROM messages WHERE conversation_id=? ORDER BY sequence_number ASC",
            conversation_id,
        )
        return {
            "id": str(conv.get("id", "")), "title": str(conv.get("title", "")),
            "project_id": str(conv.get("project_id")) if conv.get("project_id") is not None else None,
            "created_at": str(conv.get("created_at", "")), "updated_at": str(conv.get("updated_at", "")),
            "messages": [{"role": str(row.get("role", "")), "content": strip_pc_scope_marker(str(row.get("content", "")))} for row in messages if row.get("role") in {"user", "assistant"}],
        }

    async def update_conversation(
        self, user_id: str, conversation_id: str, *, product_scope: str,
        title: str | None = None, pinned: bool | None = None,
    ) -> dict[str, Any] | None:
        """#7175: rename and/or pin one owner-scoped conversation.

        The owner and product scope are part of the UPDATE predicate, so
        another account's conversation matches zero rows and the route answers
        404 without revealing whether it exists. `updated_at` is deliberately
        untouched: recency is message activity, and a rename must not reorder
        the sidebar by itself.
        """
        scope = _require_product_scope(product_scope)
        if title is None and pinned is None:
            raise HistoryError("conversation update requires a title or a pin")
        assignments: list[str] = []
        values: list[Any] = []
        if title is not None:
            if not isinstance(title, str):
                raise HistoryError("conversation title must be text")
            cleaned = " ".join(title.split())
            if not 1 <= len(cleaned) <= MAX_HISTORY_TITLE_CHARS:
                raise HistoryError("conversation title is empty or too long")
            assignments.append("title=?")
            values.append(cleaned)
        if pinned is not None:
            if not isinstance(pinned, bool):
                raise HistoryError("conversation pin must be a boolean")
            assignments.append("pinned=?")
            values.append(1 if pinned else 0)
        sql = (
            f"UPDATE conversations SET {', '.join(assignments)} "
            "WHERE id=? AND user_id=? AND product_scope=? AND deleted_at IS NULL"
        )
        try:
            result = await self._run(sql, *values, conversation_id, user_id, scope)
        except Exception as exc:
            if pinned is not None and _pinned_column_missing(exc):
                raise HistoryPinUnavailable("conversation pin is not available") from exc
            raise
        if _changed_rows(result) < 1:
            return None
        try:
            row = await self._first(
                "SELECT id, title, project_id, created_at, updated_at, pinned FROM conversations "
                "WHERE id=? AND user_id=? AND product_scope=? AND deleted_at IS NULL",
                conversation_id, user_id, scope,
            )
        except Exception as exc:
            if not _pinned_column_missing(exc):
                raise
            row = await self._first(
                "SELECT id, title, project_id, created_at, updated_at FROM conversations "
                "WHERE id=? AND user_id=? AND product_scope=? AND deleted_at IS NULL",
                conversation_id, user_id, scope,
            )
        if row is None:
            return None
        return {
            "id": str(row.get("id", "")),
            "title": str(row.get("title", "")),
            "project_id": str(row.get("project_id")) if row.get("project_id") is not None else None,
            "created_at": str(row.get("created_at", "")),
            "updated_at": str(row.get("updated_at", "")),
            "pinned": row.get("pinned") is not None and bool(row.get("pinned")),
        }

    async def delete_conversation(
        self, user_id: str, conversation_id: str, *, product_scope: str,
    ) -> bool:
        """#7388: deletion is a marker, not a row delete.

        The conversation leaves every product surface immediately (list, search,
        project, detail, pin, turn append, artifact access), while the row and
        its messages stay for the retention window so an operator can restore it
        server-side. `app.conversation_purge` deletes messages, the row and the
        R2 originals together once the window has passed. No browser API exposes
        a restore.

        The marker is idempotent: deleting an already-marked conversation is
        still `True`, and a retried request never moves the retention deadline.
        """

        scope = _require_product_scope(product_scope)
        owned = await self._first(
            "SELECT id, deleted_at FROM conversations WHERE id=? AND user_id=? AND product_scope=?",
            conversation_id, user_id, scope,
        )
        if not owned:
            return False
        if owned.get("deleted_at") is None:
            await self._run(
                "UPDATE conversations SET deleted_at=? "
                "WHERE id=? AND user_id=? AND product_scope=? AND deleted_at IS NULL",
                _now_iso(), conversation_id, user_id, scope,
            )
        # The R2 originals deliberately outlive the marker: they are part of
        # what the retention window keeps, and the purge pass deletes them with
        # the rows. Every product read above is closed in the meantime.
        return True

    async def list_projects(self, user_id: str) -> list[ProjectProfile]:
        """첫 페이지. 예전 호출자(커서를 모르는 쪽)는 이대로 50개를 받는다."""

        page, _ = await self.list_projects_page(user_id)
        return page

    async def list_projects_page(
        self, user_id: str, *, limit: int = MAX_PROJECTS, cursor: str | None = None,
    ) -> tuple[list[ProjectProfile], str | None]:
        """최근 수정 순 한 페이지와 다음 위치(없으면 None).

        정렬은 지금 목록과 같은 최근 수정 시각 내림차순이고, 같은 시각은 id 내림차순으로
        동점을 끊는다 — 그래야 페이지 경계에서 같은 행이 두 번 오거나 빠지지 않는다.
        계정 조건은 첫 페이지든 이어 받기든 똑같이 쿼리에 들어간다.
        """

        size = MAX_PROJECTS if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 else min(limit, MAX_PROJECTS)
        where = "user_id=?"
        params: list[Any] = [user_id]
        if cursor is not None:
            updated_at, project_id = decode_project_cursor(cursor)
            where += " AND (updated_at < ? OR (updated_at = ? AND id < ?))"
            params.extend([updated_at, updated_at, project_id])
        rows = await self._all(
            "SELECT id, name, instructions, created_at, updated_at FROM projects "
            f"WHERE {where} ORDER BY updated_at DESC, id DESC LIMIT ?",
            *params, size + 1,
        )
        page = rows[:size]
        next_cursor = None
        if len(rows) > size and page:
            last = page[-1]
            next_cursor = encode_project_cursor(str(last["updated_at"]), str(last["id"]))
        return [_project_from_row(row) for row in page], next_cursor

    async def get_project(self, user_id: str, project_id: str) -> ProjectProfile | None:
        row = await self._first(
            "SELECT id, name, instructions, created_at, updated_at FROM projects WHERE id=? AND user_id=?",
            project_id, user_id,
        )
        return _project_from_row(row) if row else None

    async def create_project(self, user_id: str, name: str, instructions: str) -> ProjectProfile:
        clean_name, clean_instructions = validate_project_fields(name, instructions)
        pid = _project_id()
        now = _now_iso()
        await self._run(
            "INSERT INTO projects (id, user_id, name, instructions, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            pid, user_id, clean_name, clean_instructions, now, now,
        )
        return ProjectProfile(pid, clean_name, clean_instructions, now, now)

    async def update_project(self, user_id: str, project_id: str, name: str, instructions: str) -> ProjectProfile | None:
        current = await self.get_project(user_id, project_id)
        if current is None:
            return None
        clean_name, clean_instructions = validate_project_fields(name, instructions)
        now = _now_iso()
        await self._run(
            "UPDATE projects SET name=?, instructions=?, updated_at=? WHERE id=? AND user_id=?",
            clean_name, clean_instructions, now, project_id, user_id,
        )
        return ProjectProfile(project_id, clean_name, clean_instructions, current.created_at, now)

    async def delete_project(self, user_id: str, project_id: str) -> bool:
        current = await self.get_project(user_id, project_id)
        if current is None:
            return False
        await self._run(
            "DELETE FROM projects WHERE id=? AND user_id=?",
            project_id, user_id,
        )
        return True

    async def append_exchange(self, user_id: str, conversation_id: str | None, user_text: str, assistant_text: str, project_id: str | None = None, *, product_scope: str, assistant_message_id: str | None = None) -> str:
        scope = _require_product_scope(product_scope)
        user_content = _bounded_text(user_text, "user_text")
        assistant_content = _bounded_text(assistant_text, "assistant_text")
        now = _now_iso()
        cid = conversation_id
        creating = cid is None
        if creating:
            if project_id is not None and await self.get_project(user_id, project_id) is None:
                raise HistoryForbidden("project is not owned by current user")
            cid = _chat_id()
        else:
            owned = await self._first(
                "SELECT id, project_id FROM conversations WHERE id=? AND user_id=? AND product_scope=? "
                "AND deleted_at IS NULL",
                cid, user_id, scope,
            )
            if not owned:
                # Another product's conversation is not addressable here, even
                # for its own owner: the scope must match the route's product.
                # The message stays the existing contract text.
                raise HistoryForbidden("conversation is not owned by current user")
            stored_project = str(owned.get("project_id")) if owned.get("project_id") is not None else None
            if stored_project != project_id:
                raise HistoryForbidden("conversation project mismatch")

        # #5015: a model-only run stores its verified answer under a run-scoped
        # message id, so the owner-scoped lookup can correlate the stored
        # completion record with the actual message. The default stays the
        # random id, and an explicit id is never taken from a browser value.
        user_msg_id = _message_id()
        answer_msg_id = (
            _message_reference(assistant_message_id)
            if assistant_message_id is not None else _message_id()
        )
        r2_keys: list[tuple[str, str]] = []
        persisted = False
        try:
            for msg_id, raw in ((user_msg_id, user_text.strip()), (answer_msg_id, assistant_text.strip())):
                key = await self._put_full_message(cid, msg_id, raw)
                if key is not None:
                    r2_keys.append((msg_id, key))
            if creating:
                # Store private full text first; unavailable R2 must not leave
                # a misleading, empty D1 conversation for the first turn.
                await self._run(
                    "INSERT INTO conversations (id, user_id, project_id, title, created_at, updated_at, product_scope) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    cid, user_id, project_id, _title_from_user_text(user_content), now, now, scope,
                )
            # #5226: the whole exchange is one statement, so the user row and the
            # assistant row land together and the two sequence numbers are
            # allocated inside the same write transaction. Two concurrent
            # appends to one conversation therefore cannot collide on
            # `UNIQUE(conversation_id, sequence_number)` and cannot leave a
            # half-written turn behind.
            await self._run(
                _APPEND_EXCHANGE_SQL,
                cid,
                user_msg_id, cid, user_content, now,
                answer_msg_id, cid, assistant_content, now,
            )
            persisted = True
            await self._run("UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?", now, cid, user_id)
            if project_id is not None:
                await self._run("UPDATE projects SET updated_at=? WHERE id=? AND user_id=?", now, project_id, user_id)
        except Exception:
            # The R2 original is removed only when its D1 row never landed. A row
            # that DID land keeps its R2 original, so a stored message never
            # degrades into a preview-only row with a missing full text, and a
            # failed append leaves no orphan R2 object behind.
            # #5015: the run-scoped answer id is deterministic, so a repeated
            # completion event collides on the messages primary key instead of
            # appending the same answer twice. The row of the first record is
            # still there, and its original has to survive that collision.
            if not persisted:
                await self._delete_orphan_full_keys(r2_keys)
                if creating:
                    # A first turn that never landed must not leave an empty
                    # conversation behind.
                    try:
                        # #7388: this row never became a conversation the owner
                        # could see, so it is removed rather than marked. The
                        # messages are deleted explicitly: this connection does
                        # not enforce ON DELETE CASCADE.
                        await self._run(
                            "DELETE FROM messages WHERE conversation_id=?", cid,
                        )
                        await self._run(
                            "DELETE FROM conversations WHERE id=? AND user_id=? AND product_scope=?",
                            cid, user_id, scope,
                        )
                    except Exception:
                        pass
            raise
        return cid

    async def verify_owner_conversation_artifacts(
        self, user_id: str, conversation_id: str,
    ) -> bool:
        """#3929: current D1 conversation ownership, no cached/browser proof."""
        cid = validate_conversation_id(conversation_id)
        if cid is None or not isinstance(user_id, str) or not user_id:
            return False
        row = await self._first(
            "SELECT id FROM conversations WHERE id=? AND user_id=? AND deleted_at IS NULL",
            cid, user_id,
        )
        return isinstance(row, dict) and row.get("id") == cid

    async def register_owner_conversation_artifact(
        self, *, user_id: str, conversation_id: str,
        workspace_ref: str, artifact: Any,
    ) -> bool:
        """Trusted host only: immutable durable record for an *already completed*
        owner/conversation/workspace-bound Claw run. Never called by user JSON.

        The INSERT is an INSERT..SELECT restricted by BOTH owner conversation
        and the completed owner run; no caller-chosen run id can grant a file.
        Existing exact-id rows are not transferable or silently overwritten.
        """
        from kagent.artifact_registration import (
            ArtifactLifecycle, CanonicalArtifactRecord,
        )
        cid = validate_conversation_id(conversation_id)
        scope = _safe_identifier("workspace_ref", workspace_ref)
        if (cid is None or not isinstance(user_id, str) or not user_id
                or not isinstance(artifact, CanonicalArtifactRecord)
                or artifact.lifecycle is not ArtifactLifecycle.DURABLE
                or artifact.durable_location is None
                or artifact.workspace_ref != scope
                or not isinstance(artifact.run_ref, str)
                or artifact.media_type not in (
                    "application/pdf",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                or not artifact.filename.lower().endswith(
                    ".pdf" if artifact.media_type == "application/pdf" else ".xlsx"
                )):
            return False
        if not await self.verify_owner_conversation_artifacts(user_id, cid):
            return False
        run = await self._first(
            "SELECT run_id FROM claw_run_history "
            "WHERE run_id=? AND user_id=? AND conversation_id=? "
            "AND workspace_id=? AND status='completed'",
            artifact.run_ref, user_id, cid, scope,
        )
        if run is None:
            return False
        existing = await self._first(
            "SELECT user_id, conversation_id, workspace_ref, source_run_ref, "
            "filename, media_type, size_bytes, integrity_ref, location_kind, "
            "location_ref FROM claw_conversation_artifact_index WHERE artifact_id=?",
            artifact.artifact_id,
        )
        location = artifact.durable_location
        expected = (
            user_id, cid, scope, artifact.run_ref, artifact.filename,
            artifact.media_type, artifact.size_bytes, artifact.integrity_ref,
            location.location_kind, location.location_ref,
        )
        columns = (
            "user_id", "conversation_id", "workspace_ref", "source_run_ref",
            "filename", "media_type", "size_bytes", "integrity_ref",
            "location_kind", "location_ref",
        )
        if existing is not None:
            return tuple(existing.get(key) for key in columns) == expected
        await self._run(
            "INSERT OR IGNORE INTO claw_conversation_artifact_index "
            "(artifact_id, user_id, conversation_id, workspace_ref, source_run_ref, "
            "filename, media_type, size_bytes, integrity_ref, location_kind, "
            "location_ref, created_at) "
            "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? "
            "FROM conversations c INNER JOIN claw_run_history r "
            "ON r.conversation_id=c.id AND r.user_id=c.user_id "
            "WHERE c.id=? AND c.user_id=? AND c.deleted_at IS NULL AND r.run_id=? "
            "AND r.workspace_id=? AND r.status='completed'",
            artifact.artifact_id, *expected, _now_iso(),
            cid, user_id, artifact.run_ref, scope,
        )
        persisted = await self._first(
            "SELECT user_id, conversation_id, workspace_ref, source_run_ref, "
            "filename, media_type, size_bytes, integrity_ref, location_kind, "
            "location_ref FROM claw_conversation_artifact_index WHERE artifact_id=?",
            artifact.artifact_id,
        )
        return persisted is not None and tuple(
            persisted.get(key) for key in columns
        ) == expected

    async def get_owner_conversation_artifact(
        self, *, user_id: str, conversation_id: str,
        workspace_ref: str, artifact_id: str,
    ) -> dict[str, Any] | None:
        """#3929: single exact durable artifact, tied to current owner and completed run.

        Never use caller-supplied provider IDs. The result is an INTERNAL row;
        public routes must never expose location_ref or raw Drive metadata.
        """
        cid = validate_conversation_id(conversation_id)
        scope = _safe_identifier("workspace_ref", workspace_ref)
        if (cid is None or not isinstance(user_id, str) or not user_id
                or not isinstance(artifact_id, str) or not artifact_id
                or len(artifact_id) > 128):
            raise HistoryError("owner-scoped artifact identity required")
        return await self._first(
            "SELECT a.ordinal, a.artifact_id, a.user_id, a.conversation_id, "
            "a.workspace_ref, a.source_run_ref, a.filename, a.media_type, "
            "a.size_bytes, a.integrity_ref, a.location_kind, a.location_ref "
            "FROM claw_conversation_artifact_index a "
            "JOIN conversations c ON c.id=a.conversation_id AND c.user_id=a.user_id "
            "JOIN claw_run_history r ON r.run_id=a.source_run_ref "
            "AND r.user_id=a.user_id AND r.conversation_id=a.conversation_id "
            "AND r.workspace_id=a.workspace_ref AND r.status='completed' "
            "WHERE a.artifact_id=? AND a.user_id=? AND a.conversation_id=? "
            "AND a.workspace_ref=?",
            artifact_id, user_id, cid, scope,
        )

    async def list_owner_conversation_artifacts(
        self, *, user_id: str, conversation_id: str,
        workspace_ref: str, limit: int = 31,
    ) -> list[dict[str, Any]]:
        """Current owner+conversation+workspace read with live run binding.

        Strictly bounded; never returns provider location to an HTTP caller
        except via the trusted private adapter that strips it.
        """
        cid = validate_conversation_id(conversation_id)
        scope = _safe_identifier("workspace_ref", workspace_ref)
        if (cid is None or not isinstance(user_id, str) or not user_id
                or type(limit) is not int or not 1 <= limit <= 31):
            raise HistoryError("bounded owner/conversation artifact lookup required")
        return await self._all(
            "SELECT a.ordinal, a.artifact_id, a.user_id, a.conversation_id, "
            "a.workspace_ref, a.source_run_ref, a.filename, a.media_type, "
            "a.size_bytes, a.integrity_ref, a.location_kind, a.location_ref "
            "FROM claw_conversation_artifact_index a "
            "JOIN conversations c ON c.id=a.conversation_id AND c.user_id=a.user_id "
            "JOIN claw_run_history r ON r.run_id=a.source_run_ref "
            "AND r.user_id=a.user_id AND r.conversation_id=a.conversation_id "
            "AND r.workspace_id=a.workspace_ref AND r.status='completed' "
            "WHERE a.user_id=? AND a.conversation_id=? AND a.workspace_ref=? "
            "ORDER BY a.ordinal DESC LIMIT ?",
            user_id, cid, scope, limit,
        )
