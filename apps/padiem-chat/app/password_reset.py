"""#5441 lost-password self-service reset: token lifecycle and service.

Why this exists
---------------
#5434 added a self-service password change for a *signed-in* account and proved
ownership with the current password.  A member who lost the password therefore
had no way back into their own account.  This module is the missing path: the
member proves ownership of the account's email address with a one-time link
and then chooses the new password themselves.

Boundaries (the same ones #5441 states)
---------------------------------------
* An email address alone never changes a password.  The password moves only
  after a one-time token that was delivered to that address is redeemed.
* The raw token is never stored.  Only a keyed digest is persisted, so a dump
  of the ledger cannot be replayed against the confirm route.
* The token is single use.  A second redemption of the same token is refused
  and audited, and a successful redemption revokes every other token of that
  account so an older mail cannot be used afterwards.
* Issuance is rate limited per identifier (cooldown + daily budget) so this
  route cannot become an unauthenticated mail-bomb surface.
* The identifier never appears in an audit row.  Only its keyed digest does.
* The account, its id, its #5118 role rows and every other account-owned
  record are preserved: a reset replaces the stored hash of exactly one
  credential row and nothing else.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

# Bounded lifecycle. A reset link is a short-lived, single-use credential.
PASSWORD_RESET_TOKEN_BYTES = 32
PASSWORD_RESET_TOKEN_TTL_SECONDS = 15 * 60
PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS = 60
PASSWORD_RESET_DAILY_REQUEST_LIMIT = 5
PASSWORD_RESET_GLOBAL_DAILY_LIMIT = 1_000
PASSWORD_RESET_MAX_CONSUME_ATTEMPTS = 5
PASSWORD_RESET_AUDIT_RETENTION_DAYS = 30

# Public outcome vocabulary. It never carries configuration, provider or
# account facts.
RESET_UNAVAILABLE = "password_reset_unavailable"
RESET_INVALID_REQUEST = "password_reset_invalid_request"
RESET_RATE_LIMITED = "password_reset_rate_limited"
RESET_TOKEN_INVALID = "password_reset_token_invalid"
RESET_TOKEN_EXPIRED = "password_reset_token_expired"
RESET_TOKEN_USED = "password_reset_token_used"
RESET_TOKEN_REVOKED = "password_reset_token_revoked"
RESET_TOKEN_LOCKED = "password_reset_token_locked"
RESET_DELIVERY_UNAVAILABLE = "password_reset_delivery_unavailable"


class PasswordResetError(Exception):
    """A bounded reset failure with a public code and message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PasswordResetToken:
    token_id: str
    user_id: str
    issued_at: str
    expires_at: str
    attempts: int
    consumed_at: str | None = None
    revoked_at: str | None = None


class PasswordResetStore(Protocol):
    """Durable storage for reset tokens and the reset audit ledger."""

    async def issue_token(
        self, *, user_id: str, token_digest: str, issued_at: str, expires_at: str
    ) -> PasswordResetToken: ...

    async def find_token(self, *, token_digest: str) -> PasswordResetToken | None: ...

    async def consume_token(
        self, *, token_digest: str, consumed_at: str, max_attempts: int
    ) -> PasswordResetToken | None: ...

    async def revoke_tokens_for_user(self, *, user_id: str, revoked_at: str) -> int: ...

    async def record_audit(
        self,
        *,
        event: str,
        user_id: str | None,
        identifier_digest: str,
        reason_code: str | None,
        occurred_at: str,
    ) -> None: ...

    async def count_audit_events(
        self, *, event: str, identifier_digest: str, since: str
    ) -> int: ...

    async def latest_audit_at(
        self, *, event: str, identifier_digest: str
    ) -> str | None: ...

    async def count_audit_events_since(self, *, event: str, since: str) -> int: ...


def _now_iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def generate_reset_token() -> str:
    """Mint one cryptographically random, URL-safe reset token."""

    return secrets.token_urlsafe(PASSWORD_RESET_TOKEN_BYTES)


def reset_token_digest(pepper: str, token: str) -> str:
    """The keyed digest that is stored for a raw reset token."""

    material = b"padiem-password-reset-token-v1\x00" + str(token).encode("utf-8")
    return hmac.new(str(pepper).encode("utf-8"), material, hashlib.sha256).hexdigest()


def identifier_digest(pepper: str, identifier: str) -> str:
    """The keyed digest that stands in for the account identifier at rest."""

    material = b"padiem-password-reset-identifier-v1\x00" + str(identifier).encode(
        "utf-8"
    )
    return hmac.new(str(pepper).encode("utf-8"), material, hashlib.sha256).hexdigest()


def build_reset_link(public_base_url: str, token: str) -> str:
    """The one-time link that is mailed to the account's address.

    The token travels in the URL *fragment*. A fragment is never sent to the
    server, so the raw token never reaches an access log, a Worker log or a
    proxy log on the way in.
    """

    base = str(public_base_url).rstrip("/")
    return f"{base}/#reset={token}"


class PasswordResetService:
    """The lost-password reset flow.

    The service owns the token lifecycle and the rate limits. It never
    authenticates a member and never grants authority: it only decides whether
    a reset token may be issued and whether a presented token may be redeemed.
    """

    def __init__(
        self,
        store: PasswordResetStore,
        *,
        pepper: str,
        public_base_url: str,
        now=None,
    ) -> None:
        if store is None:
            raise ValueError("password reset store is required")
        if not pepper:
            raise ValueError("password reset pepper is required")
        self.store = store
        self._pepper = pepper
        self._public_base_url = str(public_base_url).rstrip("/")
        self._now = now or (lambda: datetime.now(timezone.utc))

    @property
    def ready(self) -> bool:
        return bool(self._pepper) and bool(self._public_base_url)

    def digest_for(self, identifier: str) -> str:
        return identifier_digest(self._pepper, identifier)

    # -- issuance ---------------------------------------------------------

    async def check_request_allowed(
        self, *, identifier: str
    ) -> None:
        """Raise when this identifier may not ask for a reset right now.

        The limits are a cooldown and a daily budget per identifier plus a
        global daily budget. They exist so this unauthenticated route cannot
        become a mail-bomb or an enumeration amplifier.
        """

        digest = self.digest_for(identifier)
        now = self._now().astimezone(timezone.utc).replace(microsecond=0)
        latest = await self.store.latest_audit_at(
            event="requested", identifier_digest=digest
        )
        latest_at = _parse_iso(latest) if latest else None
        if latest_at is not None:
            elapsed = (now - latest_at).total_seconds()
            if elapsed < PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS:
                raise PasswordResetError(
                    RESET_RATE_LIMITED,
                    "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                )
        day_start = now.replace(hour=0, minute=0, second=0).isoformat().replace(
            "+00:00", "Z"
        )
        per_identifier = await self.store.count_audit_events(
            event="requested", identifier_digest=digest, since=day_start
        )
        if per_identifier >= PASSWORD_RESET_DAILY_REQUEST_LIMIT:
            raise PasswordResetError(
                RESET_RATE_LIMITED,
                "요청이 너무 많습니다. 내일 다시 시도해 주세요.",
            )
        global_total = await self.store.count_audit_events_since(
            event="requested", since=day_start
        )
        if global_total >= PASSWORD_RESET_GLOBAL_DAILY_LIMIT:
            raise PasswordResetError(
                RESET_RATE_LIMITED,
                "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
            )

    async def issue(
        self, *, identifier: str, user_id: str
    ) -> tuple[str, PasswordResetToken]:
        """Mint, store and return one reset token for one account.

        Returns the raw token (which is handed to the mailbox and never
        stored) and the persisted token record.
        """

        now = self._now().astimezone(timezone.utc).replace(microsecond=0)
        issued_at = _now_iso(now)
        expires_at = _now_iso(now + timedelta(seconds=PASSWORD_RESET_TOKEN_TTL_SECONDS))
        raw_token = generate_reset_token()
        digest = reset_token_digest(self._pepper, raw_token)
        token = await self.store.issue_token(
            user_id=user_id,
            token_digest=digest,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        await self.store.record_audit(
            event="issued",
            user_id=user_id,
            identifier_digest=self.digest_for(identifier),
            reason_code=None,
            occurred_at=issued_at,
        )
        return raw_token, token

    def link_for(self, raw_token: str) -> str:
        return build_reset_link(self._public_base_url, raw_token)

    # -- redemption --------------------------------------------------------

    async def peek(self, raw_token: str) -> PasswordResetToken | None:
        """Read the token row without consuming it.

        The confirm route uses this to apply the server password policy before
        it burns the token, so a member who typed a rejected password can
        retry with the same link instead of waiting for a new mail.
        """

        if not isinstance(raw_token, str) or not raw_token.strip():
            return None
        digest = reset_token_digest(self._pepper, raw_token.strip())
        return await self.store.find_token(token_digest=digest)

    async def redeem(self, *, raw_token: str) -> str:
        """Redeem one raw token and return the account it belongs to.

        The token must exist, be unconsumed, unrevoked, unexpired and below
        its attempt budget. A second redemption of the same token is refused.
        """

        if not isinstance(raw_token, str) or not raw_token.strip():
            raise PasswordResetError(RESET_TOKEN_INVALID, "재설정 링크가 올바르지 않습니다.")
        digest = reset_token_digest(self._pepper, raw_token.strip())
        token = await self.store.find_token(token_digest=digest)
        if token is None:
            raise PasswordResetError(RESET_TOKEN_INVALID, "재설정 링크가 올바르지 않습니다.")

        now = self._now().astimezone(timezone.utc).replace(microsecond=0)
        consumed_at = _now_iso(now)
        consumed = await self.store.consume_token(
            token_digest=digest,
            consumed_at=consumed_at,
            max_attempts=PASSWORD_RESET_MAX_CONSUME_ATTEMPTS,
        )
        if consumed is None:
            # The atomic consume refused the row: it was already consumed,
            # revoked, expired or over its attempt budget. Re-read the row to
            # report the truthful reason and audit it.
            current = await self.store.find_token(token_digest=digest)
            reason = self._refusal_reason(current, now=now)
            await self.store.record_audit(
                event="rejected",
                user_id=token.user_id,
                identifier_digest=self.digest_for(token.user_id),
                reason_code=reason,
                occurred_at=consumed_at,
            )
            raise PasswordResetError(reason, _REFUSAL_MESSAGES[reason])

        # Every other outstanding token of this account dies with this
        # redemption, so a mail that was delivered earlier cannot be used
        # after the account already changed its password.
        await self.store.revoke_tokens_for_user(
            user_id=consumed.user_id, revoked_at=consumed_at
        )
        await self.store.record_audit(
            event="consumed",
            user_id=consumed.user_id,
            identifier_digest=self.digest_for(consumed.user_id),
            reason_code=None,
            occurred_at=consumed_at,
        )
        return consumed.user_id

    @staticmethod
    def _refusal_reason(token: PasswordResetToken | None, *, now: datetime) -> str:
        if token is None:
            return RESET_TOKEN_INVALID
        expires_at = _parse_iso(token.expires_at)
        if expires_at is not None and expires_at <= now:
            return RESET_TOKEN_EXPIRED
        if token.attempts >= PASSWORD_RESET_MAX_CONSUME_ATTEMPTS:
            return RESET_TOKEN_LOCKED
        if token.revoked_at:
            return RESET_TOKEN_REVOKED
        if token.consumed_at:
            return RESET_TOKEN_USED
        return RESET_TOKEN_USED

    async def record_request(
        self,
        *,
        identifier: str,
        user_id: str | None,
        reason_code: str | None = None,
    ) -> None:
        await self.store.record_audit(
            event="requested",
            user_id=user_id,
            identifier_digest=self.digest_for(identifier),
            reason_code=reason_code,
            occurred_at=_now_iso(self._now().astimezone(timezone.utc)),
        )

    async def record_delivery(
        self,
        *,
        identifier: str,
        user_id: str | None,
        delivered: bool,
    ) -> None:
        await self.store.record_audit(
            event="delivered" if delivered else "delivery_failed",
            user_id=user_id,
            identifier_digest=self.digest_for(identifier),
            reason_code=None if delivered else "delivery_rejected",
            occurred_at=_now_iso(self._now().astimezone(timezone.utc)),
        )


_REFUSAL_MESSAGES = {
    RESET_TOKEN_INVALID: "재설정 링크가 올바르지 않습니다.",
    RESET_TOKEN_EXPIRED: "재설정 링크의 사용 시간이 지났습니다. 다시 요청해 주세요.",
    RESET_TOKEN_USED: "이미 사용된 재설정 링크입니다. 다시 요청해 주세요.",
    RESET_TOKEN_REVOKED: "재설정 링크가 더 이상 유효하지 않습니다. 다시 요청해 주세요.",
    RESET_TOKEN_LOCKED: "재설정 링크 시도 횟수를 초과했습니다. 다시 요청해 주세요.",
}


__all__ = [
    "PASSWORD_RESET_AUDIT_RETENTION_DAYS",
    "PASSWORD_RESET_DAILY_REQUEST_LIMIT",
    "PASSWORD_RESET_GLOBAL_DAILY_LIMIT",
    "PASSWORD_RESET_MAX_CONSUME_ATTEMPTS",
    "PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS",
    "PASSWORD_RESET_TOKEN_TTL_SECONDS",
    "RESET_DELIVERY_UNAVAILABLE",
    "RESET_INVALID_REQUEST",
    "RESET_RATE_LIMITED",
    "RESET_TOKEN_EXPIRED",
    "RESET_TOKEN_INVALID",
    "RESET_TOKEN_LOCKED",
    "RESET_TOKEN_REVOKED",
    "RESET_TOKEN_USED",
    "RESET_UNAVAILABLE",
    "PasswordResetError",
    "PasswordResetService",
    "PasswordResetStore",
    "PasswordResetToken",
    "build_reset_link",
    "generate_reset_token",
    "identifier_digest",
    "reset_token_digest",
]
