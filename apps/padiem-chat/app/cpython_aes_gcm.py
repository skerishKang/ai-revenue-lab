"""CPython implementation of the Worker AES-GCM cipher port."""
from __future__ import annotations

import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CPythonAesGcmPort:
    """WebCrypto-compatible ciphertext followed by the 128-bit authentication tag."""

    def random_bytes(self, size: int) -> bytes:
        if size != 12:
            raise ValueError("12-byte unique AES-GCM nonce required")
        return secrets.token_bytes(size)

    async def encrypt(self, *, key: bytes, iv: bytes, plaintext: bytes, additional_data: bytes) -> bytes:
        return AESGCM(key).encrypt(iv, plaintext, additional_data)

    async def decrypt(self, *, key: bytes, iv: bytes, ciphertext: bytes, additional_data: bytes) -> bytes:
        return AESGCM(key).decrypt(iv, ciphertext, additional_data)
