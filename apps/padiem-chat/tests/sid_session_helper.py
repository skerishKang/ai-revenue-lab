"""Post-transition session test helpers (#8035 운영센터 작업 중 발견, 2026-11-19).

The reviewed sideless-session transition window ended at 2026-11-18 23:59:59 UTC
(`app.auth.SIDELESS_SESSION_ACCEPTED_UNTIL`): on an authority-backed test app a
session cookie without a canonical session id (`sid`) is refused from now on.
Tests that simulate a signed-in account therefore plant a cookie that CARRIES
the sid their fixture authority knows, and their authority resolves that sid
asynchronously — the same shape the production guard expects.

Use the two pieces here instead of hand-rolling per file:

  * `sid_session_token(settings, user_id, session_id=…)` — a signed session
    token that carries the sid;
  * `AsyncSessionAuthority(session, *, extra=…)` — an authority double whose
    `resolve_auth_session` is async and answers with the bound session for any
    sid (recording calls, like the hand-rolled doubles it replaces).

The deadline semantics themselves are pinned in test_5225_logout_session_
revocation.py (both sides of the cutoff, injected now — no real-clock test).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.auth import create_session_token

DEFAULT_SESSION_ID = "session_test_a"


def sid_session_token(settings, user_id: str, *, session_id: str = DEFAULT_SESSION_ID,
                      now: int | None = None) -> str:
    """A signed session token carrying the canonical sid (post-transition)."""
    return create_session_token(settings, user_id, now=now,
                                canonical_session_id=session_id)


class AsyncSessionAuthority:
    """An authority double: `resolve_auth_session` is async and answers with
    the bound session for any sid. `revoked_sids` answer None (revoked), and
    `raising` sids raise the given exception (authority-unavailable paths)."""

    def __init__(self, session, *, extra: dict | None = None,
                 revoked_sids: set | None = None, raising: dict | None = None):
        self.session = session
        self.extra = dict(extra or {})
        self.revoked_sids = set(revoked_sids or ())
        self.raising = dict(raising or {})
        self.calls: list[str] = []

    async def resolve_auth_session(self, *, session_id: str):
        self.calls.append(session_id)
        if session_id in self.revoked_sids:
            return None
        if session_id in self.raising:
            raise self.raising[session_id]
        if session_id in self.extra:
            return self.extra[session_id]
        return self.session


def active_snapshot(snapshot_factory, *, session_id: str = DEFAULT_SESSION_ID,
                    subject_id: str | None = None, minutes: int = 30):
    """Build a relative-time active snapshot through the caller's own factory
    (keeps each test's snapshot shape) with times relative to now."""
    now = datetime.now(timezone.utc)
    return snapshot_factory(now - timedelta(minutes=3), now + timedelta(minutes=minutes),
                            session_id=session_id, subject_id=subject_id)
