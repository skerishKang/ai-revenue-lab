"""공용 시험 준비 — Google 세션 설정과 메모리 히스토리 저장소.

test_auth_history가 먼저 들고 있던 준비 코드를 여기 옮겨 시험끼리 import가
없어지게 한다(#8061). 가짜 값이라 실제 비밀값이 아니다.
"""
from __future__ import annotations

from app.config import Settings
from app.history import HistoryForbidden, UserProfile

SESSION_SECRET = "phase9-session-secret-not-a-real-credential-000000"


def google_settings(**overrides):
    values = dict(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="phase9-client.apps.googleusercontent.com",
        google_client_secret="unit-test-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    values.update(overrides)
    return Settings.from_values(**values)


class MemoryHistoryStore:
    def __init__(self):
        self.users = {}
        self.conversations = {}
        self.counter = 0

    async def upsert_google_user(self, subject, email, name, picture):
        uid = "usr_" + subject.replace("-", "")[:32].ljust(32, "0")
        profile = UserProfile(uid, email, name or email.split("@", 1)[0], picture)
        self.users[uid] = profile
        return profile

    async def get_user(self, user_id):
        return self.users.get(user_id)

    async def list_conversations(self, user_id, *, product_scope, limit=30):
        rows = [
            c for c in self.conversations.values()
            if c["user_id"] == user_id and c["product_scope"] == product_scope
        ]
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        return [{k: c[k] for k in ("id", "title", "created_at", "updated_at")} for c in rows[:limit]]

    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id or row["product_scope"] != product_scope:
            return None
        return {
            "id": row["id"], "title": row["title"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "messages": [{"role": m["role"], "content": m["content"]} for m in row["messages"]],
        }

    async def delete_conversation(self, user_id, conversation_id, *, product_scope):
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id or row["product_scope"] != product_scope:
            return False
        del self.conversations[conversation_id]
        return True

    async def append_exchange(self, user_id, conversation_id, user_text, assistant_text,
                              project_id=None, *, product_scope):
        if conversation_id is None:
            self.counter += 1
            conversation_id = "chat_" + f"{self.counter:032x}"
            self.conversations[conversation_id] = {
                "id": conversation_id, "user_id": user_id, "title": user_text[:80],
                "product_scope": product_scope,
                "created_at": f"2026-08-25T00:00:{self.counter:02d}Z",
                "updated_at": f"2026-08-25T00:00:{self.counter:02d}Z", "messages": [],
            }
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id or row["product_scope"] != product_scope:
            raise HistoryForbidden()
        row["messages"].extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ])
        self.counter += 1
        row["updated_at"] = f"2026-08-25T00:01:{self.counter:02d}Z"
        return conversation_id


async def add_test_user(store: MemoryHistoryStore, subject="1234567890", email="user@example.test", name="테스트 사용자"):
    return await store.upsert_google_user(subject, email, name, "")
