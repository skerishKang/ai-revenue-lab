"""#5034 — Web Push sender protocol proof (RFC 8291 payload, RFC 8292 VAPID).

NETWORK_FREE. The point of this file is that the encryption is verified against
an INDEPENDENT decryptor, not against itself: the payload is encrypted by
:func:`app.claw_web_push_sender.encrypt_payload` and then decrypted by a
separate implementation written from RFC 8291 §3.3-§3.5 using ``cryptography``.
A round trip through the same code would prove nothing.

The ``cryptography`` package is a dev/test dependency only. The deployed Worker
lock carries no such wheel; the Worker uses ``crypto.subtle`` through
:class:`app.claw_web_push_sender.WorkerWebCrypto`.

Pinned here:

- RFC8291_ROUND_TRIP=PASS (a real user-agent key pair decrypts the body)
- RFC8291_HEADER=PASS (salt | rs | idlen | keyid layout and record size)
- RFC8291_AAD_EMPTY=PASS (aes128gcm uses no additional authenticated data)
- RFC8291_TAMPER_REJECTED=PASS (a modified ciphertext fails authentication)
- VAPID_JWT_VERIFIES=PASS (ES256 signature verifies against the public key)
- VAPID_AUDIENCE_IS_ORIGIN=PASS (the JWT aud is scheme+host, never the path)
- MINIMAL_PAYLOAD=PASS (only title/body/tag/url leave the server)
- GONE_SUBSCRIPTION=PASS (404/410 reports gone so the caller drops the row)
- PUSH_FAILURE_NEVER_RAISES=PASS (a failing transport is an outcome, not a crash)
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.claw_web_push_sender import (
    PushSendResult,
    VapidAuthority,
    WebPushSender,
    build_push_payload,
    build_vapid_authorization,
    encrypt_payload,
)

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _raw_public_key(private_key: ec.EllipticCurvePrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )


class CryptographyPort:
    """A real crypto port backed by ``cryptography`` (test-only)."""

    def __init__(self, signing_key: ec.EllipticCurvePrivateKey | None = None) -> None:
        self._ecdh = ec.generate_private_key(ec.SECP256R1())
        self._signing_key = signing_key

    async def random_bytes(self, length: int) -> bytes:
        import os

        return os.urandom(length)

    async def ecdh_public_key(self) -> bytes:
        return _raw_public_key(self._ecdh)

    async def ecdh_shared_secret(self, peer_public_key: bytes) -> bytes:
        peer = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), peer_public_key
        )
        return self._ecdh.exchange(ec.ECDH(), peer)

    async def hkdf_sha256(
        self, *, salt: bytes, ikm: bytes, info: bytes, length: int
    ) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(), length=length, salt=salt, info=info
        ).derive(ikm)

    async def aes128gcm_encrypt(
        self, *, key: bytes, nonce: bytes, plaintext: bytes
    ) -> bytes:
        return AESGCM(key).encrypt(nonce, plaintext, None)

    async def es256_sign(self, *, signing_input: bytes) -> bytes:
        from cryptography.hazmat.primitives.asymmetric.utils import (
            decode_dss_signature,
        )

        der = self._signing_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _decrypt_as_user_agent(
    *, body: bytes, ua_private_key: ec.EllipticCurvePrivateKey, auth_secret: bytes
) -> bytes:
    """Independent RFC 8291 §3.3-§3.5 decryption, written from the spec."""

    salt = body[:16]
    record_size = int.from_bytes(body[16:20], "big")
    id_length = body[20]
    key_id = body[21 : 21 + id_length]
    ciphertext = body[21 + id_length :]

    assert record_size == 4096, "single-record aes128gcm must declare rs=4096"
    assert id_length == 65, "the key id is the uncompressed application-server point"

    ua_public = _raw_public_key(ua_private_key)
    as_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), key_id)
    ecdh_secret = ua_private_key.exchange(ec.ECDH(), as_public)

    # §3.4: ikm = HKDF(auth_secret, ecdh_secret, "WebPush: info" || ua || as, 32)
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + ua_public + key_id,
    ).derive(ecdh_secret)

    # §3.5: PRK = HKDF(salt, ikm, "", 32); then CEK and NONCE from the PRK.
    prk = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"").derive(ikm)
    cek = HKDF(
        algorithm=hashes.SHA256(),
        length=16,
        salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(prk)
    nonce = HKDF(
        algorithm=hashes.SHA256(),
        length=12,
        salt=salt,
        info=b"Content-Encoding: nonce\x00",
    ).derive(prk)

    plaintext = AESGCM(cek).decrypt(nonce, ciphertext, None)
    # RFC 8188 §2: the last record carries the 0x02 delimiter.
    assert plaintext.endswith(b"\x02"), "last-record delimiter missing"
    return plaintext[:-1]


# --------------------------------------------------------------------------
# RFC 8291 payload encryption
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rfc8291_round_trip_with_real_user_agent_keys() -> None:
    ua_private = ec.generate_private_key(ec.SECP256R1())
    ua_public = _raw_public_key(ua_private)
    auth_secret = b"\x01" * 16
    message = b'{"title":"PADIEM","body":"done","tag":"t1","url":"/claw"}'

    body = await encrypt_payload(
        plaintext=message,
        ua_public_key=ua_public,
        auth_secret=auth_secret,
        crypto=CryptographyPort(),
    )

    recovered = _decrypt_as_user_agent(
        body=body, ua_private_key=ua_private, auth_secret=auth_secret
    )
    assert recovered == message


@pytest.mark.asyncio
async def test_rfc8291_header_layout() -> None:
    ua_private = ec.generate_private_key(ec.SECP256R1())
    body = await encrypt_payload(
        plaintext=b"x",
        ua_public_key=_raw_public_key(ua_private),
        auth_secret=b"\x02" * 16,
        crypto=CryptographyPort(),
    )
    assert len(body[:16]) == 16
    assert int.from_bytes(body[16:20], "big") == 4096
    assert body[20] == 65
    # header (16+4+1+65) + ciphertext(1 byte plaintext + 1 delimiter + 16 tag)
    assert len(body) == 86 + 18


@pytest.mark.asyncio
async def test_rfc8291_tampered_ciphertext_is_rejected() -> None:
    ua_private = ec.generate_private_key(ec.SECP256R1())
    auth_secret = b"\x03" * 16
    body = bytearray(
        await encrypt_payload(
            plaintext=b"payload",
            ua_public_key=_raw_public_key(ua_private),
            auth_secret=auth_secret,
            crypto=CryptographyPort(),
        )
    )
    body[-1] ^= 0xFF
    with pytest.raises(Exception):
        _decrypt_as_user_agent(
            body=bytes(body), ua_private_key=ua_private, auth_secret=auth_secret
        )


@pytest.mark.asyncio
async def test_encrypt_rejects_wrong_key_sizes() -> None:
    from app.claw_web_push_sender import PushSendError

    with pytest.raises(PushSendError):
        await encrypt_payload(
            plaintext=b"x",
            ua_public_key=b"\x00" * 10,
            auth_secret=b"\x00" * 16,
            crypto=CryptographyPort(),
        )
    with pytest.raises(PushSendError):
        await encrypt_payload(
            plaintext=b"x",
            ua_public_key=b"\x00" * 65,
            auth_secret=b"\x00" * 4,
            crypto=CryptographyPort(),
        )


# --------------------------------------------------------------------------
# RFC 8292 VAPID
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vapid_jwt_signature_verifies_against_public_key() -> None:
    signing_key = ec.generate_private_key(ec.SECP256R1())
    public_key = _b64url(_raw_public_key(signing_key))
    authority = VapidAuthority(
        private_key=_b64url(signing_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )),
        public_key=public_key,
        subject="mailto:ops@padiem.net",
    )

    header = await build_vapid_authorization(
        authority=authority,
        endpoint="https://fcm.googleapis.com/wp/abc123",
        crypto=CryptographyPort(signing_key),
        now=1_700_000_000,
    )

    assert header.startswith("vapid t=")
    token_part, key_part = header[len("vapid "):].split(",k=")
    token = token_part[len("t="):]
    assert key_part == public_key

    encoded_header, encoded_claims, encoded_signature = token.split(".")
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = _unb64url(encoded_signature)
    assert len(signature) == 64

    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    signing_key.public_key().verify(
        encode_dss_signature(r, s), signing_input, ec.ECDSA(hashes.SHA256())
    )

    claims = json.loads(_unb64url(encoded_claims))
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert claims["sub"] == "mailto:ops@padiem.net"
    assert claims["exp"] == 1_700_000_000 + 12 * 60 * 60


@pytest.mark.asyncio
async def test_vapid_audience_is_origin_not_path() -> None:
    signing_key = ec.generate_private_key(ec.SECP256R1())
    authority = VapidAuthority(
        private_key=_b64url(b"\x00" * 32),
        public_key=_b64url(_raw_public_key(signing_key)),
        subject="mailto:ops@padiem.net",
    )
    header = await build_vapid_authorization(
        authority=authority,
        endpoint="https://updates.push.services.mozilla.com/wpush/v2/secret-token",
        crypto=CryptographyPort(signing_key),
        now=1_700_000_000,
    )
    token = header[len("vapid t="):].split(",k=")[0]
    claims = json.loads(_unb64url(token.split(".")[1]))
    assert claims["aud"] == "https://updates.push.services.mozilla.com"
    assert "secret-token" not in claims["aud"]


# --------------------------------------------------------------------------
# payload shape and sender outcomes
# --------------------------------------------------------------------------


def test_payload_carries_only_the_minimum() -> None:
    payload = json.loads(
        build_push_payload(
            title="자동화 완료", body="작업이 완료되었습니다.", url="/claw/inbox", tag="t1"
        )
    )
    assert set(payload) == {"title", "body", "tag", "url"}
    # No document content, no identifiers beyond the result link.
    assert "endpoint" not in payload
    assert "workspace" not in payload


def test_payload_omits_url_when_absent() -> None:
    payload = json.loads(build_push_payload(title="t", body="b", url=None, tag="g"))
    assert "url" not in payload


class _FakeTransport:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> Any:
        self.calls.append({"url": url, "content": content, "headers": headers})
        return type("Response", (), {"status_code": self.status_code})()


class _Subscription:
    def __init__(self) -> None:
        ua_private = ec.generate_private_key(ec.SECP256R1())
        self.endpoint = "https://fcm.googleapis.com/wp/device-1"
        self.p256dh = _b64url(_raw_public_key(ua_private))
        self.auth = _b64url(b"\x04" * 16)
        self.subscription_id = "push_" + "a" * 32


def _sender(status_code: int) -> tuple[WebPushSender, _FakeTransport]:
    signing_key = ec.generate_private_key(ec.SECP256R1())
    authority = VapidAuthority(
        private_key=_b64url(b"\x00" * 32),
        public_key=_b64url(_raw_public_key(signing_key)),
        subject="mailto:ops@padiem.net",
    )
    transport = _FakeTransport(status_code)
    sender = WebPushSender(
        authority=authority,
        crypto_factory=lambda: CryptographyPort(signing_key),
        transport=transport,
        now=lambda: 1_700_000_000,
    )
    return sender, transport


@pytest.mark.asyncio
async def test_send_success_reports_delivered() -> None:
    sender, transport = _sender(201)
    result = await sender.send(
        subscription=_Subscription(), title="t", body="b", url="/claw"
    )
    assert result.delivered is True
    assert result.status_code == 201
    assert len(transport.calls) == 1
    headers = transport.calls[0]["headers"]
    assert headers["Content-Encoding"] == "aes128gcm"
    assert headers["Authorization"].startswith("vapid t=")


@pytest.mark.asyncio
async def test_gone_subscription_reports_gone() -> None:
    sender, _ = _sender(410)
    result = await sender.send(subscription=_Subscription(), title="t", body="b")
    assert result.delivered is False
    assert result.gone is True
    assert result.status_code == 410


@pytest.mark.asyncio
async def test_push_service_error_is_an_outcome_not_a_raise() -> None:
    sender, _ = _sender(500)
    result = await sender.send(subscription=_Subscription(), title="t", body="b")
    assert result.delivered is False
    assert result.gone is False
    assert result.reason == "push_service_500"


@pytest.mark.asyncio
async def test_unconfigured_sender_reports_not_configured() -> None:
    sender = WebPushSender(authority=None, transport=None)
    result = await sender.send(subscription=_Subscription(), title="t", body="b")
    assert result == PushSendResult(delivered=False, reason="not_configured")


@pytest.mark.asyncio
async def test_transport_exception_never_raises() -> None:
    class _Boom:
        async def post(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("network down")

    signing_key = ec.generate_private_key(ec.SECP256R1())
    sender = WebPushSender(
        authority=VapidAuthority(
            private_key=_b64url(b"\x00" * 32),
            public_key=_b64url(_raw_public_key(signing_key)),
            subject="mailto:ops@padiem.net",
        ),
        crypto_factory=lambda: CryptographyPort(signing_key),
        transport=_Boom(),
    )
    result = await sender.send(subscription=_Subscription(), title="t", body="b")
    assert result.delivered is False
    assert result.reason == "transport_failed"
