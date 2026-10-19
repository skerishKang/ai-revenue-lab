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

# The dedicated key purpose never shares a derived key with the session-cookie
# secret. v1 is retained for decryption only so pre-separation rows stay
# readable until their next read re-seals them under v2.
CUSTOM_KEY_PURPOSE = b"padiem-chat-custom-provider-key-aes-gcm-v2"
LEGACY_CUSTOM_KEY_PURPOSE = b"padiem-chat-custom-provider-key-aes-gcm-v1"
MIN_KEY_SECRET_CHARS = 32


class CustomProviderSelectionError(ValueError):
    """The explicit provider/model pair is not a supported PADIEM Custom route."""


class CustomCredentialDecryptionError(RuntimeError):
    """Stored ciphertext is unreadable with every configured key.

    The message is fixed and never carries key material, plaintext or the
    stored envelope.
    """


def _derive_key(secret: str, purpose: bytes) -> bytes:
    return hmac.digest(secret.encode("utf-8"), purpose, "sha256")


def _strong_secret(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or len(value) < MIN_KEY_SECRET_CHARS:
        raise ValueError(f"{name} must be at least {MIN_KEY_SECRET_CHARS} characters")
    return value


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
    def __init__(
        self,
        db: Any,
        *,
        key_secret: str,
        session_secret: str | None = None,
        cipher: Any | None = None,
        previous_key_secrets: tuple[str, ...] | list[str] = (),
        legacy_session_secrets: tuple[str, ...] | list[str] = (),
    ):
        """Seal customer keys under a dedicated encryption secret.

        ``key_secret`` is mandatory and only its purpose-separated derivation is
        retained. ``session_secret`` and ``legacy_session_secrets`` are accepted
        solely to decrypt v1 rows written before the separation; successful
        reads are re-sealed under the current dedicated key. Raw secrets are
        never stored on the instance.
        """
        if db is None:
            raise ValueError("Trusted D1 required")
        current = _strong_secret(key_secret, name="custom key secret")

        keys: list[bytes] = [_derive_key(current, CUSTOM_KEY_PURPOSE)]
        for secret in previous_key_secrets or ():
            keys.append(
                _derive_key(
                    _strong_secret(secret, name="previous custom key secret"),
                    CUSTOM_KEY_PURPOSE,
                )
            )
        # The active session secret is the most recent legacy source, so it is
        # tried first; explicit history follows.
        legacy = list(legacy_session_secrets or ())
        if session_secret is not None:
            legacy.insert(
                0, _strong_secret(session_secret, name="session secret")
            )
        for secret in legacy:
            keys.append(
                _derive_key(
                    _strong_secret(secret, name="legacy session secret"),
                    LEGACY_CUSTOM_KEY_PURPOSE,
                )
            )

        unique: list[bytes] = []
        for key in keys:
            if key not in unique:
                unique.append(key)
        self.db = db
        self.key = unique[0]
        self._decryption_keys = tuple(unique)
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
        return await self._decrypt_and_reseal(
            row["sealed_credential"], user_id, provider_id
        )

    async def _decrypt_and_reseal(
        self, sealed: Any, user_id: str, provider_id: str
    ) -> str:
        aad = self._aad(user_id, provider_id)
        try:
            data = base64.b64decode(str(sealed), validate=True)
        except Exception:
            raise CustomCredentialDecryptionError(
                "PADIEM Custom credential could not be decrypted"
            ) from None
        if len(data) <= 12:
            raise CustomCredentialDecryptionError(
                "PADIEM Custom credential could not be decrypted"
            )

        value: str | None = None
        matched_current = False
        for key in self._decryption_keys:
            try:
                plaintext = await self.cipher.decrypt(
                    key=key,
                    iv=data[:12],
                    ciphertext=data[12:],
                    additional_data=aad,
                )
                parsed = json.loads(plaintext.decode("utf-8"))
            except Exception:
                continue
            candidate = parsed.get("api_key") if isinstance(parsed, dict) else None
            if isinstance(candidate, str) and candidate:
                value = candidate
                matched_current = key == self.key
                break

        if value is None:
            raise CustomCredentialDecryptionError(
                "PADIEM Custom credential could not be decrypted"
            )

        if not matched_current:
            await self._reseal(sealed, value, user_id, provider_id, aad)
        return value

    async def _reseal(
        self,
        previous_sealed: Any,
        api_key: str,
        user_id: str,
        provider_id: str,
        aad: bytes,
    ) -> None:
        """Move one row to the current key without changing its metadata.

        A concurrent explicit save must win, so the update is conditional on
        the envelope that was just decrypted. A failed rewrite leaves the row
        readable through the legacy key ring and is retried on the next read.
        """
        iv = self.cipher.random_bytes(12)
        plaintext = json.dumps(
            {"api_key": api_key}, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        try:
            ciphertext = await self.cipher.encrypt(
                key=self.key, iv=iv, plaintext=plaintext, additional_data=aad
            )
            sealed = base64.b64encode(iv + ciphertext).decode("ascii")
            await self._run(
                """UPDATE chat_custom_provider_credentials
                   SET sealed_credential=?
                   WHERE user_id=? AND provider_id=? AND sealed_credential=?""",
                sealed,
                user_id,
                provider_id,
                previous_sealed,
            )
        except Exception:
            # Availability of the recovered key wins; the legacy ring remains
            # usable and the next read retries the migration.
            return

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
