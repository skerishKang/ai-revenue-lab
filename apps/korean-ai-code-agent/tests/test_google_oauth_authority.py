from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from kagent.connector_trust import ConnectorBindingProjection, ConnectorBindingState
from kagent.contracts import ContractError
from kagent.gmail_contracts import GMAIL_READONLY_SCOPE
from kagent.google_oauth_authority import (
    DEFAULT_MAX_RESPONSE_BYTES,
    GMAIL_API_BASE_URL,
    GOOGLE_DRIVE_API_BASE_URL,
    GOOGLE_DRIVE_READONLY_SCOPE,
    GOOGLE_TOKEN_URL,
    GoogleOAuthCredentialRecord,
    GoogleProviderHttpResponse,
    GoogleReadonlyOAuthAuthority,
)


NOW = datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)


class FakeCredentialStore:
    def __init__(self, records=()):
        self.records = {record.binding.binding_ref: record for record in records}
        self.loads = []

    def load(self, *, binding_ref):
        self.loads.append(binding_ref)
        return self.records.get(binding_ref)


class FakeNetwork:
    def __init__(self):
        self.responses = []
        self.calls = []

    def push_json(self, status, payload):
        self.responses.append(
            GoogleProviderHttpResponse(
                status=status,
                body=json.dumps(payload).encode("utf-8"),
            )
        )

    def push_text(self, status, text):
        self.responses.append(
            GoogleProviderHttpResponse(status=status, body=text.encode("utf-8"))
        )

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected network request")
        response = self.responses.pop(0)
        if len(response.body) > kwargs["max_response_bytes"]:
            raise ContractError("Google provider response exceeds trusted byte bound")
        return response


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def binding(
    *,
    binding_ref="binding_google_1",
    connector_id="gmail",
    actor_ref="actor_1",
    scopes=(GMAIL_READONLY_SCOPE,),
    state=ConnectorBindingState.ACTIVE,
    expires_at=None,
):
    return ConnectorBindingProjection(
        binding_ref=binding_ref,
        connector_id=connector_id,
        actor_ref=actor_ref,
        account_ref="account_1",
        workspace_ref="workspace_1",
        granted_scopes=scopes,
        granted_capabilities=("read",),
        issued_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(hours=1),
        expires_at=expires_at,
        state=state,
        revoked_at=NOW - timedelta(minutes=1)
        if state is ConnectorBindingState.REVOKED
        else None,
    )


def credential(**kwargs):
    return GoogleOAuthCredentialRecord(
        binding=kwargs.pop("binding", binding()),
        client_id=kwargs.pop("client_id", "client-id.apps.googleusercontent.com"),
        client_secret=kwargs.pop("client_secret", "client-secret-value"),
        refresh_token=kwargs.pop("refresh_token", "refresh-token-value"),
        **kwargs,
    )


class GoogleOAuthAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.record = credential()
        self.store = FakeCredentialStore((self.record,))
        self.network = FakeNetwork()
        self.authority = GoogleReadonlyOAuthAuthority(
            credentials=self.store,
            network=self.network,
            clock=self.clock,
        )

    def queue_token(self, token="access-token-1", expires_in=3600, scope=None):
        payload = {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": expires_in,
        }
        if scope is not None:
            payload["scope"] = scope
        self.network.push_json(200, payload)

    def test_secret_record_repr_and_projection_do_not_expose_credentials(self):
        rendered_repr = repr(self.record)
        self.assertNotIn("client-secret-value", rendered_repr)
        self.assertNotIn("refresh-token-value", rendered_repr)
        projected = self.record.safe_dict()
        self.assertFalse(projected["raw_client_secret"])
        self.assertFalse(projected["raw_refresh_token"])
        self.assertFalse(projected["raw_access_token"])
        serialized = json.dumps(projected)
        self.assertNotIn("client-secret-value", serialized)
        self.assertNotIn("refresh-token-value", serialized)

    def test_gmail_read_refreshes_token_and_injects_bearer_only_inside_network_boundary(self):
        self.queue_token(scope=GMAIL_READONLY_SCOPE)
        self.network.push_json(200, {"messages": [{"id": "m1"}]})

        result = self.authority.get_json(
            binding_ref="binding_google_1",
            actor_ref="actor_1",
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url=GMAIL_API_BASE_URL,
            path="/users/me/messages",
            query={"q": "is:unread", "maxResults": "10"},
            timeout_seconds=30,
            max_response_bytes=256_000,
        )

        self.assertEqual(result["messages"][0]["id"], "m1")
        self.assertEqual(len(self.network.calls), 2)
        token_call, api_call = self.network.calls
        self.assertEqual(token_call["method"], "POST")
        self.assertEqual(token_call["url"], GOOGLE_TOKEN_URL)
        form = parse_qs(token_call["body"].decode("utf-8"))
        self.assertEqual(form["grant_type"], ["refresh_token"])
        self.assertEqual(form["client_id"], ["client-id.apps.googleusercontent.com"])
        self.assertEqual(form["client_secret"], ["client-secret-value"])
        self.assertEqual(form["refresh_token"], ["refresh-token-value"])
        self.assertNotIn("Authorization", token_call["headers"])

        self.assertEqual(api_call["method"], "GET")
        self.assertEqual(api_call["headers"]["Authorization"], "Bearer access-token-1")
        parsed = urlsplit(api_call["url"])
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, "gmail.googleapis.com")
        self.assertNotIn("access_token", parsed.query)
        self.assertNotIn("refresh-token-value", api_call["url"])

    def test_drive_call_infers_drive_readonly_scope_and_uses_same_authority(self):
        drive_record = credential(
            binding=binding(
                binding_ref="binding_drive_1",
                connector_id="google-drive",
                scopes=(GOOGLE_DRIVE_READONLY_SCOPE,),
            )
        )
        authority = GoogleReadonlyOAuthAuthority(
            credentials=FakeCredentialStore((drive_record,)),
            network=self.network,
            clock=self.clock,
        )
        self.queue_token(scope=GOOGLE_DRIVE_READONLY_SCOPE)
        self.network.push_json(200, {"files": []})

        result = authority.get_json(
            binding_ref="binding_drive_1",
            actor_ref="actor_1",
            base_url=GOOGLE_DRIVE_API_BASE_URL,
            path="/files",
            query={"pageSize": "25"},
            timeout_seconds=30,
        )
        self.assertEqual(result, {"files": []})
        self.assertEqual(
            self.network.calls[1]["max_response_bytes"],
            DEFAULT_MAX_RESPONSE_BYTES,
        )

    def test_actor_connector_scope_and_binding_state_fail_closed_before_network(self):
        with self.assertRaisesRegex(ContractError, "actor binding mismatch"):
            self.authority.get_json(
                binding_ref="binding_google_1",
                actor_ref="actor_other",
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_API_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=30,
            )
        self.assertEqual(self.network.calls, [])

        wrong_connector = credential(
            binding=binding(
                binding_ref="binding_wrong_1",
                connector_id="google-drive",
                scopes=(GOOGLE_DRIVE_READONLY_SCOPE,),
            )
        )
        authority = GoogleReadonlyOAuthAuthority(
            credentials=FakeCredentialStore((wrong_connector,)),
            network=self.network,
            clock=self.clock,
        )
        with self.assertRaisesRegex(ContractError, "connector binding mismatch"):
            authority.get_json(
                binding_ref="binding_wrong_1",
                actor_ref="actor_1",
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_API_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=30,
            )

        missing_scope = credential(
            binding=binding(
                binding_ref="binding_scope_1",
                scopes=("https://www.googleapis.com/auth/gmail.compose",),
            )
        )
        authority = GoogleReadonlyOAuthAuthority(
            credentials=FakeCredentialStore((missing_scope,)),
            network=self.network,
            clock=self.clock,
        )
        with self.assertRaisesRegex(ContractError, "missing the required readonly scope"):
            authority.get_json(
                binding_ref="binding_scope_1",
                actor_ref="actor_1",
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_API_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=30,
            )

        revoked = credential(
            binding=binding(
                binding_ref="binding_revoked_1",
                state=ConnectorBindingState.REVOKED,
            )
        )
        authority = GoogleReadonlyOAuthAuthority(
            credentials=FakeCredentialStore((revoked,)),
            network=self.network,
            clock=self.clock,
        )
        with self.assertRaisesRegex(ContractError, "not active"):
            authority.get_json(
                binding_ref="binding_revoked_1",
                actor_ref="actor_1",
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_API_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=30,
            )
        self.assertEqual(self.network.calls, [])

    def test_exact_readonly_scope_set_and_provider_origin_are_pinned(self):
        with self.assertRaisesRegex(ContractError, "exact scope"):
            self.authority.get_json(
                binding_ref="binding_google_1",
                actor_ref="actor_1",
                required_scopes=("https://www.googleapis.com/auth/gmail.modify",),
                base_url=GMAIL_API_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=30,
            )
        with self.assertRaisesRegex(ContractError, "base URL is not reviewed"):
            self.authority.get_json(
                binding_ref="binding_google_1",
                actor_ref="actor_1",
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url="https://evil.example/gmail/v1",
                path="/users/me/messages",
                query={},
                timeout_seconds=30,
            )
        self.assertEqual(self.network.calls, [])

    def test_cached_access_token_is_reused_until_refresh_skew_window(self):
        self.queue_token()
        self.network.push_json(200, {"id": "first"})
        first = self.authority.get_json(
            binding_ref="binding_google_1",
            actor_ref="actor_1",
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url=GMAIL_API_BASE_URL,
            path="/users/me/messages/m1",
            query={"format": "full"},
            timeout_seconds=30,
        )
        self.assertEqual(first["id"], "first")

        self.network.push_json(200, {"id": "second"})
        second = self.authority.get_json(
            binding_ref="binding_google_1",
            actor_ref="actor_1",
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url=GMAIL_API_BASE_URL,
            path="/users/me/messages/m2",
            query={"format": "full"},
            timeout_seconds=30,
        )
        self.assertEqual(second["id"], "second")
        self.assertEqual([call["method"] for call in self.network.calls], ["POST", "GET", "GET"])

        self.clock.now += timedelta(seconds=3550)
        self.queue_token(token="access-token-2")
        self.network.push_json(200, {"id": "third"})
        self.authority.get_json(
            binding_ref="binding_google_1",
            actor_ref="actor_1",
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url=GMAIL_API_BASE_URL,
            path="/users/me/messages/m3",
            query={},
            timeout_seconds=30,
        )
        self.assertEqual(self.network.calls[-1]["headers"]["Authorization"], "Bearer access-token-2")

    def test_401_invalidates_cache_refreshes_once_and_retries(self):
        self.queue_token(token="access-token-old")
        self.network.push_json(401, {"error": "invalid_token"})
        self.queue_token(token="access-token-new")
        self.network.push_json(200, {"id": "m1"})

        result = self.authority.get_json(
            binding_ref="binding_google_1",
            actor_ref="actor_1",
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url=GMAIL_API_BASE_URL,
            path="/users/me/messages/m1",
            query={},
            timeout_seconds=30,
        )
        self.assertEqual(result["id"], "m1")
        self.assertEqual(
            [call["method"] for call in self.network.calls],
            ["POST", "GET", "POST", "GET"],
        )
        self.assertEqual(
            self.network.calls[1]["headers"]["Authorization"],
            "Bearer access-token-old",
        )
        self.assertEqual(
            self.network.calls[3]["headers"]["Authorization"],
            "Bearer access-token-new",
        )

    def test_provider_query_cannot_smuggle_credentials_or_override_origin(self):
        for query in (
            {"access_token": "secret"},
            {"key": "secret"},
            {"authorization": "Bearer secret"},
        ):
            with self.assertRaisesRegex(ContractError, "credential-bearing"):
                self.authority.get_json(
                    binding_ref="binding_google_1",
                    actor_ref="actor_1",
                    required_scopes=(GMAIL_READONLY_SCOPE,),
                    base_url=GMAIL_API_BASE_URL,
                    path="/users/me/messages",
                    query=query,
                    timeout_seconds=30,
                )
        with self.assertRaisesRegex(ContractError, "path traversal"):
            self.authority.get_json(
                binding_ref="binding_google_1",
                actor_ref="actor_1",
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_API_BASE_URL,
                path="/users/../drive",
                query={},
                timeout_seconds=30,
            )
        self.assertEqual(self.network.calls, [])

    def test_refresh_and_provider_errors_are_generic_and_do_not_echo_secret_bodies(self):
        self.network.push_text(400, "refresh-token-value provider diagnostic")
        with self.assertRaisesRegex(ContractError, "^Google OAuth token refresh failed$") as caught:
            self.authority.get_json(
                binding_ref="binding_google_1",
                actor_ref="actor_1",
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_API_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=30,
            )
        self.assertNotIn("refresh-token-value", str(caught.exception))

        self.network.calls.clear()
        self.network.responses.clear()
        self.queue_token()
        self.network.push_text(403, "access-token-1 sensitive provider details")
        with self.assertRaisesRegex(ContractError, "HTTP 403") as caught:
            self.authority.get_json(
                binding_ref="binding_google_1",
                actor_ref="actor_1",
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_API_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=30,
            )
        self.assertNotIn("access-token-1", str(caught.exception))

    def test_json_text_and_byte_bounds_are_explicit(self):
        self.queue_token()
        self.network.push_text(200, "not-json")
        with self.assertRaisesRegex(ContractError, "JSON response is invalid"):
            self.authority.get_json(
                binding_ref="binding_google_1",
                actor_ref="actor_1",
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_API_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=30,
            )

        another = GoogleReadonlyOAuthAuthority(
            credentials=self.store,
            network=self.network,
            clock=self.clock,
        )
        self.queue_token(token="text-access")
        self.network.push_text(200, "hello drive")
        text = another.get_text(
            binding_ref="binding_google_1",
            actor_ref="actor_1",
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url=GMAIL_API_BASE_URL,
            path="/users/me/profile",
            query={},
            timeout_seconds=30,
            max_response_bytes=100,
        )
        self.assertEqual(text, "hello drive")
        self.assertEqual(self.network.calls[-1]["max_response_bytes"], 100)

        with self.assertRaisesRegex(ContractError, "trusted Google HTTP bound"):
            self.authority.get_json(
                binding_ref="binding_google_1",
                actor_ref="actor_1",
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_API_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=30,
                max_response_bytes=4_000_001,
            )


if __name__ == "__main__":
    unittest.main()