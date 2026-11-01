"""Validate common-auth profile data before any Chat account mutation."""
from __future__ import annotations

import logging
import re

from .history import HistoryConflict

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


async def provision_shared_profile(request, user_id, access_token, tokens, *, verifier, store, legacy_user, notify):
    if not isinstance(tokens, dict) or not isinstance(user_id, str):
        raise ValueError('invalid_profile_response')
    verified = await verifier.verify(access_token)
    account_id = verified.get('accountId') if isinstance(verified, dict) else None
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
        # Profile disclosure is opt-in per client, and the production Chat client
        # (b62) has not opted in: the authority then sends a token and nothing else.
        # The verified subject and its existing Chat link are enough to log in, and
        # there is nothing here that Chat may write, so nothing is written.
        logger.info('shared_login_profile_omitted reason=client_opt_out body_fields=%s',
                    ','.join(sorted(key for key in tokens if isinstance(key, str))))
        return
    if (not isinstance(profile, dict) or not profile or not set(profile) <= PROFILE_FIELDS
            or 'email' not in profile):
        # Field names are protocol, values are not.
        logger.warning('shared_login_profile_rejected condition=shape fields=%s body_fields=%s',
                       ','.join(sorted(key for key in profile if isinstance(key, str)))
                       if isinstance(profile, dict) else _shape(profile),
                       ','.join(sorted(key for key in tokens if isinstance(key, str))))
        raise ValueError('invalid_profile')
    email, name, picture = profile['email'], profile.get('name', ''), profile.get('picture', '')
    if (not isinstance(email, str) or not email.strip() or len(email) > 320
            or 'email_verified' in profile and profile['email_verified'] is not True
            or not isinstance(name, str) or len(name) > 160
            or not isinstance(picture, str) or len(picture) > 1000):
        # The verification flag is only required when the client asked for it: the
        # authority sets it once Google's ID token has been checked, and drops it
        # with every other field the client does not list.
        logger.warning('shared_login_profile_rejected condition=values fields=%s',
                       ','.join(sorted(key for key in profile if isinstance(key, str))))
        raise ValueError('invalid_profile')
    try:
        await store.upsert_shared_user(user_id, account_id, email, name, picture)
    except HistoryConflict:
        logger.warning('shared_profile_identity_conflict')
        raise
    await notify(request, user_id)
