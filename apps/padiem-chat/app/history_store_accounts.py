"""계정 저장 (M구역, #7813 H5-1).

`app/history.py`의 `D1HistoryStore`에서 위치만 옮긴 사용자·비밀번호 자격
저장이다. 동작·응답 형식·DB 쿼리 결과는 변하지 않으며, 기존 경로는
`app/history.py`가 `D1HistoryStore`를 조합으로 다시 내보낸다.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .history_errors import HistoryConflict, HistoryError
from .history_ids import _password_user_id, _user_id
from .history_store_core import StoreCore
from .history_text import _now_iso
from .history_types import PasswordCredential, UserProfile


class AccountStore(StoreCore):
    """계정 저장 (M구역)."""

    async def upsert_shared_user(self, user_id: str, account_id: str, email: str, name: str, picture: str) -> UserProfile:
        if not re.fullmatch(r'usr_[0-9a-f]{32}', user_id) or not re.fullmatch(r'sub_[A-Za-z0-9_-]+', account_id):
            raise HistoryError('invalid shared identity')
        now = _now_iso()
        incoming_name = name.strip()[:160]
        if incoming_name:
            display = incoming_name
        else:
            # #7348: an account that already carries its own display name (a
            # password signup, for example) keeps it when the common login
            # publishes a profile with an empty name. The email prefix stays a
            # presentation default only for a row that has no name yet.
            existing = await self._all(
                "SELECT display_name FROM users WHERE id=?", user_id,
            )
            stored = existing[0].get("display_name") if existing else None
            display = (str(stored) if stored else email.split('@', 1)[0])[:160]
        pic = picture.strip()[:1000]
        marker = 'shared:' + account_id
        rows = await self._all(
            "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
            "VALUES (?, 'google', ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET email=excluded.email, display_name=excluded.display_name, "
            "picture_url=excluded.picture_url, updated_at=excluded.updated_at "
            "WHERE users.provider_subject NOT LIKE 'shared:%' OR users.provider_subject=excluded.provider_subject RETURNING id",
            user_id, marker, email, display, pic, now, now,
        )
        if len(rows) != 1:
            raise HistoryConflict('shared identity conflict')
        return UserProfile(user_id, email, display, pic)

    async def upsert_google_user(self, subject: str, email: str, name: str, picture: str) -> UserProfile:
        uid = _user_id(subject)
        now = _now_iso()
        display = (name.strip() or email.split("@", 1)[0])[:160]
        pic = picture.strip()[:1000]
        # The user ID derives from the verified Google subject, so only its
        # own shared placeholder may be replaced when rolling back login.
        await self._run("UPDATE users SET provider_subject=? WHERE id=? AND provider_subject LIKE 'shared:%'", subject, uid)
        await self._run(
            "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
            "VALUES (?, 'google', ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(auth_provider, provider_subject) DO UPDATE SET "
            "email=excluded.email, display_name=excluded.display_name, picture_url=excluded.picture_url, updated_at=excluded.updated_at",
            uid, subject, email, display, pic, now, now,
        )
        return UserProfile(uid, email, display, pic)

    async def register_password_user(
        self,
        username: str,
        email: str,
        name: str,
        password_hash: str,
    ) -> UserProfile:
        existing = await self._first(
            "SELECT id FROM users WHERE lower(email)=lower(?) LIMIT 1",
            email,
        )
        if existing is not None:
            raise HistoryConflict("email already registered")
        existing_username = await self._first(
            "SELECT user_id FROM password_credentials WHERE username=? COLLATE NOCASE LIMIT 1",
            username,
        )
        if existing_username is not None:
            raise HistoryConflict("username already registered")

        uid = _password_user_id(username)
        now = _now_iso()
        display = (name.strip() or username)[:160]
        # The v1 users table has a historical google-only CHECK constraint.
        # Keep this row as storage compatibility only; password_credentials is
        # the product-local auth-method authority, while the Control Plane is
        # explicitly bridged with auth_provider='password'.
        compatibility_subject = "password:" + username
        user_statement = self.db.prepare(
            "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
            "VALUES (?, 'google', ?, ?, ?, '', ?, ?)"
        ).bind(uid, compatibility_subject, email, display, now, now)
        credential_statement = self.db.prepare(
            "INSERT INTO password_credentials "
            "(user_id, username, password_hash, failed_attempts, locked_until, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, NULL, ?, ?)"
        ).bind(uid, username, password_hash, now, now)
        batch = getattr(self.db, "batch", None)
        if not callable(batch):
            raise HistoryError("D1 batch API is required for password registration")
        try:
            await batch([user_statement, credential_statement])
        except Exception as exc:
            raise HistoryConflict("password account registration conflict") from exc
        return UserProfile(uid, email, display, "")

    async def consume_service_id(self, service_id: str, expires_at: str) -> bool:
        """Persist one service RPC id on this store and reject its replay."""
        cutoff = datetime.now(timezone.utc).isoformat()
        await self._run(
            "DELETE FROM password_rpc_service_ids WHERE expires<=?",
            cutoff,
        )
        row = await self._first(
            "INSERT INTO password_rpc_service_ids(service_id, expires) VALUES(?, ?) "
            "ON CONFLICT(service_id) DO NOTHING RETURNING service_id",
            service_id,
            expires_at,
        )
        return row is not None

    async def find_password_credential(self, identifier: str) -> PasswordCredential | None:
        if "@" in identifier:
            row = await self._first(
                "SELECT u.id, u.email, u.display_name, u.picture_url, c.username, c.password_hash, "
                "c.failed_attempts, c.locked_until, c.created_at "
                "FROM password_credentials c JOIN users u ON u.id=c.user_id "
                "WHERE lower(u.email)=lower(?) LIMIT 1",
                identifier,
            )
        else:
            row = await self._first(
                "SELECT u.id, u.email, u.display_name, u.picture_url, c.username, c.password_hash, "
                "c.failed_attempts, c.locked_until, c.created_at "
                "FROM password_credentials c JOIN users u ON u.id=c.user_id "
                "WHERE c.username=? COLLATE NOCASE LIMIT 1",
                identifier,
            )
        if row is None:
            return None
        return PasswordCredential(
            user=UserProfile(
                str(row.get("id", "")),
                str(row.get("email", "")),
                str(row.get("display_name", "")),
                str(row.get("picture_url", "")),
            ),
            username=str(row.get("username", "")),
            password_hash=str(row.get("password_hash", "")),
            failed_attempts=max(0, int(row.get("failed_attempts", 0))),
            locked_until=str(row.get("locked_until")) if row.get("locked_until") else None,
            created_at=str(row.get("created_at")) if row.get("created_at") else None,
        )

    async def record_password_failure(
        self,
        user_id: str,
        failed_attempts: int,
        locked_until: str | None,
    ) -> None:
        await self._run(
            "UPDATE password_credentials SET failed_attempts=?, locked_until=?, updated_at=? WHERE user_id=?",
            failed_attempts,
            locked_until,
            _now_iso(),
            user_id,
        )

    async def reset_password_failures(self, user_id: str) -> None:
        await self._run(
            "UPDATE password_credentials SET failed_attempts=0, locked_until=NULL, updated_at=? WHERE user_id=?",
            _now_iso(),
            user_id,
        )

    # #7556: the three single-statement failure writes. A read-then-write of an
    # absolute count lost every concurrent failure but one; each statement here
    # is evaluated by SQLite/D1 against the row as it is at write time.

    async def increment_password_failures(self, user_id: str) -> int | None:
        """Add one failure in SQL and return the stored count, or None if no row."""
        row = await self._first(
            "UPDATE password_credentials SET failed_attempts=MIN(100, failed_attempts+1), "
            "updated_at=? WHERE user_id=? RETURNING failed_attempts",
            _now_iso(),
            user_id,
        )
        if not row:
            return None
        return max(0, int(row.get("failed_attempts", 0)))

    async def restart_password_failures_after_lapsed_lock(
        self, user_id: str, *, expected_locked_until: str
    ) -> bool:
        """Restart the count at one, only while the exact lapsed lock is still stored."""
        row = await self._first(
            "UPDATE password_credentials SET failed_attempts=1, locked_until=NULL, updated_at=? "
            "WHERE user_id=? AND locked_until=? RETURNING user_id",
            _now_iso(),
            user_id,
            expected_locked_until,
        )
        return bool(row)

    async def lock_password_credential(
        self, user_id: str, *, lock_until: str, min_failures: int
    ) -> None:
        """Set the lock when the stored count reached the limit and no lock is set."""
        await self._run(
            "UPDATE password_credentials SET locked_until=?, updated_at=? "
            "WHERE user_id=? AND failed_attempts>=? AND locked_until IS NULL",
            lock_until,
            _now_iso(),
            user_id,
            int(min_failures),
        )

    async def find_password_credential_by_user_id(
        self, user_id: str
    ) -> PasswordCredential | None:
        """The credential row of one already known account.

        #5434: a self-service password change resolves the account from the
        signed session, never from a request-supplied identifier, so the
        lookup is keyed by the server-owned user id.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        row = await self._first(
            "SELECT u.id, u.email, u.display_name, u.picture_url, c.username, c.password_hash, "
            "c.failed_attempts, c.locked_until "
            "FROM password_credentials c JOIN users u ON u.id=c.user_id "
            "WHERE c.user_id=? LIMIT 1",
            user_id,
        )
        if row is None:
            return None
        return PasswordCredential(
            user=UserProfile(
                str(row.get("id", "")),
                str(row.get("email", "")),
                str(row.get("display_name", "")),
                str(row.get("picture_url", "")),
            ),
            username=str(row.get("username", "")),
            password_hash=str(row.get("password_hash", "")),
            failed_attempts=max(0, int(row.get("failed_attempts", 0))),
            locked_until=str(row.get("locked_until")) if row.get("locked_until") else None,
        )

    async def update_password_credential(
        self, user_id: str, password_hash: str
    ) -> None:
        """Replace the stored hash of one account and clear its failure state.

        #5434: only the hash, the failure counter and the lock move. The
        account id, the role rows, the membership rows and every other
        account-owned record stay exactly as they were.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(password_hash, str) or not password_hash:
            raise HistoryError("password_hash is required")
        await self._run(
            "UPDATE password_credentials SET password_hash=?, failed_attempts=0, "
            "locked_until=NULL, updated_at=? WHERE user_id=?",
            password_hash,
            _now_iso(),
            user_id,
        )

    async def get_user(self, user_id: str) -> UserProfile | None:
        row = await self._first(
            "SELECT id, email, display_name, picture_url FROM users "
            "WHERE id=?",
            user_id,
        )
        if not row:
            return None
        return UserProfile(
            str(row.get("id", "")),
            str(row.get("email", "")),
            str(row.get("display_name", "")),
            str(row.get("picture_url", "")),
        )

    async def user_row_exists(self, user_id: str) -> bool:
        """Whether this product's own store still carries the user row.

        Internal audit H2 (2026-11-10): the request-time session guard asks
        this only for compatibility cookies without a canonical session id —
        the one session shape account deletion cannot revoke server-side.
        Stores that do not model user rows simply do not declare this
        capability, and the guard then keeps the reviewed cookie-only
        behaviour for those requests.
        """

        row = await self._first("SELECT id FROM users WHERE id=?", user_id)
        return row is not None
