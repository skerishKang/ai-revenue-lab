from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Any, Protocol

from padiem_control_plane.contracts import ControlPlaneContractError


SEALED_ENVELOPE_PREFIX = "sealed:v1:"
AES_GCM_KEY_BYTES = 32
AES_GCM_IV_BYTES = 12
AES_GCM_TAG_BYTES = 16
MAX_SEALED_PLAINTEXT_BYTES = 131_072
MAX_SEALED_PAYLOAD_BYTES = AES_GCM_IV_BYTES + MAX_SEALED_PLAINTEXT_BYTES + AES_GCM_TAG_BYTES

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_KEY_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_ENVELOPE_RE = re.compile(r"^sealed:v1:[A-Za-z0-9_-]+$")
_REVIEWED_CONNECTORS = frozenset({"gmail", "google-drive"})


class GoogleOAuthSealPurpose(str, Enum):
    AUTHORIZATION_SESSION = "authorization-session"
    REFRESH_TOKEN = "refresh-token"


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_google_oauth_seal_context",
            f"{field_name} must be a bounded safe reference",
        )
    return value


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str, *, field_name: str, max_bytes: int) -> bytes:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ControlPlaneContractError(
            "invalid_google_oauth_sealed_envelope",
            f"{field_name} must be bounded base64url text",
        )
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ControlPlaneContractError(
            "invalid_google_oauth_sealed_envelope",
            f"{field_name} must be valid base64url",
        ) from exc
    if not decoded or len(decoded) > max_bytes:
        raise ControlPlaneContractError(
            "invalid_google_oauth_sealed_envelope",
            f"{field_name} exceeds the trusted bound",
        )
    return decoded


def decode_worker_seal_key(secret_b64url: str) -> bytes:
    """Decode one 256-bit Worker secret without deriving weaker key material.

    The production secret is expected to be an unpadded base64url encoding of
    exactly 32 random bytes.  This function never returns a printable key
    projection and callers must not log the returned bytes.
    """

    if not isinstance(secret_b64url, str) or not _KEY_SECRET_RE.fullmatch(secret_b64url):
        raise ControlPlaneContractError(
            "invalid_google_oauth_seal_key",
            "Google OAuth seal key secret must encode exactly 32 random bytes",
        )
    padding = "=" * (-len(secret_b64url) % 4)
    try:
        key = base64.b64decode(secret_b64url + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ControlPlaneContractError(
            "invalid_google_oauth_seal_key",
            "Google OAuth seal key secret is not valid base64url",
        ) from exc
    if len(key) != AES_GCM_KEY_BYTES:
        raise ControlPlaneContractError(
            "invalid_google_oauth_seal_key",
            "Google OAuth seal key secret must decode to 256 bits",
        )
    return key


def _bounded_plaintext(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ControlPlaneContractError(
            "invalid_google_oauth_seal_plaintext",
            "Google OAuth sealed plaintext must be non-empty text",
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ControlPlaneContractError(
            "invalid_google_oauth_seal_plaintext",
            "Google OAuth sealed plaintext must be valid UTF-8 text",
        ) from exc
    if len(encoded) > MAX_SEALED_PLAINTEXT_BYTES:
        raise ControlPlaneContractError(
            "invalid_google_oauth_seal_plaintext",
            "Google OAuth sealed plaintext exceeds the trusted bound",
        )
    return encoded


@dataclass(frozen=True, slots=True)
class GoogleOAuthSealContext:
    purpose: GoogleOAuthSealPurpose
    connector_id: str
    record_ref: str
    actor_ref: str
    account_ref: str
    workspace_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, GoogleOAuthSealPurpose):
            raise ControlPlaneContractError(
                "invalid_google_oauth_seal_context",
                "purpose must be GoogleOAuthSealPurpose",
            )
        for field_name in (
            "connector_id",
            "record_ref",
            "actor_ref",
            "account_ref",
            "workspace_ref",
        ):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        if self.connector_id not in _REVIEWED_CONNECTORS:
            raise ControlPlaneContractError(
                "invalid_google_oauth_seal_context",
                "connector_id is not a reviewed Google readonly connector",
            )

    def aad_bytes(self) -> bytes:
        return json.dumps(
            {
                "version": "v1",
                "purpose": self.purpose.value,
                "connector_id": self.connector_id,
                "record_ref": self.record_ref,
                "actor_ref": self.actor_ref,
                "account_ref": self.account_ref,
                "workspace_ref": self.workspace_ref,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "version": "v1",
            "purpose": self.purpose.value,
            "connector_id": self.connector_id,
            "record_ref": self.record_ref,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "aad_bound": True,
            "raw_key": False,
            "raw_plaintext": False,
        }


class AesGcmWebCryptoPort(Protocol):
    def random_bytes(self, length: int) -> bytes:
        ...

    async def encrypt(
        self,
        *,
        key: bytes,
        iv: bytes,
        plaintext: bytes,
        additional_data: bytes,
    ) -> bytes:
        ...

    async def decrypt(
        self,
        *,
        key: bytes,
        iv: bytes,
        ciphertext: bytes,
        additional_data: bytes,
    ) -> bytes:
        ...


class CloudflareWorkerWebCryptoAesGcmPort:
    """Cloudflare Python Worker FFI adapter for ``crypto.subtle`` AES-GCM.

    Imports of ``js`` and ``pyodide`` are deliberately lazy so this module can
    be imported by ordinary CPython contract tests.  In a real Python Worker,
    Cloudflare exposes JavaScript globals and Runtime APIs through Pyodide FFI.
    """

    @staticmethod
    def _ffi():
        try:
            from js import Object, Uint8Array, crypto  # type: ignore[import-not-found]
            from pyodide.ffi import to_js  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Cloudflare Python Worker WebCrypto FFI is unavailable") from exc
        return Object, Uint8Array, crypto, to_js

    @classmethod
    def _uint8(cls, value: bytes):
        _, Uint8Array, _, to_js = cls._ffi()
        return Uint8Array.new(to_js(list(value)))

    @classmethod
    def _algorithm(cls, *, iv: bytes, additional_data: bytes):
        Object, _, _, to_js = cls._ffi()
        return to_js(
            {
                "name": "AES-GCM",
                "iv": cls._uint8(iv),
                "additionalData": cls._uint8(additional_data),
                "tagLength": 128,
            },
            dict_converter=Object.fromEntries,
        )

    @classmethod
    async def _key(cls, key: bytes):
        Object, _, crypto, to_js = cls._ffi()
        algorithm = to_js({"name": "AES-GCM"}, dict_converter=Object.fromEntries)
        usages = to_js(["encrypt", "decrypt"])
        return await crypto.subtle.importKey(
            "raw",
            cls._uint8(key),
            algorithm,
            False,
            usages,
        )

    def random_bytes(self, length: int) -> bytes:
        if isinstance(length, bool) or not isinstance(length, int) or not 1 <= length <= 1024:
            raise ValueError("random byte length is outside the trusted bound")
        _, Uint8Array, crypto, _ = self._ffi()
        buffer = Uint8Array.new(length)
        crypto.getRandomValues(buffer)
        return bytes(buffer.to_py())

    async def encrypt(
        self,
        *,
        key: bytes,
        iv: bytes,
        plaintext: bytes,
        additional_data: bytes,
    ) -> bytes:
        _, Uint8Array, crypto, _ = self._ffi()
        crypto_key = await self._key(key)
        result = await crypto.subtle.encrypt(
            self._algorithm(iv=iv, additional_data=additional_data),
            crypto_key,
            self._uint8(plaintext),
        )
        return bytes(Uint8Array.new(result).to_py())

    async def decrypt(
        self,
        *,
        key: bytes,
        iv: bytes,
        ciphertext: bytes,
        additional_data: bytes,
    ) -> bytes:
        _, Uint8Array, crypto, _ = self._ffi()
        crypto_key = await self._key(key)
        result = await crypto.subtle.decrypt(
            self._algorithm(iv=iv, additional_data=additional_data),
            crypto_key,
            self._uint8(ciphertext),
        )
        return bytes(Uint8Array.new(result).to_py())

    def safe_dict(self) -> dict[str, Any]:
        return {
            "cloudflare_python_worker_ffi": True,
            "webcrypto_subtle": True,
            "algorithm": "AES-GCM-256",
            "iv_bytes": AES_GCM_IV_BYTES,
            "tag_bits": 128,
            "key_extractable": False,
            "raw_key_public": False,
        }


class GoogleOAuthWebCryptoSealer:
    """Versioned AEAD sealing boundary for OAuth state and refresh tokens."""

    def __init__(
        self,
        *,
        key_secret_b64url: str,
        crypto_port: AesGcmWebCryptoPort | None = None,
    ) -> None:
        self._key = decode_worker_seal_key(key_secret_b64url)
        self._crypto = crypto_port or CloudflareWorkerWebCryptoAesGcmPort()

    async def seal_text(self, *, plaintext: str, context: GoogleOAuthSealContext) -> str:
        if not isinstance(context, GoogleOAuthSealContext):
            raise ControlPlaneContractError(
                "invalid_google_oauth_seal_context",
                "context must be GoogleOAuthSealContext",
            )
        plaintext_bytes = _bounded_plaintext(plaintext)
        iv = self._crypto.random_bytes(AES_GCM_IV_BYTES)
        if not isinstance(iv, bytes) or len(iv) != AES_GCM_IV_BYTES:
            raise RuntimeError("WebCrypto port returned an invalid AES-GCM IV")
        try:
            ciphertext = await self._crypto.encrypt(
                key=self._key,
                iv=iv,
                plaintext=plaintext_bytes,
                additional_data=context.aad_bytes(),
            )
        except Exception as exc:
            raise ControlPlaneContractError(
                "google_oauth_seal_failed",
                "Google OAuth sensitive material could not be sealed",
            ) from exc
        if (
            not isinstance(ciphertext, bytes)
            or len(ciphertext) < AES_GCM_TAG_BYTES + 1
            or len(ciphertext) > MAX_SEALED_PLAINTEXT_BYTES + AES_GCM_TAG_BYTES
        ):
            raise RuntimeError("WebCrypto port returned invalid AES-GCM ciphertext")
        return SEALED_ENVELOPE_PREFIX + _b64url_encode(iv + ciphertext)

    async def unseal_text(self, *, envelope: str, context: GoogleOAuthSealContext) -> str:
        if not isinstance(context, GoogleOAuthSealContext):
            raise ControlPlaneContractError(
                "invalid_google_oauth_seal_context",
                "context must be GoogleOAuthSealContext",
            )
        if not isinstance(envelope, str) or not _ENVELOPE_RE.fullmatch(envelope):
            raise ControlPlaneContractError(
                "invalid_google_oauth_sealed_envelope",
                "Google OAuth sealed envelope is invalid",
            )
        payload = _b64url_decode(
            envelope[len(SEALED_ENVELOPE_PREFIX) :],
            field_name="sealed envelope payload",
            max_bytes=MAX_SEALED_PAYLOAD_BYTES,
        )
        if len(payload) < AES_GCM_IV_BYTES + AES_GCM_TAG_BYTES + 1:
            raise ControlPlaneContractError(
                "invalid_google_oauth_sealed_envelope",
                "Google OAuth sealed envelope is too short",
            )
        iv = payload[:AES_GCM_IV_BYTES]
        ciphertext = payload[AES_GCM_IV_BYTES:]
        try:
            plaintext = await self._crypto.decrypt(
                key=self._key,
                iv=iv,
                ciphertext=ciphertext,
                additional_data=context.aad_bytes(),
            )
        except Exception as exc:
            raise ControlPlaneContractError(
                "google_oauth_unseal_failed",
                "Google OAuth sealed material failed integrity verification",
            ) from exc
        if not isinstance(plaintext, bytes) or not plaintext:
            raise ControlPlaneContractError(
                "google_oauth_unseal_failed",
                "Google OAuth sealed material decrypted to an invalid payload",
            )
        try:
            text = plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ControlPlaneContractError(
                "google_oauth_unseal_failed",
                "Google OAuth sealed material is not valid UTF-8 text",
            ) from exc
        _bounded_plaintext(text)
        return text

    def safe_dict(self) -> dict[str, Any]:
        port_safe = getattr(self._crypto, "safe_dict", None)
        return {
            "sealed_envelope": "sealed:v1",
            "algorithm": "AES-GCM-256",
            "aad_context_bound": True,
            "worker_secret_key_required": True,
            "worker_secret_is_kms": False,
            "raw_key_public": False,
            "raw_plaintext_public": False,
            "raw_refresh_token_public": False,
            "crypto_port": port_safe() if callable(port_safe) else {"test_port": True},
            "production_deployment": False,
            "production_ready": False,
        }


WORKER_WEBCRYPTO_SEALER_SOURCE_READY = True
WORKER_SECRET_IS_KMS = False
SEALED_ENVELOPE_VERSION = "v1"
PUBLIC_OAUTH_ROUTE_ADDED = False
PRODUCTION_MUTATION = False
