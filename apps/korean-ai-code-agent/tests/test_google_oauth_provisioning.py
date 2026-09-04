from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
import unittest

from kagent.contracts import ContractError
from kagent.gmail_contracts import GMAIL_READONLY_SCOPE
from kagent.google_oauth_authority import (
    GMAIL_API_BASE_URL,
    GOOGLE_DRIVE_READONLY_SCOPE,
    GoogleProviderHttpResponse,
    GoogleReadonlyOAuthAuthority,
)
from kagent.google_oauth_provisioning import (
    AUTHORIZATION_SESSION_TTL_SECONDS,
    GOOGLE_AUTHORIZATION_URL,
    GoogleOAuthClientConfig,
    GoogleOAuthProvisioner,
    SqliteSealedGoogleOAuthStore,
)


NOW = datetime(2026, 9, 4, 9, 30, tzinfo=timezone.utc)
STATE = "s" * 43
VERIFIER = "v" * 64
BINDING_TOKEN = "b" * 32


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class SequenceRandom:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def __call__(self, size):
        self.calls.append(size)
        if not self.values:
            raise AssertionError("unexpected random-token request")
        return self.values.pop(0)


class DeterministicTestSealer:
    """Authenticated deterministic sealer for tests only; never Production crypto."""

    def __init__(self, key=b"test-only-google-oauth-sealer-key"):
        self.key = key

    def _stream(self, aad, length):
        blocks = []
        counter = 0
        while sum(len(block) for block in blocks) < length:
            blocks.append(
                hashlib.sha256(self.key + aad + counter.to_bytes(4, "big")).digest()
            )
            counter += 1
        return b"".join(blocks)[:length]

    def seal(self, *, plaintext, aad):
        stream = self._stream(aad, len(plaintext))
        ciphertext = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(self.key, aad + ciphertext, hashlib.sha256).digest()
        return tag + ciphertext

    def open(self, *, ciphertext, aad):
        if not isinstance(ciphertext, bytes) or len(ciphertext) < 32:
            raise ContractError("test sealed value is invalid")
        tag, body = ciphertext[:32], ciphertext[32:]
        expected = hmac.new(self.key, aad + body, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ContractError("test sealed value authentication failed")
        stream = self._stream(aad, len(body))
        return bytes(left ^ right for left, right in zip(body, stream))


class FakeNetwork:
    def __init__(self):
        self.responses = []
        self.calls = []

    def push_json(self, status, payload):
        self.responses.append(
            GoogleProviderHttpResponse(status=status, body=json.dumps(payload).encode("utf-8"))
        )

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected network request")
        return self.responses.pop(0)


class GoogleOAuthProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.sealer = DeterministicTestSealer()
        self.store = SqliteSealedGoogleOAuthStore(":memory:", self.sealer)
        self.network = FakeNetwork()
        self.random = SequenceRandom((STATE, VERIFIER, BINDING_TOKEN))
        self.client = GoogleOAuthClientConfig(
            client_id="client-id.apps.googleusercontent.com",
            client_secret="client-secret-value",
            redirect_uri="https://claw.padiem.net/oauth/google/callback",
        )
        self.provisioner = GoogleOAuthProvisioner(
            client=self.client,
            sessions=self.store,
            credentials=self.store,
            network=self.network,
            clock=self.clock,
            random_token=self.random,
        )

    def begin_gmail(self):
        return self.provisioner.begin(
            connector_id="gmail",
            actor_ref="actor_1",
            account_ref="account_1",
            workspace_ref="workspace_1",
        )

    def queue_success(self, *, scope=GMAIL_READONLY_SCOPE, refresh_token="refresh-secret"):
        self.network.push_json(
            200,
            {
                "access_token": "short-lived-access-token",
                "refresh_token": refresh_token,
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": scope,
            },
        )

    def test_begin_binds_trusted_refs_and_builds_offline_state_pkce_url_without_secrets(self):
        start = self.begin_gmail()
        self.assertEqual(start.state_ref, STATE)
        parsed = urlsplit(start.authorization_url)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", GOOGLE_AUTHORIZATION_URL)
        query = parse_qs(parsed.query)
        self.assertEqual(query["client_id"], ["client-id.apps.googleusercontent.com"])
        self.assertEqual(query["redirect_uri"], ["https://claw.padiem.net/oauth/google/callback"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], [GMAIL_READONLY_SCOPE])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["state"], [STATE])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        expected_challenge = __import__("base64").urlsafe_b64encode(
            hashlib.sha256(VERIFIER.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        self.assertEqual(query["code_challenge"], [expected_challenge])
        self.assertNotIn("client_secret", query)
        self.assertNotIn("code_verifier", query)
        self.assertNotIn("account_ref", query)
        self.assertNotIn("workspace_ref", query)
        rendered = start.safe_dict()
        self.assertFalse(rendered["raw_client_secret"])
        self.assertFalse(rendered["raw_code_verifier"])

        persisted = b"\n".join(self.store.raw_persistent_rows_for_audit())
        self.assertNotIn(VERIFIER.encode(), persisted)
        self.assertNotIn(b"client-secret-value", persisted)
        self.assertNotIn(b"account_1", persisted)

    def test_callback_exchanges_code_with_pkce_and_persists_only_sealed_refresh_credential(self):
        self.begin_gmail()
        self.queue_success()
        receipt = self.provisioner.complete_callback(
            state_ref=STATE,
            authorization_code="authorization-code-secret",
        )
        binding = receipt.binding
        self.assertEqual(binding.connector_id, "gmail")
        self.assertEqual(binding.actor_ref, "actor_1")
        self.assertEqual(binding.account_ref, "account_1")
        self.assertEqual(binding.workspace_ref, "workspace_1")
        self.assertEqual(binding.granted_scopes, (GMAIL_READONLY_SCOPE,))
        self.assertEqual(binding.granted_capabilities, ("read",))
        self.assertTrue(binding.binding_ref.startswith("google-gmail-"))

        self.assertEqual(len(self.network.calls), 1)
        token_call = self.network.calls[0]
        self.assertEqual(token_call["method"], "POST")
        form = parse_qs(token_call["body"].decode("utf-8"))
        self.assertEqual(form["grant_type"], ["authorization_code"])
        self.assertEqual(form["code"], ["authorization-code-secret"])
        self.assertEqual(form["code_verifier"], [VERIFIER])
        self.assertEqual(form["client_secret"], ["client-secret-value"])
        self.assertEqual(form["redirect_uri"], [self.client.redirect_uri])

        record = self.store.load(binding_ref=binding.binding_ref)
        self.assertIsNotNone(record)
        self.assertEqual(record.refresh_token, "refresh-secret")
        self.assertEqual(record.binding.workspace_ref, "workspace_1")
        persisted = b"\n".join(self.store.raw_persistent_rows_for_audit())
        for secret in (
            b"refresh-secret",
            b"client-secret-value",
            b"authorization-code-secret",
            VERIFIER.encode(),
        ):
            self.assertNotIn(secret, persisted)

        rendered = receipt.safe_dict()
        self.assertTrue(rendered["refresh_token_persisted"])
        self.assertFalse(rendered["raw_authorization_code"])
        self.assertFalse(rendered["raw_access_token"])
        self.assertFalse(rendered["raw_refresh_token"])

    def test_callback_state_is_single_use_and_replay_fails_before_network(self):
        self.begin_gmail()
        self.queue_success()
        self.provisioner.complete_callback(
            state_ref=STATE,
            authorization_code="authorization-code-secret",
        )
        call_count = len(self.network.calls)
        with self.assertRaisesRegex(ContractError, "unknown or already consumed"):
            self.provisioner.complete_callback(
                state_ref=STATE,
                authorization_code="authorization-code-secret-2",
            )
        self.assertEqual(len(self.network.calls), call_count)

    def test_unknown_state_and_provider_denial_fail_closed_without_token_exchange(self):
        with self.assertRaisesRegex(ContractError, "unknown or already consumed"):
            self.provisioner.complete_callback(
                state_ref="x" * 43,
                authorization_code="code",
            )
        self.assertEqual(self.network.calls, [])

        self.begin_gmail()
        with self.assertRaisesRegex(ContractError, "authorization was not granted"):
            self.provisioner.complete_callback(
                state_ref=STATE,
                provider_error="access_denied",
            )
        self.assertEqual(self.network.calls, [])
        with self.assertRaisesRegex(ContractError, "already consumed"):
            self.provisioner.complete_callback(
                state_ref=STATE,
                authorization_code="code",
            )

    def test_expired_state_fails_after_single_use_consumption(self):
        self.begin_gmail()
        self.clock.now += timedelta(seconds=AUTHORIZATION_SESSION_TTL_SECONDS + 1)
        with self.assertRaisesRegex(ContractError, "state has expired"):
            self.provisioner.complete_callback(
                state_ref=STATE,
                authorization_code="code",
            )
        self.assertEqual(self.network.calls, [])
        with self.assertRaisesRegex(ContractError, "already consumed"):
            self.provisioner.complete_callback(
                state_ref=STATE,
                authorization_code="code",
            )

    def test_callback_rejects_missing_refresh_token_scope_expansion_and_provider_body_leakage(self):
        self.begin_gmail()
        self.network.push_json(
            200,
            {
                "access_token": "access",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": GMAIL_READONLY_SCOPE,
            },
        )
        with self.assertRaisesRegex(ContractError, "lacks refresh_token"):
            self.provisioner.complete_callback(state_ref=STATE, authorization_code="code")
        self.assertEqual(self.store.raw_persistent_rows_for_audit(), ())

        random2 = SequenceRandom(("t" * 43, "w" * 64, "c" * 32))
        provisioner2 = GoogleOAuthProvisioner(
            client=self.client,
            sessions=self.store,
            credentials=self.store,
            network=self.network,
            clock=self.clock,
            random_token=random2,
        )
        start2 = provisioner2.begin(
            connector_id="gmail",
            actor_ref="actor_1",
            account_ref="account_1",
            workspace_ref="workspace_1",
        )
        self.network.push_json(
            200,
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": f"{GMAIL_READONLY_SCOPE} https://www.googleapis.com/auth/gmail.modify",
            },
        )
        with self.assertRaisesRegex(ContractError, "granted scopes differ"):
            provisioner2.complete_callback(state_ref=start2.state_ref, authorization_code="code")

    def test_drive_uses_separate_exact_readonly_scope(self):
        random_drive = SequenceRandom(("d" * 43, "p" * 64, "q" * 32))
        provisioner = GoogleOAuthProvisioner(
            client=self.client,
            sessions=self.store,
            credentials=self.store,
            network=self.network,
            clock=self.clock,
            random_token=random_drive,
        )
        start = provisioner.begin(
            connector_id="google-drive",
            actor_ref="actor_1",
            account_ref="account_1",
            workspace_ref="workspace_1",
        )
        query = parse_qs(urlsplit(start.authorization_url).query)
        self.assertEqual(query["scope"], [GOOGLE_DRIVE_READONLY_SCOPE])
        self.network.push_json(
            200,
            {
                "access_token": "drive-access",
                "refresh_token": "drive-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": GOOGLE_DRIVE_READONLY_SCOPE,
            },
        )
        receipt = provisioner.complete_callback(
            state_ref=start.state_ref,
            authorization_code="drive-code",
        )
        self.assertEqual(receipt.binding.connector_id, "google-drive")
        self.assertEqual(receipt.binding.granted_scopes, (GOOGLE_DRIVE_READONLY_SCOPE,))

    def test_refresh_token_time_based_expiry_projects_into_binding(self):
        self.begin_gmail()
        self.network.push_json(
            200,
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token_expires_in": 7200,
                "scope": GMAIL_READONLY_SCOPE,
            },
        )
        receipt = self.provisioner.complete_callback(state_ref=STATE, authorization_code="code")
        self.assertEqual(receipt.binding.expires_at, NOW + timedelta(seconds=7200))

    def test_sealed_store_detects_ciphertext_tamper_and_delete_removes_credential(self):
        self.begin_gmail()
        self.queue_success()
        receipt = self.provisioner.complete_callback(state_ref=STATE, authorization_code="code")
        binding_ref = receipt.binding.binding_ref
        row = self.store._db.execute(
            "SELECT sealed FROM google_oauth_credentials WHERE binding_ref = ?",
            (binding_ref,),
        ).fetchone()
        tampered = bytearray(row[0])
        tampered[-1] ^= 1
        self.store._db.execute(
            "UPDATE google_oauth_credentials SET sealed = ? WHERE binding_ref = ?",
            (bytes(tampered), binding_ref),
        )
        with self.assertRaisesRegex(ContractError, "authentication failed"):
            self.store.load(binding_ref=binding_ref)
        self.assertTrue(self.store.delete_binding(binding_ref=binding_ref))
        self.assertIsNone(self.store.load(binding_ref=binding_ref))
        self.assertFalse(self.store.delete_binding(binding_ref=binding_ref))

    def test_provisioned_store_is_directly_consumable_by_readonly_authority(self):
        self.begin_gmail()
        self.queue_success(refresh_token="refresh-for-authority")
        receipt = self.provisioner.complete_callback(
            state_ref=STATE,
            authorization_code="authorization-code-secret",
        )
        self.network.push_json(
            200,
            {
                "access_token": "authority-access",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": GMAIL_READONLY_SCOPE,
            },
        )
        self.network.push_json(200, {"messages": []})
        authority = GoogleReadonlyOAuthAuthority(
            credentials=self.store,
            network=self.network,
            clock=self.clock,
        )
        result = authority.get_json(
            binding_ref=receipt.binding.binding_ref,
            actor_ref="actor_1",
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url=GMAIL_API_BASE_URL,
            path="/users/me/messages",
            query={"maxResults": "10"},
            timeout_seconds=30,
            max_response_bytes=256_000,
        )
        self.assertEqual(result, {"messages": []})
        refresh_call = self.network.calls[-2]
        refresh_form = parse_qs(refresh_call["body"].decode("utf-8"))
        self.assertEqual(refresh_form["refresh_token"], ["refresh-for-authority"])
        self.assertEqual(self.network.calls[-1]["headers"]["Authorization"], "Bearer authority-access")

    def test_client_projection_and_redirect_validation_never_expose_secret(self):
        rendered = self.client.safe_dict()
        self.assertFalse(rendered["raw_client_secret"])
        self.assertNotIn("client-secret-value", json.dumps(rendered))
        with self.assertRaisesRegex(ContractError, "HTTPS URI"):
            GoogleOAuthClientConfig(
                client_id="client",
                client_secret="secret",
                redirect_uri="http://claw.padiem.net/oauth/google/callback",
            )

    def test_unreviewed_connector_is_rejected_before_state_persistence(self):
        with self.assertRaisesRegex(ContractError, "not approved"):
            self.provisioner.begin(
                connector_id="google-calendar",
                actor_ref="actor_1",
                account_ref="account_1",
                workspace_ref="workspace_1",
            )
        self.assertEqual(self.store.raw_persistent_rows_for_audit(), ())


if __name__ == "__main__":
    unittest.main()
