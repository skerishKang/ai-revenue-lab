"""Differential test of the real Identity DO class over two SQLite adapters."""
import base64
import importlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from com2_identity_rpc_ingress import COM2_IDENTITY_RPC_METHODS, create_app
from internal_rpc_ingress import proof_for
from test_identity_authority_durable import FakeStorage

ROOT = Path(__file__).resolve().parents[2]
SECRET = "synthetic-test-secret-" + "x" * 32
KEY = base64.urlsafe_b64encode(b"I" * 32).decode().rstrip("=")


@pytest.mark.asyncio
async def test_twelve_rpc_envelopes_match_actual_do_entrypoint(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "apps/padiem-identity"))
    monkeypatch.syspath_prepend(str(ROOT / "apps/padiem-broker"))
    monkeypatch.delitem(sys.modules, "workers", raising=False)
    monkeypatch.delitem(sys.modules, "identity_authority_worker", raising=False)
    worker = importlib.import_module("identity_authority_worker")
    from storage import SqLiteDurableStorage
    env = SimpleNamespace(CONTROL_PLANE_IDENTITY_LOOKUP_KEY=KEY, GOOGLE_CONNECT_TICKET_KEY=KEY)
    do = worker.CanonicalIdentityDurableObject(SimpleNamespace(storage=FakeStorage()), env)

    db = tmp_path / "identity.sqlite3"
    seed_storage = SqLiteDurableStorage.open(str(db))
    worker.CanonicalIdentityDurableObject(SimpleNamespace(storage=seed_storage), env)
    seed_storage.close()
    key = tmp_path / "key"
    key.write_text(KEY)
    monkeypatch.setenv("COM2_IDENTITY_DB_PATH", str(db))
    monkeypatch.setenv("COM2_IDENTITY_LOOKUP_KEY_FILE", str(key))
    monkeypatch.setenv("COM2_IDENTITY_TICKET_KEY_FILE", str(key))
    factory = importlib.import_module("authority_factory")
    authority = factory.create_authority()
    try:
        app = create_app(authority=authority, secret=SECRET)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            for method in sorted(COM2_IDENTITY_RPC_METHODS):
                path = "/internal/rpc/" + method
                body = b"{}"
                at = int(time.time())
                headers = {"x-padiem-service-at": str(at), "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body)}
                actual = await client.post(path, content=body, headers=headers)
                expected = await getattr(do, method)({})
                assert actual.status_code == 200, method
                assert actual.json() == expected, method
                assert not expected["ok"], method
            # A successful link uses the same DO logic on both adapters. Pin the
            # synthetic token source; compare authority outputs and persisted lookup.
            from datetime import datetime, timedelta, timezone
            instant = datetime.now(timezone.utc)
            class FrozenDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return instant if tz is not None else instant.replace(tzinfo=None)
            monkeypatch.setattr(worker, "datetime", FrozenDatetime)
            do._store._random_hex = lambda n: "a" * (n * 2)
            authority._store._random_hex = lambda n: "a" * (n * 2)
            payload = {"product_id": "b62", "product_user_id": "usr_test", "auth_provider": "google", "provider_subject": "synthetic-provider"}
            path = "/internal/rpc/resolve_or_create_product_link"
            body = json.dumps(payload).encode()
            at = int(time.time())
            headers = {"x-padiem-service-at": str(at), "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body)}
            response = await client.post(path, content=body, headers=headers)
            expected = await do.resolve_or_create_product_link(payload)
            assert expected["ok"] and response.json() == expected
            subject = expected["link"]["canonical_subject_id"]
            assert response.json()["link"]["canonical_subject_id"] == subject
            reverse = {"product_id": "b62", "canonical_subject_id": subject}
            path = "/internal/rpc/resolve_product_user_for_subject"
            body = json.dumps(reverse).encode()
            headers = {"x-padiem-service-at": str(at), "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body)}
            response = await client.post(path, content=body, headers=headers)
            assert response.json() == await do.resolve_product_user_for_subject(reverse)

            # Seed identical owner/session/context rows in each *real* store,
            # then exercise the three consent methods through the HTTP ingress.
            from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
            import canonical_connector_enrollment_consent_rpc as consent_rpc
            monkeypatch.setattr(consent_rpc, "datetime", FrozenDatetime)
            monkeypatch.setattr(consent_rpc.secrets, "token_hex", lambda n: "b" * (n * 2))
            session_id = None
            for side in (do, authority):
                for name in ("CONTROL_PLANE_CONNECTOR_ENROLLMENT_RPC_ENABLED",
                             "CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCOPE_APPROVED",
                             "CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALLED"):
                    setattr(side.env, name, "true")
                tenant = side._store.create_tenant(now=instant)
                side._store.assign_tenant_membership(tenant_id=tenant.tenant_id, canonical_subject_id=subject, now=instant, role="owner")
                linked = side._store.resolve_or_create_product_link(product_id="b54-padiem-claw", product_user_id="usr_claw", auth_provider="google", provider_subject="synthetic-provider", now=instant)
                assert linked.canonical_subject_id == subject
                session = side._store.establish_auth_session(product_id="b54-padiem-claw", subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=subject), authenticated_at=instant, not_after=instant + timedelta(hours=1), now=instant)
                if session_id is None:
                    session_id = session.session_id
                assert session.session_id == session_id
                side._storage.sql.exec("INSERT INTO canonical_connector_context (product_id, subject_id, actor_ref, account_ref, workspace_ref, created_at) VALUES (?, ?, ?, ?, ?, ?)", "b62", subject, "actor.test", "account.test", "workspace.test", instant.isoformat())
                side._connector_enrollment_records.install_schema()
                granted = await side.grant_connector_enrollment_consent({"session_id": session_id, "device_id": "device.test", "confirmed": True, "confirmation_version": "pc-enrollment-consent-v1"})
                assert granted["ok"], granted
                assert granted["consent"]["consent_id"] == "consent." + "b" * 32
            consent_id = "consent." + "b" * 32
            challenge = "pairing." + "f" * 32
            vectors = (
                ("resolve_connector_enrollment_consent_for_device", {"session_id": session_id, "device_id": "device.test"}),
                ("bind_connector_enrollment_challenge", {"session_id": session_id, "challenge_id": challenge, "expires_at": (instant + timedelta(minutes=5)).isoformat()}),
                ("authorize_connector_enrollment_redeem", {"challenge_id": challenge, "consent_id": consent_id, "device_id": "device.test", "owner_ref": subject, "account_ref": "account.test", "workspace_ref": "workspace.test"}),
            )
            for method, payload in vectors:
                expected = await getattr(do, method)(payload)
                path = "/internal/rpc/" + method
                body = json.dumps(payload).encode()
                at = int(time.time())
                headers = {"x-padiem-service-at": str(at), "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body)}
                response = await client.post(path, content=body, headers=headers)
                assert expected["ok"] and response.json() == expected, method

            # Compare the remaining legacy success paths over the same seeded
            # identity and context. The authority owns the clock in each call.
            monkeypatch.setattr(worker, "datetime", FrozenDatetime)
            async def compare(method, payload):
                expected = await getattr(do, method)(payload)
                path = "/internal/rpc/" + method
                body = json.dumps(payload).encode()
                at = int(time.time())
                headers = {"x-padiem-service-at": str(at), "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body)}
                response = await client.post(path, content=body, headers=headers)
                assert response.status_code == 200
                assert expected["ok"] and response.json() == expected, (method, expected, response.json())
                return expected

            for side in (do, authority):
                side._store._random_hex = lambda n: "c" * (n * 2)
            established = await compare("establish_auth_session", {
                "product_id": "b62", "subject": {"subject_type": "user", "subject_id": subject},
                "authenticated_at": instant.isoformat(), "not_after": (instant + timedelta(hours=1)).isoformat(),
            })
            b62_session = established["session"]["session_id"]
            await compare("resolve_auth_session", {"session_id": b62_session})
            await compare("resolve_current_auth_session", {"product_id": "b62", "product_user_id": "usr_test"})
            await compare("resolve_connector_workspace", {"session_id": b62_session})
            await compare("resolve_connector_context", {"session_id": b62_session})
            await compare("revoke_auth_session", {"product_id": "b62", "session_id": b62_session})
            for side in (do, authority):
                side._store._random_hex = lambda n: "d" * (n * 2)
            await compare("establish_auth_session", {
                "product_id": "b62", "subject": {"subject_type": "user", "subject_id": subject},
                "authenticated_at": instant.isoformat(), "not_after": (instant + timedelta(hours=1)).isoformat(),
            })
            await compare("revoke_all_auth_sessions", {"product_id": "b62", "product_user_id": "usr_test"})
    finally:
        authority._storage.close()
        sys.modules.pop("identity_authority_worker", None)
