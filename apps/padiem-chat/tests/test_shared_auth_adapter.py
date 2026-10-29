import asyncio
import unittest

from app.shared_auth_adapter import SharedAuthUnavailable, SharedChatAuth


class Verifier:
    def verify(self, token):
        if token != 'valid':
            raise ValueError('bad signature')
        return {'accountId': 'sub_synthetic', 'expiresAt': 1100}


class Authority:
    def __init__(self):
        self.calls = 0

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        assert product_id == 'b62'
        assert canonical_subject_id == 'sub_synthetic'
        self.calls += 1
        return 'existing-chat-user'


class SharedAuthTests(unittest.TestCase):
    def test_legacy_only_if_shared_cookie_is_absent(self):
        auth = SharedChatAuth(verifier=Verifier(), authority=Authority(), legacy=lambda _: 'legacy-user', clock=lambda: 1000)
        self.assertEqual(asyncio.run(auth.user_id(None, None)), 'legacy-user')
        for value in ['', 'forged']:
            with self.assertRaises(SharedAuthUnavailable):
                asyncio.run(auth.user_id(None, value))

    def test_verified_account_resolves_existing_user_and_caches(self):
        authority = Authority()
        auth = SharedChatAuth(verifier=Verifier(), authority=authority, legacy=lambda _: None, clock=lambda: 1000)
        self.assertEqual(asyncio.run(auth.user_id(None, 'valid')), 'existing-chat-user')
        self.assertEqual(asyncio.run(auth.user_id(None, 'valid')), 'existing-chat-user')
        self.assertEqual(authority.calls, 1)

    def test_missing_link_does_not_create_user_or_fall_back(self):
        class Missing:
            async def resolve_product_user_for_subject(self, **_kwargs):
                raise ValueError('missing link')
        auth = SharedChatAuth(verifier=Verifier(), authority=Missing(), legacy=lambda _: 'legacy-user', clock=lambda: 1000)
        with self.assertRaises(SharedAuthUnavailable):
            asyncio.run(auth.user_id(None, 'valid'))

    def test_comparison_returns_only_match_or_mismatch(self):
        for legacy, expected in [('existing-chat-user', 'MATCH'), ('different-user', 'MISMATCH')]:
            auth = SharedChatAuth(verifier=Verifier(), authority=Authority(), legacy=lambda _: legacy, clock=lambda: 1000)
            self.assertEqual(asyncio.run(auth.compare_existing_account(None, 'valid')), expected)

    def test_comparison_returns_unknown_for_missing_or_unverified_sessions(self):
        for legacy, token in [(None, 'valid'), ('existing-chat-user', None), ('existing-chat-user', 'forged')]:
            auth = SharedChatAuth(verifier=Verifier(), authority=Authority(), legacy=lambda _: legacy, clock=lambda: 1000)
            self.assertEqual(asyncio.run(auth.compare_existing_account(None, token)), 'UNKNOWN')

    def test_comparison_does_not_log_ids_or_create_a_link(self):
        class Missing:
            async def resolve_product_user_for_subject(self, **_kwargs):
                raise ValueError('unavailable')
        auth = SharedChatAuth(verifier=Verifier(), authority=Missing(), legacy=lambda _: 'private-user', clock=lambda: 1000)
        with self.assertNoLogs():
            self.assertEqual(asyncio.run(auth.compare_existing_account(None, 'valid')), 'UNKNOWN')
