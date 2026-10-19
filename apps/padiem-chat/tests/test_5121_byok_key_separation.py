"""#5121 PADIEM Custom (BYOK) encryption-key separation.

The provider-key envelope must be sealed with a dedicated encryption secret,
not with the session-cookie secret. Existing v1 rows written from the session
secret stay readable through an explicit legacy ring and are re-sealed under
the dedicated key on the next read. Missing or wrong key material fails closed
without exposing secret values or the raw provider key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.byok_client import CustomProviderClient
from app.byok_credentials import (
    CUSTOM_KEY_PURPOSE,
    LEGACY_CUSTOM_KEY_PURPOSE,
    CustomCredentialDecryptionError,
    D1CustomProviderCredentialStore,
)
from app.config import ConfigError, Settings
from app.history import D1HistoryStore
from app.main import create_app

SESSION_OLD = "byok-5121-session-secret-old-not-a-real-credential"
SESSION_NEW = "byok-5121-session-secret-new-not-a-real-credential"
KEY_CURRENT = "byok-5121-custom-key-current-not-a-real-credential"
KEY_PREVIOUS = "byok-5121-custom-key-previous-not-a-real-credential"
KEY_WRONG = "byok-5121-custom-key-wrong-not-a-real-credential"
CUSTOM_KEY = "sk-customer-owned-5121-key-AAAA1111"
OTHER_KEY = "sk-customer-owned-5121-key-BBBB2222"
ROTATED_KEY = "sk-customer-owned-5121-key-CCCC3333"
OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
PROVIDER_ID = "opencode-go"
MODEL_ID = "opencode-go/beam-free"
ORIGIN = "https://chat.example.test"
DEFAULT_ANSWER = "custom 답변"

MIGRATIONS = (
    "001_auth_history.sql",
    "002_projects.sql",
    "042_conversation_product_scope.sql",
    "053_chat_custom_provider_credentials.sql",
)


def settings(*, with_custom_key: bool = True, **overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": ORIGIN,
        "google_client_id": "5121-client.apps.googleusercontent.com",
        "google_client_secret": "unit-test-google-secret",
        "session_secret": SESSION_NEW,
        "session_max_age_seconds": 3600,
    }
    if with_custom_key:
        values["custom_key_secret"] = KEY_CURRENT
    values.update(overrides)
    return Settings.from_values(**values)


class Statement:
    def __init__(self, conn: sqlite3.Connection, query: str):
        self.conn = conn
        self.query = query
        self.parameters: tuple = ()

    def bind(self, *values):
        self.parameters = values
        return self

    async def run(self):
        cursor = self.conn.execute(self.query, self.parameters)
        rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
        self.conn.commit()
        return {"results": rows}

    async def first(self):
        row = self.conn.execute(self.query, self.parameters).fetchone()
        self.conn.commit()
        return dict(row) if row else None

    async def all(self):
        rows = [
            dict(row)
            for row in self.conn.execute(self.query, self.parameters).fetchall()
        ]
        self.conn.commit()
        return rows


class SQLiteD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        for name in MIGRATIONS:
            self.conn.executescript((migrations / name).read_text(encoding="utf-8"))
        now = "2026-10-19T00:00:00Z"
        for uid, email in ((OWNER, "owner@example.test"), (OTHER, "other@example.test")):
            self.conn.execute(
                "INSERT INTO users "
                "(id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
                "VALUES (?, 'google', ?, ?, ?, '', ?, ?)",
                (uid, "subject-" + uid, email, email.split("@", 1)[0], now, now),
            )
        self.conn.commit()

    def prepare(self, query: str) -> Statement:
        return Statement(self.conn, query)

    def row(self, user_id: str = OWNER) -> dict | None:
        value = self.conn.execute(
            "SELECT key_last4, sealed_credential, created_at, updated_at "
            "FROM chat_custom_provider_credentials WHERE user_id=? AND provider_id=?",
            (user_id, PROVIDER_ID),
        ).fetchone()
        return dict(value) if value else None

    def insert_sealed(
        self,
        sealed: str,
        *,
        user_id: str = OWNER,
        key_last4: str = CUSTOM_KEY[-4:],
        created_at: int = 100,
        updated_at: int = 100,
    ) -> None:
        self.conn.execute(
            "INSERT INTO chat_custom_provider_credentials "
            "(user_id, provider_id, key_last4, sealed_credential, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, PROVIDER_ID, key_last4, sealed, created_at, updated_at),
        )
        self.conn.commit()


class FakeAuthenticatedCipher:
    def random_bytes(self, size: int) -> bytes:
        assert size == 12
        return b"x" * 12

    async def encrypt(self, *, key, iv, plaintext, additional_data):
        tag = hashlib.sha256(key + iv + additional_data).digest()
        return tag + bytes(value ^ tag[index % len(tag)] for index, value in enumerate(plaintext))

    async def decrypt(self, *, key, iv, ciphertext, additional_data):
        tag = hashlib.sha256(key + iv + additional_data).digest()
        if ciphertext[:32] != tag:
            raise ValueError("AAD mismatch")
        return bytes(value ^ tag[index % len(tag)] for index, value in enumerate(ciphertext[32:]))


class ProviderRecorder:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request):
        self.requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "beam-free",
                "choices": [{"message": {"content": DEFAULT_ANSWER}}],
            },
        )


def derive(secret: str, purpose: bytes) -> bytes:
    return hmac.digest(secret.encode("utf-8"), purpose, "sha256")


def aad(user_id: str = OWNER) -> bytes:
    return f"padiem-custom:{user_id}:{PROVIDER_ID}".encode("utf-8")


async def seal(secret: str, purpose: bytes, api_key: str, user_id: str = OWNER) -> str:
    cipher = FakeAuthenticatedCipher()
    iv = cipher.random_bytes(12)
    ciphertext = await cipher.encrypt(
        key=derive(secret, purpose),
        iv=iv,
        plaintext=json.dumps({"api_key": api_key}, separators=(",", ":")).encode(),
        additional_data=aad(user_id),
    )
    return base64.b64encode(iv + ciphertext).decode("ascii")


async def open_sealed(sealed: str, secret: str, purpose: bytes, user_id: str = OWNER) -> str:
    cipher = FakeAuthenticatedCipher()
    data = base64.b64decode(sealed)
    plaintext = await cipher.decrypt(
        key=derive(secret, purpose),
        iv=data[:12],
        ciphertext=data[12:],
        additional_data=aad(user_id),
    )
    return json.loads(plaintext.decode("utf-8"))["api_key"]


def store(d1: SQLiteD1, **kwargs) -> D1CustomProviderCredentialStore:
    values = {
        "key_secret": KEY_CURRENT,
        "session_secret": SESSION_NEW,
        "cipher": FakeAuthenticatedCipher(),
    }
    values.update(kwargs)
    return D1CustomProviderCredentialStore(d1, **values)


async def request(app, method, path, *, uid=None, json_body=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
    ) as client:
        if uid:
            client.cookies.set(SESSION_COOKIE, create_session_token(settings(), uid))
        return await client.request(
            method, path, json=json_body, headers={"Origin": ORIGIN}
        )


def chat_payload() -> dict:
    return {
        "messages": [{"role": "user", "content": "안녕하세요"}],
        "custom": {"provider": PROVIDER_ID, "model": MODEL_ID},
    }


class B14Bomb:
    def __getattr__(self, name):
        raise AssertionError(f"B14 client touched on BYOK_DIRECT: {name}")


def app_with(store_or_none, *, custom_key: bool = True):
    d1 = SQLiteD1()
    recorder = ProviderRecorder()
    app = create_app(
        settings(with_custom_key=custom_key),
        history_store=D1HistoryStore(d1),
        d1_binding=d1,
        custom_credential_store=store_or_none,
        custom_provider_client=CustomProviderClient(transport=recorder.transport),
    )
    app.state.b14_client = B14Bomb()
    app.state.usage_gate_enforced = False
    return app, d1, recorder


# ---------------------------------------------------------------------------
# Dedicated write key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_writes_use_dedicated_secret_not_session_secret():
    d1 = SQLiteD1()
    credential_store = store(d1)
    await credential_store.save(
        user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY, now=100
    )

    sealed = d1.row()["sealed_credential"]
    assert CUSTOM_KEY not in sealed
    assert await open_sealed(sealed, KEY_CURRENT, CUSTOM_KEY_PURPOSE) == CUSTOM_KEY
    with pytest.raises(ValueError):
        await open_sealed(sealed, SESSION_NEW, LEGACY_CUSTOM_KEY_PURPOSE)

    # The session secret alone can no longer construct the store.
    with pytest.raises(TypeError):
        D1CustomProviderCredentialStore(d1, session_secret=SESSION_NEW)


@pytest.mark.asyncio
async def test_app_factory_composes_store_from_dedicated_secret():
    d1 = SQLiteD1()
    app, _, _ = app_with(None)
    composed = app.state.custom_credential_store
    assert composed is not None
    assert composed.key == derive(KEY_CURRENT, CUSTOM_KEY_PURPOSE)


# ---------------------------------------------------------------------------
# Legacy v1 (session-secret) compatibility and staged transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_row_survives_session_rotation_and_is_resealed():
    d1 = SQLiteD1()
    d1.insert_sealed(await seal(SESSION_OLD, LEGACY_CUSTOM_KEY_PURPOSE, CUSTOM_KEY))

    # Deployment switch: the session secret was already rotated, so the old
    # value is supplied explicitly in the legacy ring.
    credential_store = store(
        d1,
        session_secret=SESSION_NEW,
        legacy_session_secrets=(SESSION_OLD,),
    )
    assert await credential_store.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY

    migrated = d1.row()
    assert migrated["updated_at"] == 100
    assert migrated["key_last4"] == CUSTOM_KEY[-4:]
    assert await open_sealed(migrated["sealed_credential"], KEY_CURRENT, CUSTOM_KEY_PURPOSE) == CUSTOM_KEY
    with pytest.raises(ValueError):
        await open_sealed(migrated["sealed_credential"], SESSION_OLD, LEGACY_CUSTOM_KEY_PURPOSE)

    # The legacy ring can be removed after the re-seal.
    after = store(d1, session_secret=None, legacy_session_secrets=())
    assert await after.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY


@pytest.mark.asyncio
async def test_legacy_row_is_read_with_current_session_secret_before_rotation():
    d1 = SQLiteD1()
    d1.insert_sealed(await seal(SESSION_NEW, LEGACY_CUSTOM_KEY_PURPOSE, CUSTOM_KEY))

    credential_store = store(d1, session_secret=SESSION_NEW)
    assert await credential_store.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY
    assert await open_sealed(
        d1.row()["sealed_credential"], KEY_CURRENT, CUSTOM_KEY_PURPOSE
    ) == CUSTOM_KEY


@pytest.mark.asyncio
async def test_rotated_session_secret_without_legacy_ring_fails_closed():
    d1 = SQLiteD1()
    d1.insert_sealed(await seal(SESSION_OLD, LEGACY_CUSTOM_KEY_PURPOSE, CUSTOM_KEY))
    credential_store = store(d1, session_secret=SESSION_NEW)

    with pytest.raises(CustomCredentialDecryptionError) as error:
        await credential_store.api_key(OWNER, PROVIDER_ID)
    assert SESSION_OLD not in str(error.value)
    assert CUSTOM_KEY not in str(error.value)
    assert d1.row()["sealed_credential"] == await seal(
        SESSION_OLD, LEGACY_CUSTOM_KEY_PURPOSE, CUSTOM_KEY
    )


# ---------------------------------------------------------------------------
# Real AES-GCM interoperability (production WebCrypto wire)
# ---------------------------------------------------------------------------


class RealAesGcmCipher:
    def __init__(self):
        aead = pytest.importorskip(
            "cryptography.hazmat.primitives.ciphers.aead",
            reason="real AES-GCM cross-check requires the cryptography package",
        )
        self._aesgcm = aead.AESGCM

    def random_bytes(self, size: int) -> bytes:
        assert size == 12
        return os.urandom(size)

    async def encrypt(self, *, key, iv, plaintext, additional_data):
        return self._aesgcm(key).encrypt(iv, plaintext, additional_data)

    async def decrypt(self, *, key, iv, ciphertext, additional_data):
        return self._aesgcm(key).decrypt(iv, ciphertext, additional_data)


def _real_plaintext(api_key: str) -> bytes:
    return json.dumps({"api_key": api_key}, separators=(",", ":")).encode("utf-8")


def real_seal(secret: str, purpose: bytes, api_key: str, user_id: str = OWNER) -> str:
    cipher = RealAesGcmCipher()
    iv = cipher.random_bytes(12)
    ciphertext = cipher._aesgcm(derive(secret, purpose)).encrypt(
        iv, _real_plaintext(api_key), aad(user_id)
    )
    return base64.b64encode(iv + ciphertext).decode("ascii")


def real_open(sealed: str, secret: str, purpose: bytes, user_id: str = OWNER) -> str:
    cipher = RealAesGcmCipher()
    data = base64.b64decode(sealed)
    plaintext = cipher._aesgcm(derive(secret, purpose)).decrypt(
        data[:12], data[12:], aad(user_id)
    )
    return json.loads(plaintext.decode("utf-8"))["api_key"]


@pytest.mark.asyncio
async def test_real_aes_gcm_legacy_v1_is_resealed_under_v2():
    d1 = SQLiteD1()
    legacy = real_seal(SESSION_OLD, LEGACY_CUSTOM_KEY_PURPOSE, CUSTOM_KEY)
    d1.insert_sealed(legacy)

    credential_store = store(
        d1,
        cipher=RealAesGcmCipher(),
        session_secret=None,
        legacy_session_secrets=(SESSION_OLD,),
    )
    assert await credential_store.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY

    migrated = d1.row()
    assert migrated["sealed_credential"] != legacy
    assert migrated["updated_at"] == 100
    assert migrated["key_last4"] == CUSTOM_KEY[-4:]
    assert real_open(
        migrated["sealed_credential"], KEY_CURRENT, CUSTOM_KEY_PURPOSE
    ) == CUSTOM_KEY
    with pytest.raises(Exception):
        real_open(migrated["sealed_credential"], SESSION_OLD, LEGACY_CUSTOM_KEY_PURPOSE)

    # A later deployment with the legacy ring removed reads the v2 row.
    after = store(d1, cipher=RealAesGcmCipher(), session_secret=None)
    assert await after.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY


@pytest.mark.asyncio
async def test_real_aes_gcm_tampered_envelope_fails_closed_and_is_not_rewritten():
    d1 = SQLiteD1()
    data = bytearray(base64.b64decode(real_seal(SESSION_OLD, LEGACY_CUSTOM_KEY_PURPOSE, CUSTOM_KEY)))
    data[-1] ^= 0x01
    tampered = base64.b64encode(bytes(data)).decode("ascii")
    d1.insert_sealed(tampered)

    credential_store = store(
        d1,
        cipher=RealAesGcmCipher(),
        session_secret=None,
        legacy_session_secrets=(SESSION_OLD,),
    )
    with pytest.raises(CustomCredentialDecryptionError) as error:
        await credential_store.api_key(OWNER, PROVIDER_ID)
    assert CUSTOM_KEY not in str(error.value)
    assert d1.row()["sealed_credential"] == tampered



# ---------------------------------------------------------------------------
# Dedicated-key rotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_previous_dedicated_key_decrypts_and_reseals():
    d1 = SQLiteD1()
    d1.insert_sealed(await seal(KEY_PREVIOUS, CUSTOM_KEY_PURPOSE, CUSTOM_KEY))

    credential_store = store(
        d1, session_secret=None, previous_key_secrets=(KEY_PREVIOUS,)
    )
    assert await credential_store.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY
    assert await open_sealed(
        d1.row()["sealed_credential"], KEY_CURRENT, CUSTOM_KEY_PURPOSE
    ) == CUSTOM_KEY

    without_previous = store(d1, session_secret=None)
    assert await without_previous.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY


@pytest.mark.asyncio
async def test_wrong_dedicated_key_fails_closed_without_leak():
    d1 = SQLiteD1()
    sealed = await seal(KEY_WRONG, CUSTOM_KEY_PURPOSE, CUSTOM_KEY)
    d1.insert_sealed(sealed)

    credential_store = store(d1, session_secret=None)
    with pytest.raises(CustomCredentialDecryptionError) as error:
        await credential_store.api_key(OWNER, PROVIDER_ID)
    message = str(error.value)
    assert KEY_CURRENT not in message
    assert KEY_WRONG not in message
    assert CUSTOM_KEY not in message
    assert d1.row()["sealed_credential"] == sealed


@pytest.mark.asyncio
async def test_chat_route_maps_wrong_key_to_503_without_provider_call():
    d1 = SQLiteD1()
    d1.insert_sealed(await seal(KEY_WRONG, CUSTOM_KEY_PURPOSE, CUSTOM_KEY))
    app, _, recorder = app_with(store(d1, session_secret=None))

    response = await request(app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "custom_credential_unavailable"
    assert CUSTOM_KEY not in response.text
    assert KEY_CURRENT not in response.text
    assert recorder.requests == []


# ---------------------------------------------------------------------------
# Missing secret fails closed at the product boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_dedicated_secret_leaves_feature_unavailable():
    app, _, recorder = app_with(None, custom_key=False)
    assert app.state.custom_credential_store is None

    status = await request(app, "GET", "/api/chat/custom/credential", uid=OWNER)
    assert status.status_code == 503
    assert status.json()["error"]["code"] == "custom_provider_unavailable"

    save = await request(
        app,
        "PUT",
        "/api/chat/custom/credential",
        uid=OWNER,
        json_body={"provider": PROVIDER_ID, "api_key": CUSTOM_KEY},
    )
    assert save.status_code == 503
    assert save.json()["error"]["code"] == "custom_provider_unavailable"

    chat = await request(app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload())
    assert chat.status_code == 503
    assert chat.json()["error"]["code"] == "custom_provider_unavailable"
    assert recorder.requests == []


# ---------------------------------------------------------------------------
# Owner isolation, overwrite and deletion in dedicated-key mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_aad_rejects_cross_user_ciphertext_swap():
    d1 = SQLiteD1()
    credential_store = store(d1)
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)
    await credential_store.save(user_id=OTHER, provider_id=PROVIDER_ID, api_key=OTHER_KEY)

    assert await credential_store.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY
    assert await credential_store.api_key(OTHER, PROVIDER_ID) == OTHER_KEY

    d1.conn.execute(
        "UPDATE chat_custom_provider_credentials SET sealed_credential=? "
        "WHERE user_id=? AND provider_id=?",
        (d1.row(OWNER)["sealed_credential"], OTHER, PROVIDER_ID),
    )
    d1.conn.commit()

    with pytest.raises(CustomCredentialDecryptionError):
        await credential_store.api_key(OTHER, PROVIDER_ID)
    assert await credential_store.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY


@pytest.mark.asyncio
async def test_overwrite_and_delete_remain_owner_scoped():
    d1 = SQLiteD1()
    credential_store = store(d1)
    await credential_store.save(
        user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY, now=100
    )
    await credential_store.save(
        user_id=OTHER, provider_id=PROVIDER_ID, api_key=OTHER_KEY, now=110
    )

    rotated = await credential_store.save(
        user_id=OWNER, provider_id=PROVIDER_ID, api_key=ROTATED_KEY, now=200
    )
    assert rotated == {
        "provider": PROVIDER_ID,
        "key_last4": ROTATED_KEY[-4:],
        "updated_at": 200,
    }
    assert await credential_store.api_key(OWNER, PROVIDER_ID) == ROTATED_KEY
    assert await credential_store.api_key(OTHER, PROVIDER_ID) == OTHER_KEY

    assert await credential_store.delete(OWNER, PROVIDER_ID) is True
    assert await credential_store.api_key(OWNER, PROVIDER_ID) is None
    assert await credential_store.status(OWNER) == []
    assert await credential_store.api_key(OTHER, PROVIDER_ID) == OTHER_KEY


# ---------------------------------------------------------------------------
# Configuration surface
# ---------------------------------------------------------------------------


def test_settings_parse_rotation_rings_and_reject_short_secrets():
    configured = Settings.from_values(
        auth_mode="off",
        custom_key_secret=KEY_CURRENT,
        custom_key_previous_secrets=f" {KEY_PREVIOUS} , {KEY_PREVIOUS} ",
        custom_key_legacy_session_secrets=f"{SESSION_OLD},{SESSION_OLD}",
    )
    assert configured.custom_key_secret == KEY_CURRENT
    assert configured.custom_key_previous_secrets == (KEY_PREVIOUS,)
    assert configured.custom_key_legacy_session_secrets == (SESSION_OLD,)
    rendered = repr(configured)
    assert KEY_CURRENT not in rendered
    assert KEY_PREVIOUS not in rendered
    assert SESSION_OLD not in rendered

    with pytest.raises(ConfigError):
        Settings.from_values(auth_mode="off", custom_key_secret="short")
    with pytest.raises(ConfigError):
        Settings.from_values(auth_mode="off", custom_key_previous_secrets="short")
    with pytest.raises(ConfigError):
        Settings.from_values(
            auth_mode="off", custom_key_legacy_session_secrets=[SESSION_OLD, "short"]
        )


def test_worker_bindings_project_the_dedicated_key_names():
    from app.worker_config import WORKER_BINDING_NAMES, settings_from_worker_bindings

    for name in (
        "PADIEM_CHAT_CUSTOM_KEY_SECRET",
        "PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS",
        "PADIEM_CHAT_CUSTOM_KEY_LEGACY_SESSION_SECRETS",
    ):
        assert name in WORKER_BINDING_NAMES

    projected = settings_from_worker_bindings(
        {
            "PADIEM_CHAT_AUTH_MODE": "off",
            "PADIEM_CHAT_CUSTOM_KEY_SECRET": KEY_CURRENT,
            "PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS": KEY_PREVIOUS,
            "PADIEM_CHAT_CUSTOM_KEY_LEGACY_SESSION_SECRETS": SESSION_OLD,
        }
    )
    assert projected.custom_key_secret == KEY_CURRENT
    assert projected.custom_key_previous_secrets == (KEY_PREVIOUS,)
    assert projected.custom_key_legacy_session_secrets == (SESSION_OLD,)
