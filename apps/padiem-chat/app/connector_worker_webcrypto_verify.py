"""Cloudflare Python Worker WebCrypto Ed25519 PoP verifier (#4139).

Source-only: never mounts a route or grants device/account permission.
Uses Workers' js.crypto.subtle via Pyodide FFI; unlike a native cryptography
wheel, this is package-free for the B62 Python/Pyodide Worker build.

The caller (not HTTP/JSON) constructs this verifier within a trusted Worker
runtime. This verifies ONLY a fresh ephemeral public-key signature; actual
owner consent, canonical Broker proof, and Windows DPAPI ACK are separate.
All exceptions are sanitized, and 'truthy' JS/Python strings cannot authorize.
"""
from __future__ import annotations

from typing import Any, Callable

WORKER_ED25519_PRODUCTION_ENABLED = False
WORKER_ED25519_OWNER_GATEWAY_MOUNTED = False


class WebCryptoUnavailable(RuntimeError):
    """No crypto algorithm/key material exposed to the caller."""


def _native_runtime() -> tuple[Any, Any, Callable[..., Any]]:
    """Import Pyodide resources ONLY inside a real Worker method call."""
    from js import crypto, Uint8Array  # type: ignore[import-not-found]
    from pyodide.ffi import to_js  # type: ignore[import-not-found]
    return crypto.subtle, Uint8Array, to_js


def _bytes_as_uint8(data: bytes, factory: Any) -> Any:
    """Copy exact binary bytes into JS TypedArray without PyProxy coercion."""
    out = factory.new(len(data))
    for index, byte in enumerate(data):
        out[index] = byte
    return out


class CloudflareWorkerEd25519Verifier:
    """Exactly the trusted async verify_ed25519 port required by PC gateway.

    The optional runtime_loader enables a hermetic fake of js/pyodide in tests,
    NOT a permission to bypass signature validation in a deployed Worker.
    Normal runtime composition must use the zero-argument constructor.
    """

    def __init__(
        self, *, runtime_loader: Callable[[], tuple[Any, Any, Callable[..., Any]]] | None = None,
    ) -> None:
        self._loader = runtime_loader or _native_runtime

    async def verify_ed25519(
        self, *, public_key: bytes, signature: bytes, transcript: bytes,
    ) -> bool:
        if (
            type(public_key) is not bytes or len(public_key) != 32
            or type(signature) is not bytes or len(signature) != 64
            or type(transcript) is not bytes
            or not 0 < len(transcript) <= 2048
        ):
            return False
        try:
            subtle, uint8_factory, to_js = self._loader()
            if not callable(getattr(subtle, "importKey", None)):
                raise WebCryptoUnavailable("unavailable")
            if not callable(getattr(subtle, "verify", None)):
                raise WebCryptoUnavailable("unavailable")
            if not callable(getattr(uint8_factory, "new", None)) or not callable(to_js):
                raise WebCryptoUnavailable("unavailable")
            key = await subtle.importKey(
                "raw", _bytes_as_uint8(public_key, uint8_factory),
                "Ed25519", False, to_js(["verify"]),
            )
            result = await subtle.verify(
                "Ed25519", key,
                _bytes_as_uint8(signature, uint8_factory),
                _bytes_as_uint8(transcript, uint8_factory),
            )
            return result is True
        except Exception:
            # Incorrect algorithms, unsupported Worker API, FFI type mismatch
            # and signature failures are NOT authentication. Never log a frame.
            return False
