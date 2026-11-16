"""행 변환·공개 투영 (#7813 H3).

`app/history.py`에서 위치만 옮긴 D1 행 변환과 공개 투영이다. 동작·응답
형식·DB 쿼리 결과는 변하지 않으며, 기존 경로는 `app/history.py`가 이
이름들을 다시 내보낸다.
"""
from __future__ import annotations

from typing import Any

from .history_ids import validate_conversation_id
from .history_types import ProjectProfile, VerifiedDispatch, _VERIFIED_FOR


def _changed_rows(result: Any) -> int:
    """How many rows one ``statement.run()`` actually changed.

    ``meta.changes`` is the D1-sanctioned counter for "rows this statement
    modified". ``rows_written`` is deliberately not used: it also counts index
    writes, so a guarded single-row UPDATE can report more than one and a real
    winner would be misread as a loser. ``0`` is the load-bearing value — a
    conditional write that matched nothing refuses here, which is how a losing
    concurrent writer never inherits someone else's row.
    """
    if result is None:
        return 0
    meta = result.get("meta") if isinstance(result, dict) else getattr(result, "meta", None)
    if meta is None:
        return 0
    changed = meta.get("changes") if isinstance(meta, dict) else getattr(meta, "changes", None)
    if isinstance(changed, bool) or not isinstance(changed, int):
        return 0
    return max(0, changed)


def _batch_returned_row(results: Any, index: int) -> dict[str, Any] | None:
    """Read one ``RETURNING`` row out of a ``db.batch()`` result.

    Mirrors the automation store's reader: ``None`` means the guarded statement
    matched no row, which is how a refused write reports itself. An INSERT that
    was ignored for any reason (duplicate id, ownership scope, constraint) also
    reports no row, so an append is only ever reported as done when it happened.
    """

    if results is None:
        return None
    try:
        if len(results) <= index:
            return None
    except TypeError:
        return None
    result = results[index]
    if isinstance(result, dict):
        rows = result.get("results")
    else:
        rows = getattr(result, "results", None)
    if rows is None:
        if isinstance(result, dict):
            meta = result.get("meta")
        else:
            meta = getattr(result, "meta", None)
        if isinstance(meta, dict):
            written = meta.get("rows_written")
        else:
            written = getattr(meta, "rows_written", None)
        if isinstance(written, int) and written > 0:
            return {"rows_written": written}
        return None
    if not rows:
        return None
    try:
        return _row_to_dict(rows[0])
    except (TypeError, IndexError, KeyError):
        return None


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _rows_from_result(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    rows = getattr(result, "results", None)
    if rows is None and isinstance(result, dict):
        rows = result.get("results")
    if rows is None:
        return []
    out = []
    for row in rows:
        item = _row_to_dict(row)
        if item is not None:
            out.append(item)
    return out


def _project_from_row(row: dict[str, Any]) -> ProjectProfile:
    return ProjectProfile(
        id=str(row.get("id", "")),
        name=str(row.get("name", "")),
        instructions=str(row.get("instructions", "")),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )


def _run_history_session(row: dict[str, Any]) -> dict[str, str] | None:
    """Project the bounded #2829 canonical session reference, when one exists.

    Only the owner conversation id in the exact validated shape is exposed.
    A missing, malformed, or storage-raw candidate projects ``None`` instead
    of fabricating a session — legacy rows persist no reference at all.
    """
    try:
        conversation_id = validate_conversation_id(row.get("conversation_id"))
    except ValueError:
        return None
    if conversation_id is None:
        return None
    return {"conversation_id": conversation_id}


def _run_history_public(row: dict[str, Any]) -> dict[str, Any]:
    document_id = row.get("artifact_document_id")
    artifact = None
    if document_id is not None and str(document_id):
        artifact = {
            "document_id": str(document_id),
            "filename": str(row.get("artifact_filename") or ""),
            "media_type": str(row.get("artifact_media_type") or ""),
        }
    return {
        "run_id": str(row.get("run_id", "")),
        "channel": str(row.get("channel", "")),
        "action": str(row.get("action", "")),
        "title": str(row.get("title", "")),
        "status": str(row.get("status", "")),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
        "result_summary": str(row.get("result_summary")) if row.get("result_summary") is not None else None,
        "artifact": artifact,
        "session": _run_history_session(row),
    }


def _tagged(row: Any) -> "VerifiedDispatch":
    """Mark a row an owner-scoped read produced with the owner it names.

    Only the store wraps, so a dict that arrives from anywhere else is not a handle and
    falls back to the authoritative lookup.
    """

    marked = VerifiedDispatch(row)
    marked[_VERIFIED_FOR] = str(row.get("user_id") or "")
    return marked
