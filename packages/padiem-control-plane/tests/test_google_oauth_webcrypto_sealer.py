from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import hashlib
import hmac

import pytest

from google_oauth_durable_store import (
    GMAIL_READONLY_SCOPE,
    DurableGoogleOAuthCredential,
)
from google_oauth_webcrypto_sealer import (
    AES_GCM_IV_BYTES,
    CloudflareWorkerWebCryptoAesGcmPort,
    GoogleOAuthSealContext,
    GoogleOAuthSealPurpose,
    GoogleOAuthWebCryptoSealer,
    SEALED_ENVELOPE_PREFIX,
    decode_worker_seal_key,
)
from padiem_control_plane.contracts import ControlPlaneContractError


KEY_BYTES = b"K" * 32
KEY_SECRET = base64.urlsafe_b64encode(KEY_BYTES).decode("ascii").rstrip("=")
PLAINTEXT = "refresh-token-sensitive-value"


class DeterministicAeadTestPort:
    """Reversible integrity-bound test double; deliberately not production crypto."""

    def random_bytes(self, length: int) -> bytes:
        assert length == AES_GCM_IV_BYTES
        return bytes(range(1, length + 1))

    async def encrypt(
        self,
        *,
        key: bytes,
        iv: bytes,
        plaintext: bytes,
        additional_data: bytes,
    ) -> bytes:
        tag = hashlib.sha256(key + iv + additional_data + plaintext).digest()[:16]
        return plaintext[::-1] + tag

    async def decrypt(
        self,
        *,
        key: bytes,
        iv: bytes,
        ciphertext: bytes,
        additional_data: bytes,
    ) -> bytes:
        if len(ciphertext) < 17:
            raise ValueError("bad ciphertext")
        reversed_plaintext, tag = ciphertext[:-16], ciphertext[-16:]
        plaintext = reversed_plaintext[::-1]
        expected = hashlib.sha256(key + iv + additional_data + plaintext).digest()[:16]
        if not hmac.compare_digest(tag, expected):
            raise ValueError("integrity failure")
        return plaintext

    def safe_dict(self):
        return {"test_port": True, "production_crypto": False}


def context(**overrides) -> GoogleOAuthSealContext:
    values = dict(
        purpose=GoogleOAuthSealPurpose.REFRESH_TOKEN,
        connector_id="gmail",
        record_ref="binding_1",
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
    )
    values.update(overrides)
    return GoogleOAuthSealContext(**values)


def sealer() -> GoogleOAuthWebCryptoSealer:
    return GoogleOAuthWebCryptoSealer(
        key_secret_b64url=KEY_SECRET,
        crypto_port=DeterministicAeadTestPort(),
    )


def tamper(envelope: str) -> str:
    encoded = envelope[len(SEALED_ENVELOPE_PREFIX) :]
    padding = "=" * (-len(encoded) % 4)
    payload = bytearray(base64.urlsafe_b64decode(encoded + padding))
    payload[-1] ^= 1
    return SEALED_ENVELOPE_PREFIX + base64.urlsafe_b64encode(bytes(payload)).decode("ascii").rstrip("=")


def test_worker_secret_is_exact_256_bit_base64url_and_never_derived_from_bad_input():
    assert len(KEY_SECRET) == 43
    assert decode_worker_seal_key(KEY_SECRET) == KEY_BYTES

    for invalid in ("short", "A" * 42, "A" * 44, "!" * 43, KEY_SECRET + "="):
        with pytest.raises(ControlPlaneContractError) as exc:
            decode_worker_seal_key(invalid)
        assert exc.value.code == "invalid_google_oauth_seal_key"


def test_roundtrip_uses_versioned_envelope_and_hides_plaintext():
    oauth_sealer = sealer()
    seal_context = context()

    envelope = asyncio.run(
        oauth_sealer.seal_text(plaintext=PLAINTEXT, context=seal_context)
    )
    assert envelope.startswith(SEALED_ENVELOPE_PREFIX)
    assert PLAINTEXT not in envelope
    assert KEY_SECRET not in envelope
    assert asyncio.run(
        oauth_sealer.unseal_text(envelope=envelope, context=seal_context)
    ) == PLAINTEXT


def test_aad_binds_connector_record_actor_account_workspace_and_purpose():
    oauth_sealer = sealer()
    original = context()
    envelope = asyncio.run(oauth_sealer.seal_text(plaintext=PLAINTEXT, context=original))

    mismatches = (
        replace(original, record_ref="binding_2"),
        replace(original, actor_ref="actor_2"),
        replace(original, account_ref="account_2"),
        replace(original, workspace_ref="workspace_2"),
        replace(original, connector_id="google-drive"),
        replace(original, purpose=GoogleOAuthSealPurpose.AUTHORIZATION_SESSION),
    )
    for mismatch in mismatches:
        with pytest.raises(ControlPlaneContractError) as exc:
            asyncio.run(oauth_sealer.unseal_text(envelope=envelope, context=mismatch))
        assert exc.value.code == "google_oauth_unseal_failed"


def test_ciphertext_tamper_fails_integrity_without_leaking_detail():
    oauth_sealer = sealer()
    seal_context = context()
    envelope = asyncio.run(oauth_sealer.seal_text(plaintext=PLAINTEXT, context=seal_context))

    with pytest.raises(ControlPlaneContractError) as exc:
        asyncio.run(oauth_sealer.unseal_text(envelope=tamper(envelope), context=seal_context))
    assert exc.value.code == "google_oauth_unseal_failed"
    assert PLAINTEXT not in str(exc.value)
    assert KEY_SECRET not in str(exc.value)


def test_sealed_envelope_is_accepted_by_durable_store_record_contract():
    oauth_sealer = sealer()
    seal_context = context()
    envelope = asyncio.run(oauth_sealer.seal_text(plaintext=PLAINTEXT, context=seal_context))

    record = DurableGoogleOAuthCredential(
        binding_ref="binding_1",
        connector_id="gmail",
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(GMAIL_READONLY_SCOPE,),
        sealed_refresh_token=envelope,
        issued_at=__import__("datetime").datetime(2026, 9, 4, 10, 0, tzinfo=__import__("datetime").timezone.utc),
    )
    assert record.sealed_refresh_token == envelope
    assert PLAINTEXT not in str(record.safe_dict())


def test_invalid_envelope_and_empty_plaintext_fail_closed():
    oauth_sealer = sealer()
    seal_context = context()

    with pytest.raises(ControlPlaneContractError) as empty:
        asyncio.run(oauth_sealer.seal_text(plaintext="", context=seal_context))
    assert empty.value.code == "invalid_google_oauth_seal_plaintext"

    for invalid in ("", "sealed:v1:", "sealed:v2:AAAA", "plain", "sealed:v1:!!!!"):
        with pytest.raises(ControlPlaneContractError) as exc:
            asyncio.run(oauth_sealer.unseal_text(envelope=invalid, context=seal_context))
        assert exc.value.code == "invalid_google_oauth_sealed_envelope"


def test_context_rejects_unreviewed_connector_and_unsafe_refs():
    with pytest.raises(ControlPlaneContractError):
        context(connector_id="google-calendar")
    with pytest.raises(ControlPlaneContractError):
        context(record_ref="../../escape")


def test_cloudflare_port_is_lazy_import_and_declares_exact_runtime_crypto_contract():
    # Instantiation and safe projection work under ordinary CPython because js/
    # pyodide imports happen only when the Worker runtime crypto methods execute.
    port = CloudflareWorkerWebCryptoAesGcmPort()
    public = port.safe_dict()
    assert public == {
        "cloudflare_python_worker_ffi": True,
        "webcrypto_subtle": True,
        "algorithm": "AES-GCM-256",
        "iv_bytes": 12,
        "tag_bits": 128,
        "key_extractable": False,
        "raw_key_public": False,
    }


def test_sealer_public_projection_does_not_claim_worker_secret_is_kms():
    oauth_sealer = sealer()
    public = oauth_sealer.safe_dict()
    assert public["sealed_envelope"] == "sealed:v1"
    assert public["algorithm"] == "AES-GCM-256"
    assert public["aad_context_bound"] is True
    assert public["worker_secret_key_required"] is True
    assert public["worker_secret_is_kms"] is False
    assert public["raw_key_public"] is False
    assert public["raw_plaintext_public"] is False
    assert KEY_SECRET not in str(public)
    assert PLAINTEXT not in str(public)
