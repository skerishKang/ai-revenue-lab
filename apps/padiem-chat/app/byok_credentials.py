"""PADIEM Custom (BYOK) owner-scoped provider credential store.

A customer-owned provider key is sealed with AES-GCM before D1 storage and is
looked up only by the server-side direct execution path. No response, log or
browser contract carries the raw key. Ownership is the canonical session
``user_id``; this module never mints a second account or login authority.

A credential is bound to the canonical owner, the provider id and the
effective endpoint. Custom endpoints use an endpoint-bound AAD so a tampered
D1 row cannot redirect a sealed key to another host; pre-endpoint rows remain
readable through the legacy AAD and are re-sealed on the next read.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from padiem_control_plane.cloudflare_aes_gcm import CloudflareAesGcmPort

from .byok_endpoint import CustomEndpointError, normalize_custom_endpoint

MIN_CUSTOM_KEY_CHARS = 16
MAX_CUSTOM_KEY_CHARS = 512
MAX_CUSTOM_MODEL_CHARS = 200

# The dedicated key purpose never shares a derived key with the session-cookie
# secret. v1 is retained for decryption only so pre-separation rows stay
# readable until their next read re-seals them under v2.
CUSTOM_KEY_PURPOSE = b"padiem-chat-custom-provider-key-aes-gcm-v2"
LEGACY_CUSTOM_KEY_PURPOSE = b"padiem-chat-custom-provider-key-aes-gcm-v1"
MIN_KEY_SECRET_CHARS = 32

_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$")


class CustomProviderSelectionError(ValueError):
    """The explicit provider/model pair is not a supported PADIEM Custom route."""


class CustomCredentialDecryptionError(RuntimeError):
    """Stored ciphertext is unreadable with every configured key.

    The message is fixed and never carries key material, plaintext or the
    stored envelope.
    """


class CustomEndpointStorageUnavailable(RuntimeError):
    """The additive endpoint column has not been applied to this database."""


def _derive_key(secret: str, purpose: bytes) -> bytes:
    return hmac.digest(secret.encode("utf-8"), purpose, "sha256")


def _strong_secret(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or len(value) < MIN_KEY_SECRET_CHARS:
        raise ValueError(f"{name} must be at least {MIN_KEY_SECRET_CHARS} characters")
    return value


@dataclass(frozen=True, slots=True)
class CustomProvider:
    provider_id: str
    display_name: str
    base_origin: str
    wire: str
    auth: str
    models: tuple[str, ...] = ()
    models_path: str | None = None
    allowed_models: tuple[str, ...] | None = None
    extra_headers: tuple[tuple[str, str], ...] = ()
    stream_by_default: bool = True

    @property
    def model_id(self) -> str:
        """First registry model, kept for the original OpenCode Go contract."""
        return self.models[0] if self.models else ""

    def accepts_model(self, model_id: str) -> bool:
        if self.allowed_models is None:
            return True
        return model_id in self.allowed_models

    def upstream_model(self, model_id: str) -> str:
        """Map the public model id to the vendor wire id."""
        prefix = self.provider_id + "/"
        if model_id.startswith(prefix) and model_id[len(prefix):]:
            candidate = model_id[len(prefix):]
            if self.allowed_models is None or model_id in self.allowed_models:
                return candidate
        return model_id


@dataclass(frozen=True, slots=True)
class ResolvedCustomSelection:
    provider: CustomProvider
    model_id: str
    upstream_model: str


# Official provider base URLs and wire contracts. Model catalogs are fetched
# from each provider at runtime where the provider exposes a list endpoint;
# only the pre-existing OpenCode Go model stays a fixed registry entry.
CUSTOM_PROVIDERS: dict[str, CustomProvider] = {
    "opencode-go": CustomProvider(
        provider_id="opencode-go",
        display_name="Padiem Custom (OpenCode Go)",
        base_origin="https://opencode.ai/inference/go/v1",
        wire="openai-chat",
        auth="bearer",
        models=("opencode-go/beam-free",),
        allowed_models=("opencode-go/beam-free",),
        stream_by_default=False,
    ),
    "openai": CustomProvider(
        provider_id="openai",
        display_name="OpenAI",
        base_origin="https://api.openai.com/v1",
        wire="openai-chat",
        auth="bearer",
        models_path="models",
    ),
    "openrouter": CustomProvider(
        provider_id="openrouter",
        display_name="OpenRouter",
        base_origin="https://openrouter.ai/api/v1",
        wire="openai-chat",
        auth="bearer",
        models_path="models",
        extra_headers=(("X-Title", "PADIEM Chat"),),
    ),
    "anthropic": CustomProvider(
        provider_id="anthropic",
        display_name="Anthropic",
        base_origin="https://api.anthropic.com/v1",
        wire="anthropic-messages",
        auth="anthropic",
        models_path="models",
    ),
    "gemini": CustomProvider(
        provider_id="gemini",
        display_name="Google Gemini",
        base_origin="https://generativelanguage.googleapis.com/v1beta",
        wire="google-generate-content",
        auth="google",
        models_path="models",
    ),
}

DEFAULT_CUSTOM_PROVIDER = "opencode-go"


def validate_custom_model_id(value: Any) -> str:
    if not isinstance(value, str):
        raise CustomProviderSelectionError(
            "PADIEM Custom 모델 ID 형식이 올바르지 않습니다."
        )
    model = value.strip()
    if not model or len(model) > MAX_CUSTOM_MODEL_CHARS or not _MODEL_ID.fullmatch(model):
        raise CustomProviderSelectionError(
            "PADIEM Custom 모델 ID 형식이 올바르지 않습니다."
        )
    return model


def resolve_custom_selection(provider_id: str, model_id: str) -> ResolvedCustomSelection:
    if not isinstance(provider_id, str) or not isinstance(model_id, str):
        raise CustomProviderSelectionError("지원하지 않는 PADIEM Custom 공급사/모델입니다.")
    spec = CUSTOM_PROVIDERS.get(provider_id.strip())
    if spec is None:
        raise CustomProviderSelectionError("지원하지 않는 PADIEM Custom 공급사입니다.")
    model = validate_custom_model_id(model_id)
    if not spec.accepts_model(model):
        raise CustomProviderSelectionError("지원하지 않는 PADIEM Custom 모델입니다.")
    return ResolvedCustomSelection(
        provider=spec,
        model_id=model,
        upstream_model=spec.upstream_model(model),
    )


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
        self._endpoint_column: bool | None = None

    @staticmethod
    def _legacy_aad(user_id: str, provider_id: str) -> bytes:
        return f"padiem-custom:{user_id}:{provider_id}".encode("utf-8")

    @staticmethod
    def _endpoint_aad(user_id: str, provider_id: str, endpoint: str) -> bytes:
        return (
            f"padiem-custom:v3:{user_id}:{provider_id}:{endpoint}".encode("utf-8")
        )

    @classmethod
    def _aad(
        cls, user_id: str, provider_id: str, endpoint: str, default_endpoint: str
    ) -> bytes:
        if endpoint == default_endpoint:
            return cls._legacy_aad(user_id, provider_id)
        return cls._endpoint_aad(user_id, provider_id, endpoint)

    async def _has_endpoint_column(self) -> bool:
        if self._endpoint_column is None:
            try:
                rows = await self.db.prepare(
                    "PRAGMA table_info(chat_custom_provider_credentials)"
                ).all()
                self._endpoint_column = any(
                    (_row(row) or {}).get("name") == "endpoint" for row in rows or []
                )
            except Exception:
                self._endpoint_column = False
        return self._endpoint_column

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
        endpoint: str | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("canonical owner required")
        spec = CUSTOM_PROVIDERS.get(provider_id)
        if spec is None:
            raise ValueError("unsupported custom provider")
        key = validate_custom_api_key(api_key)
        try:
            effective_endpoint = normalize_custom_endpoint(
                endpoint, default_endpoint=spec.base_origin
            )
        except CustomEndpointError:
            raise
        supports_endpoint = await self._has_endpoint_column()
        if effective_endpoint != spec.base_origin and not supports_endpoint:
            raise CustomEndpointStorageUnavailable(
                "custom endpoint storage is not available"
            )
        timestamp = int(time.time() if now is None else now)
        iv = self.cipher.random_bytes(12)
        plaintext = json.dumps(
            {"api_key": key}, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        aad = self._aad(
            user_id, provider_id, effective_endpoint, spec.base_origin
        )
        ciphertext = await self.cipher.encrypt(
            key=self.key,
            iv=iv,
            plaintext=plaintext,
            additional_data=aad,
        )
        sealed = base64.b64encode(iv + ciphertext).decode("ascii")
        if supports_endpoint:
            await self._run(
                """INSERT INTO chat_custom_provider_credentials
                    (user_id,provider_id,key_last4,sealed_credential,endpoint,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(user_id,provider_id) DO UPDATE SET
                    key_last4=excluded.key_last4,
                    sealed_credential=excluded.sealed_credential,
                    endpoint=excluded.endpoint,
                    updated_at=excluded.updated_at""",
                user_id,
                provider_id,
                key[-4:],
                sealed,
                effective_endpoint,
                timestamp,
                timestamp,
            )
        else:
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
            "endpoint": effective_endpoint,
            "endpoint_is_default": effective_endpoint == spec.base_origin,
            "updated_at": timestamp,
        }

    async def credential(
        self, user_id: str, provider_id: str
    ) -> tuple[str, str] | None:
        """Return ``(api_key, effective_endpoint)`` for one owner/provider."""
        if not isinstance(user_id, str) or not user_id:
            return None
        spec = CUSTOM_PROVIDERS.get(provider_id)
        if spec is None:
            return None
        supports_endpoint = await self._has_endpoint_column()
        if supports_endpoint:
            row = await self._first(
                "SELECT sealed_credential,endpoint FROM chat_custom_provider_credentials "
                "WHERE user_id=? AND provider_id=?",
                user_id,
                provider_id,
            )
        else:
            row = await self._first(
                "SELECT sealed_credential FROM chat_custom_provider_credentials "
                "WHERE user_id=? AND provider_id=?",
                user_id,
                provider_id,
            )
        if not row:
            return None
        stored_endpoint = row.get("endpoint") if supports_endpoint else None
        try:
            endpoint = normalize_custom_endpoint(
                stored_endpoint, default_endpoint=spec.base_origin
            )
        except CustomEndpointError:
            raise CustomCredentialDecryptionError(
                "PADIEM Custom credential endpoint is invalid"
            ) from None
        api_key = await self._decrypt_and_reseal(
            row["sealed_credential"],
            user_id,
            provider_id,
            endpoint,
            spec.base_origin,
            supports_endpoint,
        )
        return api_key, endpoint

    async def api_key(self, user_id: str, provider_id: str) -> str | None:
        credential = await self.credential(user_id, provider_id)
        return credential[0] if credential else None

    async def _decrypt_and_reseal(
        self,
        sealed: Any,
        user_id: str,
        provider_id: str,
        endpoint: str,
        default_endpoint: str,
        supports_endpoint: bool,
    ) -> str:
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

        current_aad = self._aad(user_id, provider_id, endpoint, default_endpoint)

        value: str | None = None
        matched_current = False
        for key in self._decryption_keys:
            try:
                plaintext = await self.cipher.decrypt(
                    key=key,
                    iv=data[:12],
                    ciphertext=data[12:],
                    additional_data=current_aad,
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

        # A custom-endpoint row is sealed under the endpoint-bound AAD. The
        # default endpoint intentionally uses the legacy AAD so pre-058 rows
        # stay readable, and that is the only AAD ever offered there.
        if not matched_current:
            await self._reseal(
                sealed,
                value,
                user_id,
                provider_id,
                current_aad,
                endpoint if supports_endpoint else None,
            )
        return value

    async def _reseal(
        self,
        previous_sealed: Any,
        api_key: str,
        user_id: str,
        provider_id: str,
        aad: bytes,
        endpoint: str | None,
    ) -> None:
        """Move one row to the current key/AAD without changing its metadata.

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
            if endpoint is None:
                await self._run(
                    """UPDATE chat_custom_provider_credentials
                       SET sealed_credential=?
                       WHERE user_id=? AND provider_id=? AND sealed_credential=?""",
                    sealed,
                    user_id,
                    provider_id,
                    previous_sealed,
                )
            else:
                await self._run(
                    """UPDATE chat_custom_provider_credentials
                       SET sealed_credential=?, endpoint=?
                       WHERE user_id=? AND provider_id=? AND sealed_credential=?""",
                    sealed,
                    endpoint,
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
        supports_endpoint = await self._has_endpoint_column()
        columns = "provider_id,key_last4,created_at,updated_at"
        if supports_endpoint:
            columns += ",endpoint"
        rows = await self.db.prepare(
            f"SELECT {columns} FROM chat_custom_provider_credentials "
            "WHERE user_id=? ORDER BY provider_id"
        ).bind(user_id).all()
        result = []
        for value in rows or []:
            row = _row(value)
            spec = (
                CUSTOM_PROVIDERS.get(row.get("provider_id"))
                if isinstance(row, dict) else None
            )
            if row is None or spec is None:
                continue
            stored_endpoint = row.get("endpoint") if supports_endpoint else None
            try:
                endpoint = normalize_custom_endpoint(
                    stored_endpoint, default_endpoint=spec.base_origin
                )
            except CustomEndpointError:
                continue
            result.append(
                {
                    "provider": row["provider_id"],
                    "key_last4": row["key_last4"],
                    "endpoint": endpoint,
                    "endpoint_is_default": endpoint == spec.base_origin,
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
