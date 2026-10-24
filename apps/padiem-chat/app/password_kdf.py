"""#5479/#5664 — the Worker password KDF across Cloudflare Python runtimes.

The Chat Worker hashes passwords with PBKDF2-HMAC-SHA512 (RFC 2898). Which
implementation provides that KDF depends on the runtime the compatibility
date selects:

- Pyodide 3.13 (``compatibility_date = "2026-08-25"``, current Production)
  provides ``hashlib.pbkdf2_hmac`` through ``_hashlib``/OpenSSL. This is the
  fast path and the one Production runs today.
- Pyodide 3.14 (``compatibility_date >= "2026-09-08"``) ships no ``_hashlib``
  and CPython 3.14 removed the pure-Python ``hashlib`` PBKDF2 fallback, so
  ``hashlib.pbkdf2_hmac`` does not exist there. That runtime is also the
  platform's published fix for the cold-init ``NoGilError`` race
  (``cloudflare/workerd#6624``), which #5664 recorded as still hitting
  Production register/login/reset requests.

This module decouples the KDF from the runtime so the stored credential
format (``pbkdf2_sha512$220000$...``, byte-identical PBKDF2 output per RFC
2898) survives a runtime move without any credential migration:

- :func:`pbkdf2_sha512_sync` uses the C-accelerated ``hashlib`` path and is
  what Production runs today.
- :func:`apbkdf2_sha512` is the async dispatch: the C path when the runtime
  has it, otherwise Workers' native ``js.crypto.subtle.deriveBits`` (no
  ``_hashlib`` required, same RFC output).
- :func:`pbkdf2_sha512_python` is a bounded pure-Python RFC 2898 reference
  used by tests and by environments with neither implementation. It is
  byte-identical to ``hashlib.pbkdf2_hmac`` but far slower — it is a
  determinism bridge, not an interactive-login path.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, Callable

#: The digest PBKDF2_ALGORITHM names, as WebCrypto spells it. The stored
#: prefix (``pbkdf2_sha512``) and the derived bytes are unchanged either way.
WEBCRYPTO_HASH = "SHA-512"

#: SHA-512 digest size in bytes. One PBKDF2 block, per RFC 2898.
SHA512_DIGEST_LEN = 64


class Pbkdf2Unavailable(RuntimeError):
    """The runtime exposes no usable PBKDF2 implementation for the request."""


#: Test hook: pretend the runtime has no C-accelerated PBKDF2 so the dispatch
#: exercises the WebCrypto/pure-Python paths the way a 3.14 snapshot would.
FORCE_NON_C_PATH = False


def pbkdf2_hmac_available() -> bool:
    """Does this runtime provide the C-accelerated ``hashlib.pbkdf2_hmac``?"""
    if FORCE_NON_C_PATH:
        return False
    return hasattr(hashlib, "pbkdf2_hmac")


def pbkdf2_sha512_sync(
    password: bytes, salt: bytes, iterations: int, dklen: int
) -> bytes:
    """The C-accelerated path. Raises :class:`Pbkdf2Unavailable` on 3.14."""
    if not pbkdf2_hmac_available():
        raise Pbkdf2Unavailable(
            "hashlib.pbkdf2_hmac is not available on this runtime"
        )
    return hashlib.pbkdf2_hmac(
        "sha512", password, salt, iterations, dklen=dklen
    )


def pbkdf2_sha512_python(
    password: bytes, salt: bytes, iterations: int, dklen: int
) -> bytes:
    """Pure-Python RFC 2898 PBKDF2-HMAC-SHA512.

    Byte-identical to ``hashlib.pbkdf2_hmac("sha512", ...)`` for every input
    (asserted by the tests against the C implementation). Each output block
    is ``T_i = U_1 ^ U_2 ^ ... ^ U_c`` with ``U_1 = HMAC(P, S || INT(i))`` and
    ``U_j = HMAC(P, U_{j-1})``. Deterministic, allocation-bounded, and slow:
    a determinism bridge for tests and KDF-less runtimes, never an
    interactive-login path at the stored 220_000-iteration cost.
    """
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if dklen < 1:
        raise ValueError("dklen must be at least 1")
    blocks = -(-dklen // SHA512_DIGEST_LEN)
    out = bytearray()
    for block_index in range(1, blocks + 1):
        u = hmac.new(
            password, salt + block_index.to_bytes(4, "big"), "sha512"
        ).digest()
        accumulator = int.from_bytes(u, "big")
        for _ in range(iterations - 1):
            u = hmac.new(password, u, "sha512").digest()
            accumulator ^= int.from_bytes(u, "big")
        out += accumulator.to_bytes(SHA512_DIGEST_LEN, "big")
    return bytes(out[:dklen])


def _native_runtime() -> tuple[Any, Any, Callable[..., Any]]:
    """Import Pyodide resources ONLY inside a real Worker method call.

    Same discipline as connector_worker_webcrypto_verify.py: the ``js`` module
    exists only inside the Workers runtime, so tests inject a hermetic loader.
    """
    from js import crypto, Uint8Array  # type: ignore[import-not-found]
    from pyodide.ffi import to_js  # type: ignore[import-not-found]
    return crypto.subtle, Uint8Array, to_js


def _bytes_as_uint8(data: bytes, factory: Any) -> Any:
    """Copy exact binary bytes into a JS TypedArray without PyProxy coercion."""
    out = factory.new(len(data))
    for index, byte in enumerate(data):
        out[index] = byte
    return out


async def pbkdf2_sha512_webcrypto(
    password: bytes,
    salt: bytes,
    iterations: int,
    dklen: int,
    *,
    runtime_loader: Callable[[], tuple[Any, Any, Callable[..., Any]]] | None = None,
) -> bytes:
    """Workers WebCrypto path: ``subtle.deriveBits`` with PBKDF2/SHA-512.

    Native code on the JS side — no ``_hashlib`` needed, so it runs on the
    3.14 snapshot, and the derived bytes are the RFC 2898 PBKDF2-HMAC-SHA512
    output the stored credential format already holds.
    """
    subtle, uint8_factory, to_js = (runtime_loader or _native_runtime)()
    for name in ("importKey", "deriveBits"):
        if not callable(getattr(subtle, name, None)):
            raise Pbkdf2Unavailable("subtle." + name + " unavailable")
    key = await subtle.importKey(
        "raw",
        _bytes_as_uint8(password, uint8_factory),
        "PBKDF2",
        False,
        to_js(["deriveBits"]),
    )
    params = to_js(
        {
            "name": "PBKDF2",
            "hash": WEBCRYPTO_HASH,
            "salt": _bytes_as_uint8(salt, uint8_factory),
            "iterations": iterations,
        }
    )
    raw = await subtle.deriveBits(params, key, dklen * 8)
    typed = uint8_factory.new(raw)
    return bytes(typed.to_py())


async def apbkdf2_sha512(
    password: bytes,
    salt: bytes,
    iterations: int,
    dklen: int,
    *,
    runtime_loader: Callable[[], tuple[Any, Any, Callable[..., Any]]] | None = None,
) -> bytes:
    """The async dispatch the auth routes call.

    C path when the runtime has it (current Production, zero behavior
    change), WebCrypto when it does not (3.14 and later snapshots). The
    pure-Python reference only serves hermetic test contexts
    (``runtime_loader`` injected) — on a deployed Worker a WebCrypto failure
    must fail fast (the #5724 client already classifies and retries that)
    instead of quietly spending minutes in interpreted arithmetic.
    """
    if pbkdf2_hmac_available():
        return pbkdf2_sha512_sync(password, salt, iterations, dklen)
    try:
        return await pbkdf2_sha512_webcrypto(
            password, salt, iterations, dklen, runtime_loader=runtime_loader
        )
    except (Pbkdf2Unavailable, ImportError):
        # Hermetic contexts (runtime_loader injected) fall back to the
        # pure-Python reference; a deployed Worker fails fast instead.
        if runtime_loader is None:
            raise
        return pbkdf2_sha512_python(password, salt, iterations, dklen)
