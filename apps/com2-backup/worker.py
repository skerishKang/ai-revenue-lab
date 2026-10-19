"""Private COM2 backup transfer Worker.

Routes (all bearer-authenticated)
---------------------------------
``PUT  /internal/v1/com2-backup/{machine}/{backup_id}/payload``
    Bounded archive upload. Requires ``X-Padiem-Content-Sha256``. The Worker
    recomputes the digest, reads the object back and fails closed if the stored
    bytes do not match. An existing key is never overwritten: identical bytes
    answer ``already_present``, different bytes answer
    ``backup_conflict_no_overwrite``.

``PUT  /internal/v1/com2-backup/{machine}/{backup_id}/manifest``
    Stores the validated JSON manifest. Same no-overwrite rule.

``GET  /internal/v1/com2-backup/{machine}/{backup_id}/payload|manifest``
    Download for a local restore check.

``POST /internal/v1/com2-backup/{machine}/{backup_id}/verify``
    Recomputes the stored payload checksum and compares it with the manifest.

``GET  /internal/v1/com2-backup/capabilities``
    Contract limits only. States that retention/cost policy is undecided, so no
    reader mistakes this slice for a lifecycle policy.

There is deliberately no delete route and no lifecycle rule. The committed
wrangler config keeps ``COM2_BACKUP_ENABLED = "false"``; every route fails
closed until an Owner-authorized deployment flips it. The bearer token is
resolved from a Secrets Store binding and is never returned or logged.
"""

from __future__ import annotations

import inspect
import json

from workers import Response, WorkerEntrypoint

import backup_contract as contract

JSON_HEADERS = {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}
PAYLOAD_HEADERS = {
    "Content-Type": "application/gzip",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}

CHECKSUM_HEADER = "x-padiem-content-sha256"


def _json(status: int, body: dict) -> Response:
    return Response(json.dumps(body, separators=(",", ":")), status=status, headers=JSON_HEADERS)


def _ok(body: dict) -> Response:
    payload = {"ok": True}
    payload.update(body)
    return _json(200, payload)


def _error(code: str) -> Response:
    return _json(contract.status_for_code(code), {"ok": False, "error": {"code": code}})


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _resolve_secret(env, binding_name: str) -> str:
    """Resolve a Secrets Store handle or a plain test string; never log it."""
    value = getattr(env, binding_name, None)
    if value is None:
        return ""
    getter = getattr(value, "get", None)
    if callable(getter):
        try:
            resolved = await _maybe_await(getter())
        except Exception:
            return ""
        return str(resolved) if resolved is not None else ""
    return value if isinstance(value, str) else ""


async def _require_enabled(env) -> None:
    if not contract.gate_is_open(getattr(env, contract.ENABLED_BINDING, None)):
        raise contract.BackupError("backup_disabled", 503)


async def _require_token(env, request) -> None:
    expected = await _resolve_secret(env, contract.TOKEN_BINDING)
    if not expected:
        # Never invent a token or fall back to an unauthenticated mode.
        raise contract.BackupError("backup_token_unavailable", 503)
    headers = getattr(request, "headers", None)
    raw = headers.get("authorization") if headers is not None else None
    provided = contract.parse_bearer(raw)
    if provided is None or not contract.token_matches(provided, expected):
        raise contract.BackupError("backup_unauthorized", 401)


def _bucket(env):
    bucket = getattr(env, contract.BUCKET_BINDING, None)
    if bucket is None:
        raise contract.BackupError("backup_storage_unavailable", 503)
    # Only the two operations this slice uses are required. The Worker never
    # calls delete, and it does not depend on an unproven HEAD binding shape.
    for name in ("put", "get"):
        if not callable(getattr(bucket, name, None)):
            raise contract.BackupError("backup_storage_unavailable", 503)
    return bucket


def _chunk_reader(request):
    """Read the request stream one chunk at a time, never fully buffering it."""
    body = getattr(request, "body", None)
    if body is None or not hasattr(body, "getReader"):
        raise contract.BackupError("invalid_body", 400)
    reader = body.getReader()
    finished = False

    async def read(limit: int):
        nonlocal finished
        if finished:
            return None
        result = await reader.read()
        done = bool(getattr(result, "done", False))
        value = getattr(result, "value", None)
        if done or value is None:
            finished = True
            release = getattr(reader, "releaseLock", None)
            if callable(release):
                release()
            return None
        if isinstance(value, str):
            data = value.encode("utf-8")
        elif isinstance(value, (bytes, bytearray, memoryview)):
            data = bytes(value)
        else:
            declared = getattr(value, "byteLength", None)
            if declared is None:
                declared = getattr(value, "length", None)
            if isinstance(declared, int) and not isinstance(declared, bool) and declared > limit:
                raise contract.BackupError("request_too_large", 413)
            data = bytes(value)
        if len(data) > limit:
            raise contract.BackupError("request_too_large", 413)
        return data

    return read


async def _read_body(request, max_bytes: int) -> bytes:
    headers = getattr(request, "headers", None)
    declared = contract.declared_content_length(
        headers.get("content-length") if headers is not None else None
    )
    if declared is not None and declared > max_bytes:
        raise contract.BackupError("request_too_large", 413)
    return await contract.read_bounded_body(_chunk_reader(request), max_bytes)


async def _object_bytes(obj) -> bytes:
    """Read a real R2 object body or a bytes-shaped test double."""
    array_buffer = getattr(obj, "arrayBuffer", None)
    if callable(array_buffer):
        data = await _maybe_await(array_buffer())
        to_bytes = getattr(data, "to_bytes", None)
        if callable(to_bytes):
            data = to_bytes()
        return bytes(data)
    body = getattr(obj, "body", obj)
    data = await _maybe_await(body)
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    raise contract.BackupError("backup_storage_unavailable", 503)


async def _read_object(bucket, key: str, max_bytes: int) -> bytes | None:
    obj = await _maybe_await(bucket.get(key))
    if obj is None:
        return None
    size = getattr(obj, "size", None)
    if isinstance(size, int) and not isinstance(size, bool) and size > max_bytes:
        # An object written out of band must not be buffered into the isolate.
        raise contract.BackupError("stored_object_too_large", 502)
    return await _object_bytes(obj)


async def _existing_state(bucket, key: str, data: bytes, max_bytes: int) -> str | None:
    """``None`` when absent, ``identical`` or ``conflict`` when present.

    The existing object is read and compared; it is never overwritten. This
    uses only the R2 ``get`` operation already proven in the workspace storage
    code, rather than relying on a separate HEAD binding shape.
    """
    stored = await _read_object(bucket, key, max_bytes)
    if stored is None:
        return None
    return "identical" if stored == data else "conflict"


async def _put_if_absent(
    bucket, key: str, data: bytes, *, content_type: str, max_bytes: int
) -> str:
    state = await _existing_state(bucket, key, data, max_bytes)
    if state == "identical":
        return "already_present"
    if state == "conflict":
        raise contract.BackupError("backup_conflict_no_overwrite", 409)
    await _maybe_await(
        bucket.put(
            key,
            data,
            httpMetadata={"contentType": content_type, "cacheControl": "no-store"},
        )
    )
    stored = await _read_object(bucket, key, max_bytes)
    if stored is None or stored != data:
        raise contract.BackupError("backup_write_unverified", 502)
    return "stored"


def _require_json_content_type(request) -> None:
    headers = getattr(request, "headers", None)
    value = headers.get("content-type") if headers is not None else None
    if (
        not isinstance(value, str)
        or value.split(";", 1)[0].strip().lower() != "application/json"
    ):
        raise contract.BackupError("unsupported_media_type", 415)


async def _handle_put_payload(env, route, request) -> Response:
    headers = getattr(request, "headers", None)
    declared_sha = contract.validate_sha256(
        headers.get(CHECKSUM_HEADER) if headers is not None else None
    )
    data = await _read_body(request, contract.MAX_PAYLOAD_BYTES)
    if not data:
        raise contract.BackupError("empty_payload", 400)
    actual_sha = contract.sha256_hex(data)
    if not contract.token_matches(actual_sha, declared_sha):
        # Reuse the constant-time comparison; both sides are hex strings and the
        # content is not a secret, but the timing discipline stays uniform.
        raise contract.BackupError("checksum_mismatch", 400)
    key = contract.object_key(route.machine, route.backup_id, contract.ARTIFACT_PAYLOAD)
    result = await _put_if_absent(
        _bucket(env),
        key,
        data,
        content_type="application/gzip",
        max_bytes=contract.MAX_PAYLOAD_BYTES,
    )
    return _ok({"result": result, "bytes": len(data), "sha256": actual_sha})


async def _handle_put_manifest(env, route, request) -> Response:
    _require_json_content_type(request)
    raw = await _read_body(request, contract.MAX_MANIFEST_BYTES)
    if not raw:
        raise contract.BackupError("invalid_manifest", 400)
    manifest = contract.parse_manifest_bytes(raw, route.machine, route.backup_id)
    key = contract.object_key(route.machine, route.backup_id, contract.ARTIFACT_MANIFEST)
    result = await _put_if_absent(
        _bucket(env),
        key,
        raw,
        content_type="application/json",
        max_bytes=contract.MAX_MANIFEST_BYTES,
    )
    return _ok({"result": result, "file_count": manifest["file_count"]})


async def _handle_get(env, route) -> Response:
    artifact = route.action
    key = contract.object_key(route.machine, route.backup_id, artifact)
    data = await _read_object(
        _bucket(env),
        key,
        contract.MAX_PAYLOAD_BYTES
        if artifact == contract.ARTIFACT_PAYLOAD
        else contract.MAX_MANIFEST_BYTES,
    )
    if data is None:
        code = "payload_not_found" if artifact == contract.ARTIFACT_PAYLOAD else "manifest_not_found"
        raise contract.BackupError(code, 404)
    if artifact == contract.ARTIFACT_PAYLOAD:
        headers = dict(PAYLOAD_HEADERS)
        headers["Content-Length"] = str(len(data))
        return Response(data, status=200, headers=headers)
    headers = dict(JSON_HEADERS)
    headers["Content-Length"] = str(len(data))
    return Response(data, status=200, headers=headers)


async def _handle_verify(env, route) -> Response:
    bucket = _bucket(env)
    manifest_key = contract.object_key(
        route.machine, route.backup_id, contract.ARTIFACT_MANIFEST
    )
    payload_key = contract.object_key(
        route.machine, route.backup_id, contract.ARTIFACT_PAYLOAD
    )
    raw_manifest = await _read_object(bucket, manifest_key, contract.MAX_MANIFEST_BYTES)
    if raw_manifest is None:
        raise contract.BackupError("manifest_not_found", 404)
    manifest = contract.parse_manifest_bytes(raw_manifest, route.machine, route.backup_id)
    payload = await _read_object(bucket, payload_key, contract.MAX_PAYLOAD_BYTES)
    if payload is None:
        raise contract.BackupError("payload_not_found", 404)
    result = contract.integrity_result(manifest, payload)
    return _ok({"result": "verified", **result})


def _handle_capabilities() -> Response:
    return _ok(
        {
            "contract_version": contract.CONTRACT_VERSION,
            "max_payload_bytes": contract.MAX_PAYLOAD_BYTES,
            "max_manifest_bytes": contract.MAX_MANIFEST_BYTES,
            "max_manifest_files": contract.MAX_MANIFEST_FILES,
            "overwrite_policy": "STOP_NO_OVERWRITE",
            "delete_route": False,
            # No lifecycle rule, no storage class and no deletion policy is
            # asserted here; that decision belongs to the Owner.
            "retention_policy": "undecided",
        }
    )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        try:
            # Gate first: no Secret read and no storage call while OFF.
            await _require_enabled(self.env)
            await _require_token(self.env, request)
            route = contract.parse_route(getattr(request, "url", ""))
            if route is None:
                raise contract.BackupError("not_found", 404)
            method = contract.normalize_method(getattr(request, "method", ""))
            if route.action == "capabilities":
                if method != "GET":
                    raise contract.BackupError("method_not_allowed", 405)
                return _handle_capabilities()
            if route.action == contract.ARTIFACT_PAYLOAD:
                if method == "PUT":
                    return await _handle_put_payload(self.env, route, request)
                if method == "GET":
                    return await _handle_get(self.env, route)
                raise contract.BackupError("method_not_allowed", 405)
            if route.action == contract.ARTIFACT_MANIFEST:
                if method == "PUT":
                    return await _handle_put_manifest(self.env, route, request)
                if method == "GET":
                    return await _handle_get(self.env, route)
                raise contract.BackupError("method_not_allowed", 405)
            if route.action == contract.ARTIFACT_VERIFY:
                if method != "POST":
                    raise contract.BackupError("method_not_allowed", 405)
                return await _handle_verify(self.env, route)
            raise contract.BackupError("not_found", 404)
        except contract.BackupError as exc:
            return _error(exc.code)
        except Exception:
            # Bounded envelope. Never leak a stack trace, binding value or R2
            # detail to the caller.
            return _error("backup_storage_unavailable")
