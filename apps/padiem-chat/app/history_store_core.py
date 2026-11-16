"""저장 공통·풀 원문 (#7813 H4).

`app/history.py`의 `D1HistoryStore`에서 위치만 옮긴 저장 공통 도우미와
R2 풀 원문이다. 동작·응답 형식·DB 쿼리 결과는 변하지 않으며, 기존 경로는
`app/history.py`가 `D1HistoryStore`를 조합으로 다시 내보낸다.
"""
from __future__ import annotations

import inspect
import re
from typing import Any

from .history_constants import MAX_HISTORY_MESSAGE_CHARS, MAX_MODEL_CONTEXT_BYTES, _require_product_scope, strip_pc_session_confirmation_marker
from .history_errors import HistoryContextIncomplete, HistoryError
from .history_ids import validate_conversation_id
from .history_mesh_original import ORACLE_MESH_ORIGINAL_MAX_BYTES, _MESH_RESULT_MESSAGE_ID_RE
from .history_rows import _row_to_dict, _rows_from_result
from .history_text import _bounded_text, _is_bounded_preview
from .history_types import VerifiedDispatch, _VERIFIED_FOR


class StoreCore:
    """저장 공통·풀 원문 (L구역)."""

    def __init__(self, db: Any, *, full_context_bucket: Any = None,
                 run_ownership: Any = None,
                 mesh_command_output_max_bytes: int | None = ORACLE_MESH_ORIGINAL_MAX_BYTES):
        if db is None:
            raise ValueError("D1 binding is required")
        if mesh_command_output_max_bytes is not None and (
            isinstance(mesh_command_output_max_bytes, bool)
            or not isinstance(mesh_command_output_max_bytes, int)
            or mesh_command_output_max_bytes < 1
        ):
            raise ValueError("mesh_command_output_max_bytes must be positive or None")
        self.db = db
        self.mesh_command_output_max_bytes = mesh_command_output_max_bytes
        # Existing private workspace R2 binding, never an incoming browser key.
        self.full_context_bucket = full_context_bucket
        # Where "does this run belong to this user" is answered. Absent, it is answered
        # from `claw_run_history` — the D1 that owns conversation rows. The 컴2 queue
        # deliberately does not own that table, so it supplies its own answer; without
        # this seam every dispatch creation on the queue died on `no such table` and the
        # PC lane stopped working the moment the switch went live (2026-10-30 14:11).
        self.run_ownership = run_ownership
        # Which store answers dispatch-row reads. It is this store until the queue is
        # wired in as the authority (com2), because that is where `oracle_mesh_dispatch`
        # lives then. Without the seam the conversation read-back re-read a table that is
        # no longer in D1 and answered `run_result_unavailable` (503) to the browser.
        self.dispatch_authority: Any = None

    def set_dispatch_authority(self, authority: Any) -> None:
        if authority is None or authority is self:
            return
        self.dispatch_authority = authority

    async def _dispatch(self, name: str, **arguments: Any) -> Any:
        source = self.dispatch_authority if self.dispatch_authority is not None else self
        return await getattr(source, name)(**arguments)

    @staticmethod

    @staticmethod
    def _verified(row: Any, user_id: str) -> "VerifiedDispatch | None":
        if not isinstance(row, dict):
            return None
        owner = row.get("user_id")
        if owner is not None and owner != user_id:
            return None
        marked = VerifiedDispatch(row)
        marked[_VERIFIED_FOR] = user_id
        return marked

    @staticmethod
    def _context_key(conversation_id: str, message_id: str) -> str:
        try:
            valid_conversation = validate_conversation_id(conversation_id)
        except ValueError:
            raise HistoryError("invalid canonical history object identity")
        if valid_conversation is None or not (
            isinstance(message_id, str)
            and (
                re.fullmatch(r"msg_[0-9a-f]{32}", message_id)
                or _MESH_RESULT_MESSAGE_ID_RE.fullmatch(message_id)
            )
        ):
            raise HistoryError("invalid canonical history object identity")
        return f"claw-model-context/v1/{conversation_id}/{message_id}.utf8"

    async def _put_full_message(self, conversation_id: str, message_id: str, raw: str, *, max_bytes: int | None = MAX_MODEL_CONTEXT_BYTES) -> str | None:
        if len(raw) <= MAX_HISTORY_MESSAGE_CHARS:
            return None
        data = raw.encode("utf-8")
        if max_bytes is not None and len(data) > max_bytes:
            raise HistoryError("full text exceeds the bounded storage envelope")
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "put", None)):
            raise HistoryError("private full model-context storage is unavailable")
        key = self._context_key(conversation_id, message_id)
        result = bucket.put(key, data, httpMetadata={"contentType": "text/plain; charset=utf-8"})
        if inspect.isawaitable(result):
            await result
        return key

    async def _delete_full_keys(self, keys: list[str]) -> None:
        bucket = self.full_context_bucket
        if bucket is None:
            return
        for key in keys:
            try:
                result = bucket.delete(key)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # DB owner/row authority remains independent of R2 cleanup.
                pass

    async def _delete_orphan_full_keys(self, keys: list[tuple[str, str]]) -> None:
        """Remove only the originals whose own message row never landed.

        A row that DID land keeps its R2 original, so a stored message never
        degrades into a preview-only row with a missing full text. The check is
        per message id, because the run-scoped answer id of #5015 is
        deterministic: a repeated completion event collides on the
        ``messages.id`` primary key, and that collision must not strip the
        original of the record that is already stored.

        A row that cannot be read is treated as landed: an original that might
        belong to a stored row is never destroyed on an unproven guess.
        """
        orphan_keys: list[str] = []
        for message_id, key in keys:
            try:
                landed = await self._first("SELECT id FROM messages WHERE id=?", message_id)
            except Exception:
                continue
            if not isinstance(landed, dict):
                orphan_keys.append(key)
        await self._delete_full_keys(orphan_keys)

    async def _read_full_message(self, conversation_id: str, row: dict[str, Any]) -> str:
        preview = str(row.get("content", ""))
        if not _is_bounded_preview(preview):
            return preview
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "get", None)):
            raise HistoryContextIncomplete("full model-context storage is unavailable")
        key = self._context_key(conversation_id, row.get("id"))
        obj = bucket.get(key)
        if inspect.isawaitable(obj):
            obj = await obj
        if obj is None:
            # Never pass a truncated preview to a model as the full history.
            raise HistoryContextIncomplete("saved full model context is unavailable")
        if getattr(obj, "size", 0) > MAX_MODEL_CONTEXT_BYTES:
            raise HistoryError("saved model context exceeds transport envelope")
        from .workspace_storage import _read_r2_object_bytes
        data = await _read_r2_object_bytes(obj)
        if len(data) > MAX_MODEL_CONTEXT_BYTES:
            raise HistoryError("saved model context exceeds transport envelope")
        try:
            full = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HistoryError("saved model context is not UTF-8") from exc
        if _bounded_text(full, "saved_model_context") != preview:
            raise HistoryContextIncomplete("saved model context preview does not match")
        return full

    async def get_conversation_model_context(
        self, user_id: str, conversation_id: str, *, product_scope: str,
    ) -> dict[str, Any] | None:
        """Owner- and product-scoped full messages for model only.

        Browser APIs keep bounded previews; the canonical full-original (R2)
        restoration is only ever reachable through this product-scoped read.

        #4317 perf: this used to call :meth:`get_conversation` first, which
        reads the conversation row *and* the bounded message preview, and then
        read the same message rows again for the full-original bodies. The
        preview read was pure waste on this path, so the conversation row is
        read directly here and the message rows are read once. The returned
        shape is unchanged.
        """
        scope = _require_product_scope(product_scope)
        conv = await self._first(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations "
            "WHERE id=? AND user_id=? AND product_scope=? AND deleted_at IS NULL",
            conversation_id, user_id, scope,
        )
        if not conv:
            return None
        rows = await self._all(
            "SELECT id, role, content, sequence_number FROM messages "
            "WHERE conversation_id=? ORDER BY sequence_number ASC", conversation_id,
        )
        full_messages: list[dict[str, str]] = []
        byte_total = 0
        for row in rows:
            if row.get("role") not in ("user", "assistant"):
                continue
            content = strip_pc_session_confirmation_marker(
                await self._read_full_message(conversation_id, row))
            byte_total += len(content.encode("utf-8"))
            if byte_total > MAX_MODEL_CONTEXT_BYTES:
                raise HistoryError("conversation context exceeds transport envelope")
            full_messages.append({"role": row["role"], "content": content})
        return {
            "id": str(conv.get("id", "")),
            "title": str(conv.get("title", "")),
            "project_id": (
                str(conv.get("project_id"))
                if conv.get("project_id") is not None
                else None
            ),
            "created_at": str(conv.get("created_at", "")),
            "updated_at": str(conv.get("updated_at", "")),
            "messages": full_messages,
        }

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        try:
            statement = self.db.prepare(sql)
            if values:
                statement = statement.bind(*values)
            row = await statement.first()
        except Exception as exc:
            # user_mode column compat (migration 102). 102 배포 완료 후 제거 가능.
            if 'no such column: user_mode' in str(exc) and 'oracle_mesh_dispatch' in sql and 'user_mode' in sql:
                sql2 = sql.replace('COALESCE(user_mode,0) AS user_mode', '0 AS user_mode')
                sql2 = sql2.replace(', COALESCE(user_mode,0) AS user_mode', ', 0 AS user_mode')
                sql2 = sql2.replace(' COALESCE(user_mode, 0) AS user_mode', ' 0 AS user_mode')
                statement = self.db.prepare(sql2)
                if values:
                    statement = statement.bind(*values)
                row = await statement.first()
            else:
                raise
        return _row_to_dict(row)

    async def _run(self, sql: str, *values: Any) -> Any:
        try:
            statement = self.db.prepare(sql)
            if values:
                statement = statement.bind(*values)
            return await statement.run()
        except Exception as exc:
            # user_mode column compat (migration 102). 102 배포 완료 후 제거 가능.
            emsg=str(exc)
            if ('no such column: user_mode' in emsg or 'has no column named user_mode' in emsg) and 'oracle_mesh_dispatch' in sql and 'user_mode' in sql:
                vals = list(values)
                sql2 = sql
                if 'INSERT INTO oracle_mesh_dispatch' in sql and ', created_at, user_mode)' in sql:
                    sql2 = sql.replace(', created_at, user_mode)', ', created_at)')
                    if sql2.count('?') == sql.count('?') - 1 and vals:
                        vals = vals[:-1]
                elif 'UPDATE oracle_mesh_dispatch' in sql and 'tool_call_ref=?, user_mode=?,' in sql:
                    sql2 = sql.replace('tool_call_ref=?, user_mode=?,', 'tool_call_ref=?,')
                    # value order includes tool_call_ref, user_mode before nonce/state in that update
                    # find param positions by rebuilding? easier: reconstruct from known shape not safe; try removing second-to-last in that segment impossible.
                    # Fallback: re-raise only for rare pre-102 update-replace path; reads/inserts are main compatibility need.
                    raise
                else:
                    sql2 = sql.replace(', user_mode=?,', ',').replace(', user_mode,', ',')
                statement = self.db.prepare(sql2)
                if vals:
                    statement = statement.bind(*tuple(vals))
                return await statement.run()
            raise

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        try:
            statement = self.db.prepare(sql)
            if values:
                statement = statement.bind(*values)
            result = await statement.run()
        except Exception as exc:
            # user_mode column compat (migration 102). 102 배포 완료 후 제거 가능.
            if 'no such column: user_mode' in str(exc) and 'oracle_mesh_dispatch' in sql and 'user_mode' in sql:
                sql2 = sql.replace('COALESCE(user_mode,0) AS user_mode', '0 AS user_mode')
                sql2 = sql2.replace(', COALESCE(user_mode,0) AS user_mode', ', 0 AS user_mode')
                sql2 = sql2.replace(' COALESCE(user_mode, 0) AS user_mode', ' 0 AS user_mode')
                statement = self.db.prepare(sql2)
                if values:
                    statement = statement.bind(*values)
                result = await statement.run()
            else:
                raise
        return _rows_from_result(result)
