"""Validate common-auth profile data before any Chat account mutation."""
from __future__ import annotations

import re


async def provision_shared_profile(request, user_id, access_token, tokens, *, verifier, store, legacy_user, notify):
    if not isinstance(tokens, dict) or not isinstance(user_id, str):
        raise ValueError('invalid_profile_response')
    verified = await verifier.verify(access_token)
    account_id = verified.get('accountId') if isinstance(verified, dict) else None
    if (not isinstance(account_id, str) or not re.fullmatch(r'sub_[A-Za-z0-9_-]+', account_id)
            or tokens.get('account_id') != account_id or not re.fullmatch(r'usr_[0-9a-f]{32}', user_id)):
        raise ValueError('profile_account_mismatch')
    profile = tokens.get('profile')
    if not isinstance(profile, dict) or set(profile) != {'email', 'email_verified', 'name', 'picture'}:
        raise ValueError('invalid_profile')
    email, name, picture = profile['email'], profile['name'], profile['picture']
    if (not isinstance(email, str) or not email.strip() or len(email) > 320
            or profile['email_verified'] is not True or not isinstance(name, str) or len(name) > 160
            or not isinstance(picture, str) or len(picture) > 1000):
        raise ValueError('invalid_profile')
    existing_session = legacy_user(request)
    if existing_session is not None and existing_session != user_id:
        raise ValueError('legacy_account_conflict')
    await store.upsert_shared_user(user_id, account_id, email, name, picture)
    await notify(request, user_id)
