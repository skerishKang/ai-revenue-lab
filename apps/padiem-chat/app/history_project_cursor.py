"""프로젝트 목록 커서 (#7790 R6 첫 구역).

`app/history.py`에서 위치만 옮긴 코덱이다. 동작·응답 형식·쿼리 결과는 변하지
않으며, 기존 경로는 `app/history.py`가 이 이름들을 다시 내보낸다.
"""
from __future__ import annotations

import base64
import binascii
import json
from typing import Any

#: 한 커서 문자열의 길이 상한. 이 상점이 발급한 커서는 훨씬 짧다.
PROJECT_CURSOR_MAX_CHARS = 512


class ProjectCursorError(ValueError):
    """이 상점이 발급하지 않은 프로젝트 목록 위치.

    호출자는 이 예외를 400으로만 옮긴다 — 커서 내용(다른 계정 id 등)은 답에 넣지
    않는다. 계정 조건은 커서와 무관하게 쿼리에 늘 붙으므로, 남의 커서를 들고 와도
    자기 프로젝트만 보인다.
    """


def encode_project_cursor(updated_at: str, project_id: str) -> str:
    """(최근 수정 시각, id) 를 다음 페이지용 불투명 문자열로 만든다."""

    raw = json.dumps(
        {"u": updated_at, "i": project_id}, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_project_cursor(cursor: Any) -> tuple[str, str]:
    """커서를 (최근 수정 시각, id) 로 되돌린다. 아니면 ``ProjectCursorError``."""

    if not isinstance(cursor, str) or not cursor or len(cursor) > PROJECT_CURSOR_MAX_CHARS:
        raise ProjectCursorError("invalid project cursor")
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
    except (UnicodeEncodeError, binascii.Error, ValueError):
        raise ProjectCursorError("invalid project cursor") from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProjectCursorError("invalid project cursor") from None
    if not isinstance(payload, dict) or set(payload) != {"u", "i"}:
        raise ProjectCursorError("invalid project cursor")
    updated_at, project_id = payload.get("u"), payload.get("i")
    if (not isinstance(updated_at, str) or not updated_at or len(updated_at) > 64
            or not isinstance(project_id, str) or not project_id or len(project_id) > 128):
        raise ProjectCursorError("invalid project cursor")
    return updated_at, project_id
