"""#5479/#5664 — the Worker password KDF across Cloudflare Python runtimes.

The Chat Worker hashes passwords with PBKDF2-HMAC-SHA512 (RFC 2898). Which
implementation provides that KDF depends on the runtime the compatibility
date selects:

- Pyodide 3.13 (``compatibility_date = "2026-08-25"``) provides
  ``hashlib.pbkdf2_hmac`` through ``_hashlib``/OpenSSL. This is the fastest
  path and the one Production ran until the 3.14 move.
- Pyodide 3.14 (``compatibility_date >= "2026-09-08"``) ships no ``_hashlib``
  and CPython 3.14 removed the pure-Python ``hashlib`` PBKDF2 fallback, so
  ``hashlib.pbkdf2_hmac`` does not exist there. That runtime is also the
  platform's published fix for the cold-init ``NoGilError`` race
  (``cloudflare/workerd#6624``), which #5664 recorded as still hitting
  Production register/login/reset requests.
- Workers' WebCrypto ``subtle.deriveBits`` is NOT a general replacement: the
  Production edge refuses PBKDF2 above 100,000 iterations
  (``NotSupportedError``), and the stored credential cost is 220,000. #5736
  deployed exactly that combination and every password request answered HTTP
  500, so the WebCrypto bridge may never serve a 220k request again.

This module decouples the KDF from the runtime so the stored credential
format (``pbkdf2_sha512$220000$...``, byte-identical PBKDF2 output per RFC
2898) survives a runtime move without any credential migration:

- :func:`pbkdf2_sha512_sync` uses the C-accelerated ``hashlib`` path (3.13).
- :func:`pbkdf2_sha512_cryptography` uses the ``cryptography`` package's
  OpenSSL PBKDF2HMAC, which the Worker bundle ships (and which Pyodide 3.14
  publishes a wasm wheel for). Measured in the isolated 3.14 Workerd lane:
  220,000 iterations in 269 ms, byte-identical to the C path.
- :func:`pbkdf2_sha512_webcrypto` remains for bounded iteration counts only.
- :func:`pbkdf2_sha512_python` is the pure-Python RFC 2898 reference used by
  hermetic tests and by environments with no other provider. It is
  byte-identical to ``hashlib.pbkdf2_hmac`` but far slower (720 ms at the
  stored cost in the same lane) — a determinism bridge, never an
  interactive-login path.
- :func:`resolve_kdf_provider` is the single source of truth for which of
  those the async dispatch uses, and the runtime probe reports it so a lane
  can prove which provider served the request instead of assuming one.
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

#: Measured on the Cloudflare Production edge (2026-10-24, #5479): the Workers
#: WebCrypto PBKDF2 implementation refuses any iteration count above this with
#: ``NotSupportedError: Pbkdf2 failed: iteration counts above 100000 are not
#: supported``. The isolated local Workerd lane does NOT enforce it, which is
#: why a green lane alone cannot approve a WebCrypto-served credential.
WEBCRYPTO_MAX_ITERATIONS = 100_000

#: Provider names reported by :func:`resolve_kdf_provider` and the probe.
PROVIDER_HASHLIB = "hashlib"
PROVIDER_CRYPTOGRAPHY = "cryptography"
PROVIDER_WEBCRYPTO = "webcrypto"
PROVIDER_PYTHON = "python"
PROVIDER_UNAVAILABLE = "unavailable"


class Pbkdf2Unavailable(RuntimeError):
    """The runtime exposes no usable PBKDF2 implementation for the request."""


#: Test hook: pretend the runtime has no C-accelerated PBKDF2 so the dispatch
#: exercises the paths a 3.14 snapshot would take.
FORCE_NON_C_PATH = False

#: Test hook: pretend the Worker bundle carries no ``cryptography`` package,
#: so the dispatch's last-resort behaviour is provable without uninstalling it.
FORCE_CRYPTOGRAPHY_UNAVAILABLE = False


def pbkdf2_hmac_available() -> bool:
    """Does this runtime provide the C-accelerated ``hashlib.pbkdf2_hmac``?"""
    if FORCE_NON_C_PATH:
        return False
    return hasattr(hashlib, "pbkdf2_hmac")


def _load_cryptography() -> tuple[Any, Any] | None:
    """The bundled ``cryptography`` PBKDF2 primitives, or ``None``.

    Imported lazily and without caching so a runtime whose bundle lacks the
    package reports ``None`` instead of failing the module import. On a
    Workers isolate this is a ``sys.modules`` lookup, not a re-import.
    """
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        return None
    return hashes, PBKDF2HMAC


def cryptography_available() -> bool:
    """Is the bundled OpenSSL-backed PBKDF2 available on this runtime?"""
    if FORCE_CRYPTOGRAPHY_UNAVAILABLE:
        return False
    return _load_cryptography() is not None


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


def pbkdf2_sha512_cryptography(
    password: bytes, salt: bytes, iterations: int, dklen: int
) -> bytes:
    """PBKDF2-HMAC-SHA512 through the bundled ``cryptography`` package.

    OpenSSL's implementation compiled to wasm; it needs no ``_hashlib`` and no
    WebCrypto, so it serves the stored 220,000-iteration cost on the 3.14
    snapshot. RFC 2898 output, so the stored credential bytes do not change.
    """
    loaded = _load_cryptography()
    if loaded is None:
        raise Pbkdf2Unavailable(
            "the bundled cryptography package is not available on this runtime"
        )
    hashes, PBKDF2HMAC = loaded
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA512(),
        length=dklen,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(password)


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

    Native code on the JS side and RFC 2898 output, but the Production edge
    rejects iteration counts above :data:`WEBCRYPTO_MAX_ITERATIONS`, so it
    cannot serve the stored credential cost. :func:`resolve_kdf_provider`
    keeps this path for bounded iteration counts only.
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


def resolve_kdf_provider(
    iterations: int,
    *,
    runtime_loader: Callable[[], tuple[Any, Any, Callable[..., Any]]] | None = None,
) -> str:
    """Which provider :func:`apbkdf2_sha512` will use for this request.

    One function decides, the dispatch and the runtime probe both read it, so
    the CI lane reports the provider that actually served the stored cost
    instead of assuming one. Order:

    1. ``hashlib`` — the C path (Pyodide 3.13; fastest, byte-identical).
    2. ``cryptography`` — the bundled OpenSSL KDF (Pyodide 3.14).
    3. ``webcrypto`` — bounded iteration counts only, never above the edge's
       measured ceiling. A hermetic ``runtime_loader`` selects it explicitly.
    4. ``python`` — pure-Python reference, hermetic contexts only.
    5. ``unavailable`` — nothing can serve this cost; the dispatch raises.
    """
    if runtime_loader is not None:
        return PROVIDER_WEBCRYPTO
    if pbkdf2_hmac_available():
        return PROVIDER_HASHLIB
    if cryptography_available():
        return PROVIDER_CRYPTOGRAPHY
    if 0 < iterations <= WEBCRYPTO_MAX_ITERATIONS:
        return PROVIDER_WEBCRYPTO
    return PROVIDER_UNAVAILABLE


async def apbkdf2_sha512(
    password: bytes,
    salt: bytes,
    iterations: int,
    dklen: int,
    *,
    runtime_loader: Callable[[], tuple[Any, Any, Callable[..., Any]]] | None = None,
) -> bytes:
    """The async dispatch the auth routes call.

    On Pyodide 3.13 this is the unchanged C path. On 3.14 it is the bundled
    ``cryptography`` package, not WebCrypto: the stored 220,000 iterations are
    above the edge's WebCrypto ceiling, and reaching that ceiling again is the
    exact #5736 outage. When no provider can serve the cost the dispatch
    raises :class:`Pbkdf2Unavailable` naming what is missing, instead of
    silently degrading to interpreted arithmetic and hiding a platform fault.
    """
    provider = resolve_kdf_provider(iterations, runtime_loader=runtime_loader)
    if provider == PROVIDER_HASHLIB:
        return pbkdf2_sha512_sync(password, salt, iterations, dklen)
    if provider == PROVIDER_CRYPTOGRAPHY:
        return pbkdf2_sha512_cryptography(password, salt, iterations, dklen)
    if provider == PROVIDER_WEBCRYPTO:
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
    raise Pbkdf2Unavailable(
        "no PBKDF2-HMAC-SHA512 provider can serve "
        f"{iterations} iterations on this runtime: hashlib.pbkdf2_hmac is "
        "absent, the bundled cryptography package is unavailable, and Workers "
        f"WebCrypto refuses iteration counts above {WEBCRYPTO_MAX_ITERATIONS}"
    )
