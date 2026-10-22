"""#5034 — Web Push delivery over the Worker's own WebCrypto.

This module is the *sender* half of the existing push seam in
:mod:`app.claw_push_subscriptions`. It adds no inbox, no alert record and no
second notification authority: it takes the title/body/url the existing
terminal-run projection already produced and attempts to reach the devices the
user opted in.

Why WebCrypto and not a library
-------------------------------
The Chat Worker is a Pyodide build whose committed lock carries no
``cryptography`` wheel, so ``pywebpush``/``py-vapid`` cannot be imported there.
Workers do expose ``crypto.subtle``, and this repository already uses it through
Pyodide FFI (:mod:`app.connector_worker_webcrypto_verify`). This module follows
that same reviewed pattern: the JS resources are imported only inside a real
Worker call, and every crypto operation goes through an injectable async port so
the protocol can be tested without a Worker.

Protocols implemented (both are small and fully specified)
----------------------------------------------------------
* RFC 8291 ``aes128gcm`` payload encryption (ECDH P-256 + HKDF-SHA256 + AES-128-GCM).
* RFC 8292 VAPID: an ES256 JWT in ``Authorization: vapid t=...,k=...``.

Invariants
----------
* ``INBOX_STATE_NEVER_CHANGED_BY_PUSH`` — nothing here writes a task or alert.
* ``NO_ENDPOINT_IN_LOG`` — the endpoint is a device capability URL; it is never
  logged, and error text carries only a status code.
* ``MINIMAL_LOCK_SCREEN`` — the payload is a short status plus a result link.
  The caller supplies it; this module never adds document content.
* ``GONE_SUBSCRIPTION_IS_REMOVED`` — 404/410 from the push service means the
  device is gone, and the caller is told to drop the row.
* ``PUSH_FAILURE_IS_NOT_A_JOB_FAILURE`` — every failure is reported as a
  delivery outcome, never raised into the automation path.
"""

from __future__ import annotations

import base64
import inspect
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

# RFC 8291 §4: one record, 4096-byte record size, 16-byte salt, 65-byte key id.
_RECORD_SIZE = 4096
_SALT_BYTES = 16
_PUBLIC_KEY_BYTES = 65
_AUTH_SECRET_BYTES = 16
_CEK_BYTES = 16
_NONCE_BYTES = 12

# RFC 8291 §3.4 / §3.5 info strings.
_KEY_INFO_PREFIX = b"WebPush: info\x00"
_CEK_INFO = b"Content-Encoding: aes128gcm\x00"
_NONCE_INFO = b"Content-Encoding: nonce\x00"

# RFC 8292 §2: the JWT audience is the push service origin, valid for < 24h.
_VAPID_TOKEN_TTL_SECONDS = 12 * 60 * 60

# The last-record delimiter for a single-record aes128gcm body (RFC 8188 §2).
_LAST_RECORD_DELIMITER = b"\x02"

MAX_PUSH_PAYLOAD_BYTES = 2048


class PushSendError(RuntimeError):
    """A bounded, non-secret-bearing push send failure."""


@dataclass(frozen=True, slots=True)
class VapidAuthority:
    """The VAPID key pair and contact subject for one deployment.

    ``private_key`` is the raw 32-byte P-256 scalar and ``public_key`` the
    65-byte uncompressed point, both base64url as the Web Push ecosystem
    exchanges them. Neither value is ever logged or returned to a browser; the
    public half is the only part the capability route exposes.
    """

    private_key: str
    public_key: str
    subject: str


class PushCryptoPort(Protocol):
    """The exact async crypto surface the protocol needs.

    Implemented for real by :class:`WorkerWebCrypto`; tests inject a fake so the
    RFC 8291/8292 composition is verified without a Worker runtime.
    """

    async def random_bytes(self, length: int) -> bytes: ...

    async def ecdh_public_key(self) -> bytes: ...

    async def ecdh_shared_secret(self, peer_public_key: bytes) -> bytes: ...

    async def hkdf_sha256(
        self, *, salt: bytes, ikm: bytes, info: bytes, length: int
    ) -> bytes: ...

    async def aes128gcm_encrypt(
        self, *, key: bytes, nonce: bytes, plaintext: bytes
    ) -> bytes: ...

    async def es256_sign(self, *, signing_input: bytes) -> bytes: ...


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _endpoint_origin(endpoint: str) -> str:
    """The VAPID audience: scheme + host of the push endpoint, never the path."""

    marker = endpoint.find("://")
    if marker < 0:
        raise PushSendError("push endpoint is not an absolute URL")
    rest = endpoint[marker + 3 :]
    slash = rest.find("/")
    host = rest if slash < 0 else rest[:slash]
    if not host:
        raise PushSendError("push endpoint has no host")
    return endpoint[: marker + 3] + host


async def build_vapid_authorization(
    *,
    authority: VapidAuthority,
    endpoint: str,
    crypto: PushCryptoPort,
    now: int | None = None,
) -> str:
    """Build the RFC 8292 ``Authorization`` header value for one endpoint."""

    issued = int(time.time()) if now is None else int(now)
    header = _b64url_encode(
        json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode("utf-8")
    )
    claims = _b64url_encode(
        json.dumps(
            {
                "aud": _endpoint_origin(endpoint),
                "exp": issued + _VAPID_TOKEN_TTL_SECONDS,
                "sub": authority.subject,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = f"{header}.{claims}".encode("ascii")
    signature = await crypto.es256_sign(signing_input=signing_input)
    if len(signature) != 64:
        raise PushSendError("ES256 signature must be 64 raw bytes")
    return f"vapid t={header}.{claims}.{_b64url_encode(signature)},k={authority.public_key}"


async def encrypt_payload(
    *,
    plaintext: bytes,
    ua_public_key: bytes,
    auth_secret: bytes,
    crypto: PushCryptoPort,
) -> bytes:
    """Encrypt one push payload as an RFC 8291 ``aes128gcm`` body."""

    if len(ua_public_key) != _PUBLIC_KEY_BYTES:
        raise PushSendError("user-agent public key must be 65 bytes")
    if len(auth_secret) != _AUTH_SECRET_BYTES:
        raise PushSendError("auth secret must be 16 bytes")
    if len(plaintext) > MAX_PUSH_PAYLOAD_BYTES:
        raise PushSendError("push payload is too large")

    as_public_key = await crypto.ecdh_public_key()
    if len(as_public_key) != _PUBLIC_KEY_BYTES:
        raise PushSendError("application-server public key must be 65 bytes")

    ecdh_secret = await crypto.ecdh_shared_secret(ua_public_key)

    # RFC 8291 §3.4: the input keying material for the content encryption keys.
    prk_key = await crypto.hkdf_sha256(
        salt=auth_secret,
        ikm=ecdh_secret,
        info=_KEY_INFO_PREFIX + ua_public_key + as_public_key,
        length=32,
    )
    salt = await crypto.random_bytes(_SALT_BYTES)
    prk = await crypto.hkdf_sha256(salt=salt, ikm=prk_key, info=b"", length=32)
    cek = await crypto.hkdf_sha256(salt=salt, ikm=prk, info=_CEK_INFO, length=_CEK_BYTES)
    nonce = await crypto.hkdf_sha256(
        salt=salt, ikm=prk, info=_NONCE_INFO, length=_NONCE_BYTES
    )

    ciphertext = await crypto.aes128gcm_encrypt(
        key=cek, nonce=nonce, plaintext=plaintext + _LAST_RECORD_DELIMITER
    )

    # RFC 8188 §2.1 header: salt | rs | idlen | keyid, then the single record.
    return (
        salt
        + _RECORD_SIZE.to_bytes(4, "big")
        + bytes([len(as_public_key)])
        + as_public_key
        + ciphertext
    )


def build_push_payload(*, title: str, body: str, url: str | None, tag: str) -> bytes:
    """The minimum a lock screen may show: a short status and a result link."""

    payload: dict[str, str] = {
        "title": title[:120],
        "body": body[:200],
        "tag": tag[:64],
    }
    if url:
        payload["url"] = url
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class PushSendResult:
    """One delivery attempt's outcome. Never carries the endpoint."""

    delivered: bool
    status_code: int | None = None
    gone: bool = False
    reason: str = ""


class WebPushSender:
    """Send one push to one subscription over an injected HTTP transport.

    ``transport`` is the existing bounded fetch used by this Worker
    (``httpx_compat``); it is injected so this module owns no network client.
    """

    def __init__(
        self,
        *,
        authority: VapidAuthority | None,
        crypto_factory: Callable[[], PushCryptoPort] | None = None,
        transport: Any | None = None,
        now: Callable[[], int] | None = None,
    ) -> None:
        self._authority = authority
        self._crypto_factory = crypto_factory or WorkerWebCrypto
        self._transport = transport
        self._now = now or (lambda: int(time.time()))

    @property
    def configured(self) -> bool:
        return self._authority is not None and self._transport is not None

    async def send(
        self, *, subscription: Any, title: str, body: str, url: str | None = None
    ) -> PushSendResult:
        """Attempt one push. Never raises: a failure is a reported outcome."""

        if not self.configured:
            return PushSendResult(delivered=False, reason="not_configured")
        try:
            endpoint = getattr(subscription, "endpoint", "")
            p256dh = getattr(subscription, "p256dh", "")
            auth = getattr(subscription, "auth", "")
            if not endpoint or not p256dh or not auth:
                return PushSendResult(delivered=False, reason="invalid_subscription")
            crypto = self._crypto_factory()
            payload = build_push_payload(
                title=title,
                body=body,
                url=url,
                tag=getattr(subscription, "subscription_id", "") or "padiem-task",
            )
            encrypted = await encrypt_payload(
                plaintext=payload,
                ua_public_key=_b64url_decode(p256dh),
                auth_secret=_b64url_decode(auth),
                crypto=crypto,
            )
            authorization = await build_vapid_authorization(
                authority=self._authority,
                endpoint=endpoint,
                crypto=crypto,
                now=self._now(),
            )
        except PushSendError as exc:
            return PushSendResult(delivered=False, reason=str(exc))
        except Exception:
            # No endpoint, key or stack frame in the reported reason.
            return PushSendResult(delivered=False, reason="crypto_failed")

        try:
            status = await self._post(endpoint, encrypted, authorization)
        except Exception:
            return PushSendResult(delivered=False, reason="transport_failed")

        if 200 <= status < 300:
            return PushSendResult(delivered=True, status_code=status)
        if status in (404, 410):
            # The device is gone; the caller drops the row.
            return PushSendResult(
                delivered=False, status_code=status, gone=True, reason="gone"
            )
        return PushSendResult(
            delivered=False, status_code=status, reason=f"push_service_{status}"
        )

    async def _post(self, endpoint: str, body: bytes, authorization: str) -> int:
        result = self._transport.post(
            endpoint,
            content=body,
            headers={
                "Authorization": authorization,
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": "3600",
                "Urgency": "normal",
            },
        )
        if inspect.isawaitable(result):
            result = await result
        return int(getattr(result, "status_code", 0))


class WorkerWebCrypto:
    """The real crypto port: Workers' ``crypto.subtle`` through Pyodide FFI.

    JS resources are imported only inside a real Worker call, exactly like
    :mod:`app.connector_worker_webcrypto_verify`. Outside a Worker every method
    raises, and the sender reports ``crypto_failed`` instead of pretending to
    deliver.
    """

    def __init__(self, *, private_key: str | None = None) -> None:
        self._private_key = private_key
        self._key_pair: Any | None = None

    @staticmethod
    def _runtime() -> tuple[Any, Any, Any]:
        from js import crypto, Uint8Array  # type: ignore[import-not-found]
        from pyodide.ffi import to_js  # type: ignore[import-not-found]

        return crypto.subtle, Uint8Array, to_js

    @staticmethod
    def _to_js_bytes(data: bytes, factory: Any) -> Any:
        out = factory.new(len(data))
        for index, byte in enumerate(data):
            out[index] = byte
        return out

    @staticmethod
    def _to_py_bytes(value: Any) -> bytes:
        return bytes(value.to_py() if hasattr(value, "to_py") else value)

    async def _import_private_key(self) -> Any:
        if self._key_pair is not None:
            return self._key_pair
        if not self._private_key:
            raise PushSendError("no VAPID private key is configured")
        subtle, uint8_factory, to_js = self._runtime()
        raw = _b64url_decode(self._private_key)
        if len(raw) != 32:
            raise PushSendError("VAPID private key must be 32 bytes")
        # A raw P-256 scalar is imported as a JWK so WebCrypto can use it for
        # both ECDH (as the application-server key) and ES256 signing.
        jwk = {
            "kty": "EC",
            "crv": "P-256",
            "d": _b64url_encode(raw),
            "x": "",
            "y": "",
        }
        self._key_pair = await subtle.importKey(
            "jwk", to_js(jwk), to_js({"name": "ECDSA", "namedCurve": "P-256"}), False, to_js(["sign"])
        )
        return self._key_pair

    async def random_bytes(self, length: int) -> bytes:
        subtle, uint8_factory, _to_js = self._runtime()
        value = subtle.getRandomValues(uint8_factory.new(length))
        return self._to_py_bytes(value)

    async def ecdh_public_key(self) -> bytes:
        subtle, uint8_factory, to_js = self._runtime()
        pair = await subtle.generateKey(
            to_js({"name": "ECDH", "namedCurve": "P-256"}), True, to_js(["deriveBits"])
        )
        self._ecdh_pair = pair
        exported = await subtle.exportKey("raw", pair.publicKey)
        return self._to_py_bytes(exported)

    async def ecdh_shared_secret(self, peer_public_key: bytes) -> bytes:
        subtle, uint8_factory, to_js = self._runtime()
        pair = getattr(self, "_ecdh_pair", None)
        if pair is None:
            raise PushSendError("no ephemeral ECDH key pair")
        peer = await subtle.importKey(
            "raw",
            self._to_js_bytes(peer_public_key, uint8_factory),
            to_js({"name": "ECDH", "namedCurve": "P-256"}),
            False,
            to_js([]),
        )
        derived = await subtle.deriveBits(
            to_js({"name": "ECDH", "public": peer}), pair.privateKey, 256
        )
        return self._to_py_bytes(derived)

    async def hkdf_sha256(
        self, *, salt: bytes, ikm: bytes, info: bytes, length: int
    ) -> bytes:
        subtle, uint8_factory, to_js = self._runtime()
        base = await subtle.importKey(
            "raw", self._to_js_bytes(ikm, uint8_factory), "HKDF", False, to_js(["deriveBits"])
        )
        derived = await subtle.deriveBits(
            to_js(
                {
                    "name": "HKDF",
                    "hash": "SHA-256",
                    "salt": self._to_js_bytes(salt, uint8_factory),
                    "info": self._to_js_bytes(info, uint8_factory),
                }
            ),
            base,
            length * 8,
        )
        return self._to_py_bytes(derived)

    async def aes128gcm_encrypt(
        self, *, key: bytes, nonce: bytes, plaintext: bytes
    ) -> bytes:
        subtle, uint8_factory, to_js = self._runtime()
        imported = await subtle.importKey(
            "raw", self._to_js_bytes(key, uint8_factory), "AES-GCM", False, to_js(["encrypt"])
        )
        encrypted = await subtle.encrypt(
            to_js(
                {
                    "name": "AES-GCM",
                    "iv": self._to_js_bytes(nonce, uint8_factory),
                    "tagLength": 128,
                }
            ),
            imported,
            self._to_js_bytes(plaintext, uint8_factory),
        )
        return self._to_py_bytes(encrypted)

    async def es256_sign(self, *, signing_input: bytes) -> bytes:
        subtle, uint8_factory, to_js = self._runtime()
        key = await self._import_private_key()
        signature = await subtle.sign(
            to_js({"name": "ECDSA", "hash": "SHA-256"}),
            key,
            self._to_js_bytes(signing_input, uint8_factory),
        )
        return self._to_py_bytes(signature)


__all__ = [
    "MAX_PUSH_PAYLOAD_BYTES",
    "PushCryptoPort",
    "PushSendError",
    "PushSendResult",
    "VapidAuthority",
    "WebPushSender",
    "WorkerWebCrypto",
    "build_push_payload",
    "build_vapid_authorization",
    "encrypt_payload",
]
