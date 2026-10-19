"""Cloudflare WebCrypto AES-GCM port, following the existing Google OAuth sealed-store FFI.

The original control-plane Google sealer is a top-level Worker module, not exported
by the installable padiem_control_plane wheel. The same audited WebCrypto boundary
is exposed here for B62 GitHub connection tokens without a new crypto library.
"""
from __future__ import annotations

class CloudflareAesGcmPort:
    @staticmethod
    def _ffi():
        from js import Object, Uint8Array, crypto  # type: ignore[import-not-found]
        from pyodide.ffi import to_js  # type: ignore[import-not-found]
        return Object, Uint8Array, crypto, to_js

    @classmethod
    def _bytes(cls, data: bytes):
        _, Uint8Array, _, to_js = cls._ffi()
        return Uint8Array.new(to_js(list(data)))

    @classmethod
    async def _key(cls, value: bytes):
        Object, _, crypto, to_js = cls._ffi()
        return await crypto.subtle.importKey(
            "raw", cls._bytes(value), to_js({"name": "AES-GCM"}, dict_converter=Object.fromEntries),
            False, to_js(["encrypt", "decrypt"]))

    @classmethod
    def _algorithm(cls, iv: bytes, aad: bytes):
        Object, _, _, to_js = cls._ffi()
        return to_js({"name": "AES-GCM", "iv": cls._bytes(iv),
                      "additionalData": cls._bytes(aad), "tagLength": 128},
                     dict_converter=Object.fromEntries)

    def random_bytes(self, size: int) -> bytes:
        if size != 12:
            raise ValueError("12-byte unique AES-GCM nonce required")
        _, Uint8Array, crypto, _ = self._ffi()
        buffer = Uint8Array.new(size)
        crypto.getRandomValues(buffer)
        return bytes(buffer.to_py())

    async def encrypt(self, *, key: bytes, iv: bytes, plaintext: bytes, additional_data: bytes) -> bytes:
        _, Uint8Array, crypto, _ = self._ffi()
        result = await crypto.subtle.encrypt(self._algorithm(iv, additional_data),
                                             await self._key(key), self._bytes(plaintext))
        return bytes(Uint8Array.new(result).to_py())

    async def decrypt(self, *, key: bytes, iv: bytes, ciphertext: bytes, additional_data: bytes) -> bytes:
        _, Uint8Array, crypto, _ = self._ffi()
        result = await crypto.subtle.decrypt(self._algorithm(iv, additional_data),
                                             await self._key(key), self._bytes(ciphertext))
        return bytes(Uint8Array.new(result).to_py())
