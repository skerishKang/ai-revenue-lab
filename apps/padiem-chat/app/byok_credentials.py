"""PADIEM Custom (BYOK) owner-scoped provider credential store.

A customer-owned provider key is sealed with AES-GCM before D1 storage and is
looked up only by the server-side direct execution path. No response, log or
browser contract carries the raw key. Ownership is the canonical session
``user_id``; this module never mints a second account or login authority.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from padiem_control_plane.cloudflare_aes_gcm import CloudflareAesGcmPort

MIN_CUSTOM_KEY_CHARS = 16
MAX_CUSTOM_KEY_CHARS = 512


class CustomProviderSelectionError(ValueError):
    """The explicit provider/model pair is not a supported PADIEM Custom route."""


@dataclass(frozen=True, slots=True)
class CustomProvider:
    provider_id: str
    model_id: str
    upstream_model: str
    base_origin: str
    wire: str
    display_name: str


# One already-audited provider wire is exposed for the first slice. The exact
# model is declared here instead of inferred from a request or a B14 registry.
CUSTOM_PROVIDERS: dict[str, CustomProvider] = {
    "opencode-go": CustomProvider(
        provider_id="opencode-go",
        model_id="opencode-go/beam-free",
        upstream_model="beam-free",
        base_origin="https://opencode.ai/inference/go/v1",
        wire="chat/completions",
        display_name="PADIEM Custom (OpenCode Go)",
    ),
}


def resolve_custom_selection(provider_id: str, model_id: str) -> CustomProvider:
    if not isinstance(provider_id, str) or not isinstance(model_id, str):
        raise CustomProviderSelectionError("지원하지 않는 PADIEM Custom 공급사/모델입니다.")
    spec = CUSTOM_PROVIDERS.get(provider_id.strip())
    if spec is None or spec.model_id != model_id.strip():
        raise CustomProviderSelectionError("지원하지 않는 PADIEM Custom 공급사/모델입니다.")
    return spec


def validate_custom_api_key(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("PADIEM Custom API 키 형식이 올바르지 않습니다.")
    key = value.strip()
    if not MIN_CUSTOM_KEY_CHARS <= len(key) <= MAX_CUSTOM_KEY_CHARS:
        raise ValueError("PADIEM Custom API 키 길이가 올바르지 않습니다.")
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
        raise ValueError("PADIEM Custom API 키에 허용되지 않는 문자가 있습니다.")
    return key


def _row(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_py"):
        candidate = value.to_py()
        return candidate if isinstance(candidate, dict) else None
    return dict(value) if hasattr(value, "items") else None


class D1CustomProviderCredentialStore:
    def __init__(self, db: Any, *, session_secret: str, cipher: Any | None = None):
        if db is None or not isinstance(session_secret, str) or len(session_secret) < 32:
            raise ValueError("Trusted D1 and strong product session secret required")
        self.db = db
        # Purpose-separated AES key derived from the server-only product secret.
        self.key = hmac.digest(
            session_secret.encode("utf-8"),
            b"padiem-chat-custom-provider-key-aes-gcm-v1",
            "sha256",
        )
        self.cipher = cipher if cipher is not None else CloudflareAesGcmPort()

    @staticmethod
    def _aad(user_id: str, provider_id: str) -> bytes:
        return f"padiem-custom:{user_id}:{provider_id}".encode("utf-8")

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        return _row(await self.db.prepare(sql).bind(*values).first())

    async def _run(self, sql: str, *values: Any) -> Any:
        return await self.db.prepare(sql).bind(*values).run()

    async def save(
        self,
        *,
        user_id: str,
        provider_id: str,
        api_key: str,
        now: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("canonical owner required")
        if provider_id not in CUSTOM_PROVIDERS:
            raise ValueError("unsupported custom provider")
        key = validate_custom_api_key(api_key)
        timestamp = int(time.time() if now is None else now)
        iv = self.cipher.random_bytes(12)
        plaintext = json.dumps(
            {"api_key": key}, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        ciphertext = await self.cipher.encrypt(
            key=self.key,
            iv=iv,
            plaintext=plaintext,
            additional_data=self._aad(user_id, provider_id),
        )
        sealed = base64.b64encode(iv + ciphertext).decode("ascii")
        await self._run(
            """INSERT INTO chat_custom_provider_credentials
                (user_id,provider_id,key_last4,sealed_credential,created_at,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id,provider_id) DO UPDATE SET
                key_last4=excluded.key_last4,
                sealed_credential=excluded.sealed_credential,
                updated_at=excluded.updated_at""",
            user_id,
            provider_id,
            key[-4:],
            sealed,
            timestamp,
            timestamp,
        )
        return {
            "provider": provider_id,
            "key_last4": key[-4:],
            "updated_at": timestamp,
        }

    async def api_key(self, user_id: str, provider_id: str) -> str | None:
        if not isinstance(user_id, str) or not user_id:
            return None
        if provider_id not in CUSTOM_PROVIDERS:
            return None
        row = await self._first(
            "SELECT sealed_credential FROM chat_custom_provider_credentials WHERE user_id=? AND provider_id=?",
            user_id,
            provider_id,
        )
        if not row:
            return None
        try:
            data = base64.b64decode(row["sealed_credential"], validate=True)
            plaintext = await self.cipher.decrypt(
                key=self.key,
                iv=data[:12],
                ciphertext=data[12:],
                additional_data=self._aad(user_id, provider_id),
            )
            value = json.loads(plaintext.decode("utf-8"))
        except Exception:
            return None
        key = value.get("api_key") if isinstance(value, dict) else None
        return key if isinstance(key, str) and key else None

    async def status(self, user_id: str) -> list[dict[str, Any]]:
        if not isinstance(user_id, str) or not user_id:
            return []
        rows = await self.db.prepare(
            "SELECT provider_id,key_last4,created_at,updated_at FROM chat_custom_provider_credentials WHERE user_id=? ORDER BY provider_id"
        ).bind(user_id).all()
        result = []
        for value in rows or []:
            row = _row(value)
            if row is None or row.get("provider_id") not in CUSTOM_PROVIDERS:
                continue
            result.append(
                {
                    "provider": row["provider_id"],
                    "key_last4": row["key_last4"],
                    "created_at": int(row["created_at"]),
                    "updated_at": int(row["updated_at"]),
                }
            )
        return result

    async def delete(self, user_id: str, provider_id: str) -> bool:
        if not isinstance(user_id, str) or not user_id:
            return False
        if provider_id not in CUSTOM_PROVIDERS:
            return False
        await self._run(
            "DELETE FROM chat_custom_provider_credentials WHERE user_id=? AND provider_id=?",
            user_id,
            provider_id,
        )
        row = await self._first(
            "SELECT 1 AS present FROM chat_custom_provider_credentials WHERE user_id=? AND provider_id=?",
            user_id,
            provider_id,
        )
        return row is None
