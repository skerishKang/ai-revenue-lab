"""Validate common-auth profile data before any Chat account mutation."""
from __future__ import annotations

import logging
import re
import time

from .history import HistoryConflict
from .journal_host import ensure_journal_visible
from .shared_login_timing import record_login_timing

logger = logging.getLogger(__name__)

# Account ids, user ids and profiles are identity. A diagnostic may say what shape
# arrived — prefix class and length — and nothing more.
def _shape(value):
    if isinstance(value, str):
        # Only the leading alphabetic run plus one underscore: 'usr_' tells a
        # reviewer which identifier family arrived, and nothing about whose it is.
        head = re.match(r'[A-Za-z]+_?', value)
        return f'{head.group(0) if head else "?"}+{len(value)}'
    if value is None:
        return 'absent'
    return type(value).__name__ if not isinstance(value, dict) else 'dict' + str(len(value))


# The authority filters the profile down to the client's own allowlist, so a
# supplied profile is any non-empty subset of these, always including 'email'.
PROFILE_FIELDS = frozenset({'email', 'email_verified', 'name', 'picture'})


def _verified_email_ok(profile, amr=None) -> bool:
    """email_verified 요구를 만족하는가. 그 외 필드 검사와 무관하게 값만 본다.

    1) 서명 검증된 액세스 토큰에 `amr` 클레임이 있으면 `amr`을 우선 신뢰한다:
       `amr`에 `'pwd'`가 있으면 Chat 내부 비밀번호 확인(/internal/password-verify)을
       거친 계정이므로 `email_verified=False`를 면제하고, `'google'` 등 다른 값이면
       프로필 모양과 무관하게 거절한다.
    2) 서명 검증된 토큰에 `amr`이 없을 때만 기존 발행 모양(`email_verified:false,
       name:'', picture:''`)으로 판별한다.
    """
    if 'email_verified' not in profile:
        # #7348 (2026-11-10 review): every issuing path states the flag —
        # Google profiles carry true, the password contract carries false with
        # its own empty-name shape. A profile that omits the key is not an
        # issuer this module knows, so it fails closed instead of being read
        # as verified.
        return False
    if profile['email_verified'] is True:
        return True
    if profile['email_verified'] is not False:
        return False
    if amr is not None:
        return (
            isinstance(amr, (list, tuple))
            and len(amr) > 0
            and all(isinstance(item, str) and item for item in amr)
            and 'pwd' in amr
            and 'google' not in amr
        )
    return (
        profile.get('name') == ''
        and profile.get('picture') == ''
    )


async def provision_shared_profile(request, user_id, access_token, tokens, *, verifier, store, legacy_user, notify):
    if not isinstance(tokens, dict) or not isinstance(user_id, str):
        raise ValueError('invalid_profile_response')
    verify_started = time.perf_counter()
    try:
        verified = await verifier.verify(access_token)
    finally:
        record_login_timing('profile_token_verify', (time.perf_counter() - verify_started) * 1000)
    account_id = verified.get('accountId') if isinstance(verified, dict) else None
    verified_amr = verified.get('amr') if isinstance(verified, dict) else None
    # Three different things failed under one code. The verified access token — not
    # the exchange body — is the authority for which account this login is, and a
    # conforming OAuth /token body states no account id at all; when the body does
    # state one, in either spelling, it must agree. The Chat user id is checked on
    # its own so a broken identity link is never mistaken for a bad token.
    if not isinstance(account_id, str) or not re.fullmatch(r'sub_[A-Za-z0-9_-]+', account_id):
        logger.warning('shared_login_account_rejected condition=verified_subject verified=%s',
                       _shape(account_id))
        raise ValueError('profile_account_mismatch')
    if not re.fullmatch(r'usr_[0-9a-f]{32}', user_id):
        logger.warning('shared_login_account_rejected condition=chat_user_id user_id=%s verified=sub_present',
                       _shape(user_id))
        raise ValueError('profile_account_mismatch')
    stated = next((tokens[key] for key in ('account_id', 'accountId')
                   if tokens.get(key) is not None), None)
    if stated is None:
        ensure_journal_visible(logger)
        logger.info('shared_login_account_cross_check=absent verified=%s', _shape(account_id))
    elif stated != account_id:
        logger.warning('shared_login_account_rejected condition=exchange_mismatch stated=%s verified=%s',
                       _shape(stated), _shape(account_id))
        raise ValueError('profile_account_mismatch')
    # A session for a different Chat account is the same conflict whether or not
    # this client asked for profile fields, so it is settled first.
    existing_session = legacy_user(request)
    if existing_session is not None and existing_session != user_id:
        logger.warning('shared_profile_identity_conflict')
        raise ValueError('legacy_account_conflict')
    profile = tokens.get('profile')
    if profile is None:
        # Profile disclosure is opt-in per client. When omitted, the verified
        # subject and its existing Chat link still identify the account, and
        # there is no profile data for this client to write.
        logger.info('shared_login_profile_omitted reason=client_opt_out body_field_count=%d', len(tokens))
        return
    if (not isinstance(profile, dict) or not profile or not set(profile) <= PROFILE_FIELDS
            or 'email' not in profile):
        # Field names are protocol, values are not.
        logger.warning('shared_login_profile_rejected condition=shape profile_field_count=%s body_field_count=%d',
                       len(profile) if isinstance(profile, dict) else _shape(profile), len(tokens))
        raise ValueError('invalid_profile')
    email, name, picture = profile['email'], profile.get('name', ''), profile.get('picture', '')
    if (not isinstance(email, str) or not email.strip() or len(email) > 320
            or not _verified_email_ok(profile, verified_amr)
            or not isinstance(name, str) or len(name) > 160
            or not isinstance(picture, str) or len(picture) > 1000):
        # The verification flag is only required when the client asked for it: the
        # authority sets it once Google's ID token has been checked, and drops it
        # with every other field the client does not list. Google profiles carry
        # verified=true; a password profile is recognised by its issuer contract
        # (see `_verified_email_ok`) — the credential was already proven against
        # Chat's own password verify before padiem-auth issued this profile.
        logger.warning('shared_login_profile_rejected condition=values profile_field_count=%d', len(profile))
        raise ValueError('invalid_profile')
    store_started = time.perf_counter()
    try:
        await store.upsert_shared_user(user_id, account_id, email, name, picture)
    except HistoryConflict:
        logger.warning('shared_profile_identity_conflict')
        raise
    finally:
        record_login_timing('profile_user_upsert', (time.perf_counter() - store_started) * 1000)
    notify_started = time.perf_counter()
    try:
        await notify(request, user_id)
    finally:
        record_login_timing('profile_notification', (time.perf_counter() - notify_started) * 1000)
