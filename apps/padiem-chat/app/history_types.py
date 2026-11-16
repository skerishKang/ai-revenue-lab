"""프로필·협약·검증 배포 표시 (#7813 H1).

`app/history.py`에서 위치만 옮긴 프로필, `HistoryStore` 협약과
`VerifiedDispatch`다. 동작·응답 형식·DB 쿼리 결과는 변하지 않으며, 기존
경로는 `app/history.py`가 이 이름들을 다시 내보낸다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .history_search import MAX_CONVERSATION_SEARCH_RESULTS


MAX_RECENT_CONVERSATIONS = 30

# 한 페이지 크기. 전체를 가리는 상한이 아니다 — 더 있으면 응답의 next_cursor 로
# 이어 받는다 (#5882 · #5895-D). 생성은 이 수와 무관하게 계속 허용되고, 51번째부터는
# 목록을 넘겨 보면 그대로 나온다.
MAX_PROJECTS = 50

MAX_CLAW_RUNS = 30


@dataclass(frozen=True, slots=True)
class UserProfile:
    id: str
    email: str
    display_name: str
    picture_url: str

    def public_dict(self) -> dict[str, str]:
        return {"email": self.email, "name": self.display_name, "picture": self.picture_url}


@dataclass(frozen=True, slots=True)
class PasswordCredential:
    user: UserProfile
    username: str
    password_hash: str
    failed_attempts: int
    locked_until: str | None
    # #7551: when this credential row was created. Password change and reset
    # keep it; it changes only when the credential is created again.
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectProfile:
    id: str
    name: str
    instructions: str
    created_at: str
    updated_at: str

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "instructions": self.instructions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class HistoryStore(Protocol):
    async def upsert_google_user(self, subject: str, email: str, name: str, picture: str) -> UserProfile: ...
    async def consume_service_id(self, service_id: str, expires_at: str) -> bool: ...
    async def register_password_user(self, username: str, email: str, name: str, password_hash: str) -> UserProfile: ...
    async def find_password_credential(self, identifier: str) -> PasswordCredential | None: ...
    async def find_password_credential_by_user_id(self, user_id: str) -> PasswordCredential | None: ...
    async def update_password_credential(self, user_id: str, password_hash: str) -> None: ...
    async def record_password_failure(self, user_id: str, failed_attempts: int, locked_until: str | None) -> None: ...
    async def reset_password_failures(self, user_id: str) -> None: ...
    async def get_user(self, user_id: str) -> UserProfile | None: ...
    async def user_row_exists(self, user_id: str) -> bool: ...
    async def list_conversations(self, user_id: str, *, product_scope: str, limit: int = MAX_RECENT_CONVERSATIONS) -> list[dict[str, Any]]: ...
    async def search_conversations(self, user_id: str, query: str, *, product_scope: str, limit: int = MAX_CONVERSATION_SEARCH_RESULTS) -> list[dict[str, Any]]: ...
    async def get_conversation(self, user_id: str, conversation_id: str, *, product_scope: str) -> dict[str, Any] | None: ...
    async def update_conversation(
        self, user_id: str, conversation_id: str, *, product_scope: str,
        title: str | None = None, pinned: bool | None = None,
    ) -> dict[str, Any] | None: ...
    async def delete_conversation(self, user_id: str, conversation_id: str, *, product_scope: str) -> bool: ...
    async def append_exchange(self, user_id: str, conversation_id: str | None, user_text: str, assistant_text: str, project_id: str | None = None, *, product_scope: str, assistant_message_id: str | None = None) -> str: ...
    async def list_projects(self, user_id: str) -> list[ProjectProfile]: ...
    async def list_projects_page(
        self, user_id: str, *, limit: int = MAX_PROJECTS, cursor: str | None = None,
    ) -> tuple[list[ProjectProfile], str | None]: ...
    async def get_project(self, user_id: str, project_id: str) -> ProjectProfile | None: ...
    async def create_project(self, user_id: str, name: str, instructions: str) -> ProjectProfile: ...
    async def update_project(self, user_id: str, project_id: str, name: str, instructions: str) -> ProjectProfile | None: ...
    async def delete_project(self, user_id: str, project_id: str) -> bool: ...
    async def list_project_conversations(self, user_id: str, project_id: str, *, product_scope: str, limit: int = MAX_RECENT_CONVERSATIONS) -> list[dict[str, Any]]: ...
    async def record_claw_run(self, user_id: str, run_id: str, channel: str, action: str, title: str, status: str, result_summary: str | None = None, artifact_document_id: str | None = None, artifact_filename: str | None = None, artifact_media_type: str | None = None, conversation_id: str | None = None, workspace_id: str | None = None) -> None: ...
    async def ensure_claw_automation_conversation(self, *, user_id: str, rule_id: str, rule_name: str) -> str: ...
    async def list_recent_claw_runs(self, user_id: str, limit: int = MAX_CLAW_RUNS, workspace_id: str | None = None) -> list[dict[str, Any]]: ...
    async def update_claw_run_status(self, user_id: str, run_id: str, status: str, result_summary: str | None = None) -> bool: ...
    async def consume_pc_command_confirmation(self, user_id: str, run_id: str, action: str = "pc_command", *, now: datetime | None = None) -> bool: ...
    async def expire_stale_confirmation_cards(self, user_id: str, *, now: datetime | None = None) -> int: ...
    async def append_step_result_message(self, *, user_id: str, run_id: str, message_id: str, content: str) -> bool: ...
    async def record_claw_approval_handoff(self, user_id: str, run_id: str, continuation_ref: str, pause_id: str, pause_expires_at: str, trusted_request: dict[str, Any], workspace_id: str | None = None, conversation_id: str | None = None, p01_run_id: str | None = None) -> None: ...
    async def load_claw_approval_handoff(self, user_id: str, run_id: str, workspace_id: str | None = None) -> dict[str, Any] | None: ...
    async def consume_claw_approval_handoff(self, user_id: str, run_id: str, workspace_id: str | None = None) -> bool: ...


class VerifiedDispatch(dict):
    """A dispatch row that an owner-scoped read produced, tagged with who it was read for.

    It stays a dict, so every reader of these rows keeps working and the value survives the
    queue's JSON boundary. The tag is the point: the original stores refuse a plain dict, so
    a result submission can prove its pin from the row already in hand instead of re-reading
    `oracle_mesh_dispatch` from D1 — which, with the queue live, no longer holds the row, and
    that re-read is what answered the 19:09 submission 403.
    """

    __slots__ = ()

    @property
    def verified_for(self) -> str:
        return str(self.get(_VERIFIED_FOR) or "")


_VERIFIED_FOR = "verified_for_user"
