"""Real Workerd/Pyodide multiplex for the four original runtime probes.

Each case delegates the original WorkerEntrypoint.fetch() with the *real*
incoming Workers Request. Only the /probe?case=... routing is new. Keep P01
last in the single-process runner: its existing synthetic route test patches
module globals and must not influence the HTTP/R2 contract probes.
"""
from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

from workers import Response, WorkerEntrypoint
from worker_runtime_timeout_probe import Default as TimeoutProbe
from worker_runtime_web_transport_probe import Default as WebTransportProbe
from worker_runtime_r2_read_probe import Default as R2ReadProbe
from worker_runtime_p01_binding_probe import Default as P01BindingProbe


PROBES = {
    "timeout": TimeoutProbe.fetch,
    "web_transport": WebTransportProbe.fetch,
    "r2_read": R2ReadProbe.fetch,
    "p01_binding": P01BindingProbe.fetch,
}


# #4139: temporary Workerd ONLY; never import this synthetic gateway from the
# production padiem-chat/worker.py. A 101 here proves the real Cloudflare
# Python ASGI/WS upgrade transport, NOT canonical Identity/Broker or TLS.
RUNTIME_WSS_PROBE_PATH = "/api/claw/connector/gateway/session"
_RUNTIME_CLIENT_PROOF = "synthetic-frame-no-credential"
_RUNTIME_SERVER_OPEN = "PADIEM_CONNECTOR_ASGI_WS_OPEN"
_RUNTIME_SERVER_ACK = "PADIEM_CONNECTOR_ASGI_WS_REPLY"


async def connector_asgi_websocket_runtime_probe(scope, receive, send):
    """Pure ASGI fixture: no session, no credential, no Broker or privileged IO."""
    if scope.get("type") != "websocket" or scope.get("path") != RUNTIME_WSS_PROBE_PATH:
        await send({"type": "websocket.close", "code": 1008})
        return
    opened = await receive()
    if opened.get("type") != "websocket.connect":
        await send({"type": "websocket.close", "code": 1008})
        return
    await send({"type": "websocket.accept"})
    await send({"type": "websocket.send", "text": _RUNTIME_SERVER_OPEN})
    incoming = await receive()
    if (incoming.get("type") == "websocket.receive"
            and incoming.get("text") == _RUNTIME_CLIENT_PROOF):
        await send({"type": "websocket.send", "text": _RUNTIME_SERVER_ACK})
    # No credential or ACK data is ever sent. The test client closes.


def _password_kdf_state() -> str:
    """``ok`` when this runtime can run the Worker's password hashing.

    The Worker's stored credential format is PBKDF2-HMAC-SHA512. A Python
    runtime without ``hashlib.pbkdf2_hmac`` cannot verify a stored hash at
    all, so every password login would answer HTTP 500. The probe runs the
    real application hashing function, so a runtime without the KDF is
    reported instead of silently passing.
    """
    try:
        from app.password_auth import hash_password, verify_password

        stored = hash_password("runtime-probe-password")
        if not verify_password("runtime-probe-password", stored):
            return "verify-failed"
        if verify_password("runtime-probe-wrong", stored):
            return "verify-wrong-accepted"
        return "ok"
    except Exception:
        return "missing"


async def _password_kdf_async_state() -> str:
    """``ok`` when the async auth dispatch and the WebCrypto bridge hold.

    #5479/#5664: the auth routes now call the runtime-dispatching async twins
    (``hash_password_async``/``verify_password_async``), which use the C
    ``hashlib`` path on 3.13 and the Workers WebCrypto bridge on a 3.14
    snapshot without ``_hashlib``. This state proves both inside the real
    runtime: a production-cost round trip, and — with the non-C dispatch
    forced so the bridge runs against this runtime's real ``js.crypto.subtle``
    — byte-identity with the pure-Python RFC 2898 reference at a bounded
    iteration count.
    """
    try:
        from app import password_kdf
        from app.password_auth import (
            hash_password_async,
            verify_password_async,
        )

        stored = await hash_password_async("runtime-probe-password")
        if not await verify_password_async("runtime-probe-password", stored):
            return "async-verify-failed"
        salt = bytes.fromhex("c8ade6e8d0d15e5a2e14aabf5e5d8f4a")
        previous = password_kdf.FORCE_NON_C_PATH
        try:
            password_kdf.FORCE_NON_C_PATH = True
            bridged = await password_kdf.pbkdf2_sha512_webcrypto(
                b"runtime-probe-bridged", salt, 2_000, 32
            )
        finally:
            password_kdf.FORCE_NON_C_PATH = previous
        reference = password_kdf.pbkdf2_sha512_python(
            b"runtime-probe-bridged", salt, 2_000, 32
        )
        if bridged != reference:
            return "webcrypto-mismatch"
        return "ok"
    except Exception:
        return "missing"


#: A credential written by the Pyodide 3.13 runtime (CPython 3.13, C
#: ``hashlib`` PBKDF2 path) through the real application hashing function,
#: corroborated byte-for-byte by OpenSSL. Members keep these exact bytes: a
#: compatibility-date move must not re-hash or migrate anything, so the runtime
#: Production moves TO has to accept a hash written before the move.
#:
#: The iteration count carried here is the stored 220,000, which is the point
#: of this vector. #5736 recorded a deployed 3.14 Worker rejecting exactly that
#: cost — ``js.crypto.subtle.deriveBits`` answers PBKDF2 above 100,000 iterations
#: with ``NotSupportedError`` and there is no ``_hashlib`` C path on that
#: snapshot — so every register, login and password reset returned HTTP 500 and
#: Production had to be rolled back. The low-iteration bridge check in
#: :func:`_password_kdf_async_state` cannot see that ceiling; this one can.
LEGACY_PYODIDE_313_STORED_HASH = (
    "pbkdf2_sha512$220000$FRiPFPCmf2W2mVjqpy85qw==$"
    "JUn+Fo0Rod5ZOJPBy80PJOfmfOBSS4hHGaUw7FM4ymg="
)
LEGACY_PYODIDE_313_PASSWORD = "runtime-probe-legacy-credential"
LEGACY_PYODIDE_313_WRONG_PASSWORD = "runtime-probe-legacy-credential-wrong"


async def _legacy_stored_credential_state() -> str:
    """``ok`` when this runtime serves a credential written by the previous one.

    This is the production-shaped check: the auth routes serve an existing
    member through ``verify_password_async`` only, so the stored prefix,
    iteration count and derived key from the earlier runtime must pass here and
    a wrong password must not. A runtime that cannot reach the stored iteration
    count reports the raising exception class instead of a bare ``missing``,
    so the CI log names the ceiling rather than hiding it.
    """
    try:
        from app.password_auth import verify_password_async

        if not await verify_password_async(
            LEGACY_PYODIDE_313_PASSWORD, LEGACY_PYODIDE_313_STORED_HASH
        ):
            return "rejected"
        if await verify_password_async(
            LEGACY_PYODIDE_313_WRONG_PASSWORD, LEGACY_PYODIDE_313_STORED_HASH
        ):
            return "wrong-accepted"
        return "ok"
    except Exception as error:
        return f"blocked:{type(error).__name__}"


#: Published OpenSSL/CPython vectors for the digest surface the auth layer uses
#: outside the password KDF (token hashing in ``app/auth.py``, abuse keys in
#: ``app/auth_abuse.py``). Compared against an external oracle, not against
#: ``hashlib`` checking itself.
_SHA256_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
_SHA512_ABC = (
    "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
    "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"
)
_HMAC_KEY = b"runtime-probe-key"
_HMAC_MESSAGE = b"runtime-probe-message"
_HMAC_SHA256_FIXED = "6d6357bb3cd312e22258e5b3a69d7783c68da539b57ff8add5002f5d9f508993"
_HMAC_SHA512_FIXED = (
    "c32b7a9ab5ecb2c9326f006ad9e88d5866d4fb9b0f02243ff6bc27ed1194ae45"
    "1cf380fd26f9f598c5ee01cdcdfb08378536f6137ea6a3bf89db874e450e8fba"
)


def _digest_surface_state() -> str:
    """``ok`` when this runtime's SHA-2 and HMAC match the published vectors.

    ``_hashlib`` (OpenSSL) is absent from the Pyodide 3.14 snapshot, and the
    auth layer hashes issued tokens, abuse keys and certified payloads with
    ``hashlib``/``hmac`` directly. A runtime answering those calls with
    different bytes would invalidate credentials that were issued before the
    move, so the move is provable only if the digests are checked here.
    """
    try:
        import hashlib
        import hmac

        if hashlib.sha256(b"abc").hexdigest() != _SHA256_ABC:
            return "sha256-mismatch"
        if hashlib.sha512(b"abc").hexdigest() != _SHA512_ABC:
            return "sha512-mismatch"
        if hmac.new(_HMAC_KEY, _HMAC_MESSAGE, hashlib.sha256).hexdigest() != _HMAC_SHA256_FIXED:
            return "hmac-sha256-mismatch"
        if hmac.new(_HMAC_KEY, _HMAC_MESSAGE, hashlib.sha512).hexdigest() != _HMAC_SHA512_FIXED:
            return "hmac-sha512-mismatch"
        return "ok"
    except Exception as error:
        return f"missing:{type(error).__name__}"


def _pbkdf2_sha512_pure(password: bytes, salt: bytes, iterations: int, dklen: int) -> bytes:
    """RFC 2898 PBKDF2-HMAC-SHA512 built only from the ``hashlib.sha512``
    primitive (no ``hashlib.pbkdf2_hmac``, which the 3.14 snapshot lacks).
    The HMAC key block is 128 bytes — SHA-512's block size, NOT 64."""
    block_size = hashlib.sha512().block_size
    key = password
    if len(key) > block_size:
        key = hashlib.sha512(key).digest()
    key = key.ljust(block_size, b"\x00")
    inner = hashlib.sha512(bytes(b ^ 0x36 for b in key))
    outer = hashlib.sha512(bytes(b ^ 0x5C for b in key))

    def prf(data: bytes) -> bytes:
        i = inner.copy()
        i.update(data)
        o = outer.copy()
        o.update(i.digest())
        return o.digest()

    out = bytearray()
    block_index = 1
    while len(out) < dklen:
        u = prf(salt + block_index.to_bytes(4, "big"))
        t_int = int.from_bytes(u, "big")
        for _ in range(iterations - 1):
            u = prf(u)
            t_int ^= int.from_bytes(u, "big")
        out += t_int.to_bytes(64, "big")
        block_index += 1
    return bytes(out[:dklen])


#: PBKDF2-HMAC-SHA512("password", "salt", c, 64) — computed with the C
#: implementation and pinned so a runtime without ``hashlib.pbkdf2_hmac``
#: still proves its fallback against an external reference.
_PURE_VECTORS = {
    1: "867f70cf1ade02cff3752599a3a53dc4af34c7a669815ae5d513554e1c8cf252c02d470a285a0501bad999bfe943c08f050235d7d68b1da55e63f73b60a57fce",
    2: "e1d9c16aa681708a45f5c7c4e215ceb66e011a2e9f0040713f18aefdb866d53cf76cab2868a39b9f7840edce4fef5a82be67335c77a6068e04112754f27ccf4e",
    4096: "d197b1b33db0143e018b12f3d1d1479e6cdebdcc97c5c0f87f6902e072f457b5143f30602641b3d55cd335988cb36b84376060ecd532e039b742a239434af2d5",
    220000: "3ede6b8c2ba493194db1febc21d3be4fc1c7d63f4a6bcc14ad9ae07c63432c6a867beca4a0dc50070666875567d813cc3bfd3607e634ba6087934cb5ec4bb99a",
}


async def _kdf220k_state() -> dict:
    """One real production-cost auth round trip: the stored credential
    format (PBKDF2-HMAC-SHA512 at PBKDF2_ITERATIONS) through the same async
    dispatch the auth routes call. On the 3.14 snapshot the WebCrypto bridge
    refuses iterations above 100,000 — reported as ``webcrypto-iteration-cap``
    instead of masking the failure."""
    from app import password_kdf
    import app.password_auth as password_auth

    # The lane must see WHICH provider served the stored cost, not just that
    # some provider did. #5733 passed a low-iteration bridge and a local
    # Workerd lane whose WebCrypto accepts 220k, then failed on the edge.
    provider = password_kdf.resolve_kdf_provider(password_auth.PBKDF2_ITERATIONS)
    started = time.perf_counter()
    try:
        stored = await password_auth.hash_password_async("runtime-probe-password")
        if not await password_auth.verify_password_async("runtime-probe-password", stored):
            return {
                "state": "verify-failed",
                "iterations": password_auth.PBKDF2_ITERATIONS,
                "provider": provider,
            }
        if await password_auth.verify_password_async("runtime-probe-wrong-password", stored):
            return {
                "state": "wrong-accepted",
                "iterations": password_auth.PBKDF2_ITERATIONS,
                "provider": provider,
            }
        return {
            "state": "ok",
            "iterations": password_auth.PBKDF2_ITERATIONS,
            "ms": int((time.perf_counter() - started) * 1000),
            "provider": provider,
        }
    except Exception as exc:
        text = str(exc)
        if "iteration counts above 100000" in text:
            return {
                "state": "webcrypto-iteration-cap",
                "iterations": password_auth.PBKDF2_ITERATIONS,
                "provider": provider,
                "error": text[:200],
            }
        return {"state": "missing", "provider": provider, "error": text[:200]}


async def _kdfbench_state() -> dict:
    """The 220,000-iteration alternatives with their real CPU cost.

    - ``sha512prim``: does this runtime expose the C ``hashlib.sha512``
      primitive the pure-Python fallback needs?
    - ``vector``: the pure-Python PBKDF2 against pinned external vectors
      (correctness independent of any C path).
    - ``pure_ms`` + ``identity``: 220,000 iterations in the pure-Python
      fallback, timed, and — where the C path exists — byte-identical to it.
    - ``cryptogr``: the bundled ``cryptography`` package's PBKDF2HMAC at
      220,000 (``not-bundled`` unless the dependency is added).
    """
    import hashlib

    result: dict = {}
    try:
        hashlib.sha512(b"").digest()
        result["sha512prim"] = "ok"
    except Exception:
        result["sha512prim"] = "missing"
        return result

    vector_ok = all(
        _pbkdf2_sha512_pure(b"password", b"salt", c, 64).hex() == expected
        for c, expected in _PURE_VECTORS.items()
        if c != 220000
    )
    result["vector"] = "true" if vector_ok else "false"

    started = time.perf_counter()
    pure_220k = _pbkdf2_sha512_pure(b"password", b"salt", 220000, 64)
    result["pure_ms"] = int((time.perf_counter() - started) * 1000)
    if hasattr(hashlib, "pbkdf2_hmac"):
        c_ref = hashlib.pbkdf2_hmac("sha512", b"password", b"salt", 220000, 64)
        result["identity"] = "true" if pure_220k == c_ref else "false"
    else:
        result["identity"] = (
            "true" if pure_220k.hex() == _PURE_VECTORS[220000] else "false"
        )

    try:
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes

        started = time.perf_counter()
        kdf = PBKDF2HMAC(algorithm=hashes.SHA512(), length=64, salt=b"salt", iterations=220000)
        derived = kdf.derive(b"password")
        result["cryptogr_ms"] = int((time.perf_counter() - started) * 1000)
        result["cryptogr_identity"] = "true" if derived.hex() == _PURE_VECTORS[220000] else "false"
        result["cryptogr"] = "ok"
    except ImportError:
        result["cryptogr"] = "not-bundled"
    except Exception as exc:
        result["cryptogr"] = "error:" + str(exc)[:120]
    return result



def _timezone_database_state() -> str:
    """``ok`` when this runtime can resolve a real IANA zone.

    #5023: the Calendar contracts validate the explicit timezone against the
    real IANA database. A Pyodide runtime without the tz database raises
    ZoneInfoNotFoundError for every real zone, and the Calendar routes surface
    that as HTTP 400 ``invalid_timezone`` on every read. The probe runs the
    real application contract, so a runtime without the database is reported
    instead of silently passing.
    """
    try:
        from app.calendar_contracts import validate_timezone

        validate_timezone("Asia/Seoul")
        return "ok"
    except Exception:
        return "missing"




class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlparse(str(request.url))
        if url.path == RUNTIME_WSS_PROBE_PATH and not url.query:
            if request.headers.get("upgrade") != "websocket":
                return Response("Upgrade Required", status=426)
            from workers import asgi
            # Worker Python SDK: asgi.websocket(app, request) accepts two args.
            # The synthetic transport probe must exercise the same signature
            # as CENTRAL's review-only production candidate.
            return await asgi.websocket(connector_asgi_websocket_runtime_probe, request)
        if url.path == "/ready" and not url.query:
            # #5479: report the running CPython version AND whether this
            # runtime can still run the Worker's password hashing. The CI lane
            # must prove the runtime Production actually deploys, and the
            # Pyodide 3.14 snapshot has no `hashlib.pbkdf2_hmac`, which would
            # answer every password login with HTTP 500.
            # #5023: the same holds for the IANA timezone database the
            # Calendar contracts validate against.
            # #5664: the ready line also carries the runtime-dispatching auth
            # KDF state (async routes + WebCrypto bridge), the cross-runtime
            # stored-credential check and the digest surface, so a compatibility
            # date move is provable in this lane before Production takes it.
            import sys

            kdf_async = await _password_kdf_async_state()
            stored = await _legacy_stored_credential_state()
            return Response(
                f"ok {sys.version_info.major}.{sys.version_info.minor} "
                f"kdf={_password_kdf_state()} kdfasync={kdf_async} "
                f"tz={_timezone_database_state()} stored={stored} "
                f"digest={_digest_surface_state()}",
                status=200,
            )
        if url.path != "/probe":
            return Response("not found", status=404)
        try:
            params = parse_qs(url.query, strict_parsing=True)
        except ValueError:
            return Response("invalid probe case", status=400)
        if set(params) != {"case"} or len(params["case"]) != 1:
            return Response("invalid probe case", status=400)
        case = params["case"][0]
        # #5479/#5664: the real password KDF contract — the stored credential
        # format is PBKDF2-HMAC-SHA512 at PBKDF2_ITERATIONS (220,000), and the
        # 3.14 snapshot's WebCrypto bridge refuses iterations above 100,000.
        # These two cases carry the evidence the CI lane needs to judge a
        # runtime migration: the actual production KDF round trip, and the
        # stdlib-primitive fallback with its real CPU cost.
        if case == "kdf220k":
            try:
                body = json.dumps(await _kdf220k_state(), ensure_ascii=False)
            except Exception as exc:
                body = json.dumps({"state": "probe-error", "error": str(exc)[:300]})
            return Response(body, status=200, headers={"Content-Type": "application/json"})
        if case == "kdfbench":
            try:
                body = json.dumps(await _kdfbench_state(), ensure_ascii=False)
            except Exception as exc:
                body = json.dumps({"state": "probe-error", "error": str(exc)[:300]})
            return Response(body, status=200, headers={"Content-Type": "application/json"})
        handler = PROBES.get(case)
        if handler is None:
            return Response("invalid probe case", status=400)
        # The old handlers inspect only request.url (the path remains /probe).
        # Passing the original real Workerd Request preserves the exact
        # JS-object/Request transport assertions in each legacy probe.
        return await handler(None, request)
