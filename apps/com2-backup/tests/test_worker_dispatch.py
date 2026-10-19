from __future__ import annotations

import hashlib
import json

import pytest

import fake_workers as fw

worker = fw.install_workers_module()
import backup_contract as contract  # noqa: E402  (after the fake runtime is installed)

BASE = "https://backup.internal/internal/v1/com2-backup/com2/20261019t120000z"
PAYLOAD = b"fixture-archive-bytes"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
FILE_BYTES = b"fixture file content\n"
FILE_SHA = hashlib.sha256(FILE_BYTES).hexdigest()


def manifest_bytes(**overrides):
    data = {
        "kind": contract.MANIFEST_KIND,
        "contract_version": contract.CONTRACT_VERSION,
        "machine": "com2",
        "backup_id": "20261019t120000z",
        "created_at": "2026-10-19T12:00:00Z",
        "payload_file": "payload.tar.gz",
        "payload_bytes": len(PAYLOAD),
        "payload_sha256": PAYLOAD_SHA,
        "file_count": 1,
        "total_bytes": len(FILE_BYTES),
        "files": [
            {"path": "root-1/state/state.txt", "bytes": len(FILE_BYTES), "sha256": FILE_SHA}
        ],
        "exclusions": {"secret_paths": 2},
    }
    data.update(overrides)
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


async def call(env, method, path, body=b"", headers=None, auth=True):
    merged = dict(headers or {})
    if auth:
        merged.setdefault("authorization", f"Bearer {fw.TOKEN}")
    url = path if str(path).startswith("http") else "https://backup.internal" + path
    request = fw.FakeRequest(method, url, headers=merged, body=body)
    return await worker.Default(env).fetch(request)


def payload_request_headers():
    return {
        "x-padiem-content-sha256": PAYLOAD_SHA,
        "content-type": "application/gzip",
    }


def decode(response):
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_disabled_gate_fails_before_auth_or_storage():
    env = fw.disabled_env()
    response = await call(env, "GET", "/internal/v1/com2-backup/capabilities", auth=False)
    assert response.status == 503
    assert decode(response)["error"]["code"] == "backup_disabled"
    assert env.COM2_BACKUP_BUCKET.put_calls == []


@pytest.mark.asyncio
async def test_enabled_without_token_binding_fails_closed():
    env = fw.enabled_env(COM2_BACKUP_WRITE_TOKEN=None)
    response = await call(env, "GET", "/internal/v1/com2-backup/capabilities")
    assert response.status == 503
    assert decode(response)["error"]["code"] == "backup_token_unavailable"


@pytest.mark.asyncio
async def test_wrong_and_missing_token_are_unauthorized():
    env = fw.enabled_env()
    for headers, auth in (({"authorization": "Bearer wrong-value"}, False), ({}, False)):
        response = await call(env, "GET", "/internal/v1/com2-backup/capabilities", headers=headers, auth=auth)
        assert response.status == 401
        assert decode(response)["error"]["code"] == "backup_unauthorized"


@pytest.mark.asyncio
async def test_capabilities_state_that_retention_is_undecided():
    response = await call(fw.enabled_env(), "GET", "/internal/v1/com2-backup/capabilities")
    body = decode(response)
    assert response.status == 200
    assert body["ok"] is True
    assert body["retention_policy"] == "undecided"
    assert body["delete_route"] is False
    assert body["overwrite_policy"] == "STOP_NO_OVERWRITE"


@pytest.mark.asyncio
async def test_payload_upload_is_stored_and_read_back():
    env = fw.enabled_env()
    response = await call(env, "PUT", BASE + "/payload", PAYLOAD, payload_request_headers())
    assert response.status == 200
    assert decode(response) == {"ok": True, "result": "stored", "bytes": len(PAYLOAD), "sha256": PAYLOAD_SHA}

    response = await call(env, "GET", BASE + "/payload")
    assert response.status == 200
    assert response.body == PAYLOAD
    assert response.headers["Content-Type"] == "application/gzip"


@pytest.mark.asyncio
async def test_identical_upload_is_idempotent_and_never_reputs():
    env = fw.enabled_env()
    await call(env, "PUT", BASE + "/payload", PAYLOAD, payload_request_headers())
    put_calls = len(env.COM2_BACKUP_BUCKET.put_calls)
    response = await call(env, "PUT", BASE + "/payload", PAYLOAD, payload_request_headers())
    assert response.status == 200
    assert decode(response)["result"] == "already_present"
    assert len(env.COM2_BACKUP_BUCKET.put_calls) == put_calls


@pytest.mark.asyncio
async def test_different_bytes_are_never_overwritten():
    env = fw.enabled_env()
    await call(env, "PUT", BASE + "/payload", PAYLOAD, payload_request_headers())

    other = b"different-archive-bytes"
    headers = {
        "x-padiem-content-sha256": hashlib.sha256(other).hexdigest(),
        "content-type": "application/gzip",
    }
    response = await call(env, "PUT", BASE + "/payload", other, headers)
    assert response.status == 409
    assert decode(response)["error"]["code"] == "backup_conflict_no_overwrite"

    key = contract.object_key("com2", "20261019t120000z", "payload")
    assert env.COM2_BACKUP_BUCKET.objects[key] == PAYLOAD


@pytest.mark.asyncio
async def test_checksum_mismatch_is_rejected_before_storage():
    env = fw.enabled_env()
    headers = {"x-padiem-content-sha256": hashlib.sha256(b"other").hexdigest()}
    response = await call(env, "PUT", BASE + "/payload", PAYLOAD, headers)
    assert response.status == 400
    assert decode(response)["error"]["code"] == "checksum_mismatch"
    assert env.COM2_BACKUP_BUCKET.objects == {}


@pytest.mark.asyncio
async def test_missing_checksum_header_is_rejected():
    response = await call(fw.enabled_env(), "PUT", BASE + "/payload", PAYLOAD)
    assert response.status == 400
    assert decode(response)["error"]["code"] == "invalid_checksum"


@pytest.mark.asyncio
async def test_declared_oversize_is_rejected_without_reading():
    headers = dict(payload_request_headers())
    headers["content-length"] = str(contract.MAX_PAYLOAD_BYTES + 1)
    response = await call(fw.enabled_env(), "PUT", BASE + "/payload", PAYLOAD, headers)
    assert response.status == 413
    assert decode(response)["error"]["code"] == "request_too_large"


@pytest.mark.asyncio
async def test_empty_payload_is_rejected():
    response = await call(
        fw.enabled_env(),
        "PUT",
        BASE + "/payload",
        b"",
        {"x-padiem-content-sha256": hashlib.sha256(b"").hexdigest()},
    )
    assert response.status == 400
    assert decode(response)["error"]["code"] == "empty_payload"


@pytest.mark.asyncio
async def test_manifest_upload_and_download_are_byte_exact():
    env = fw.enabled_env()
    raw = manifest_bytes()
    response = await call(
        env, "PUT", BASE + "/manifest", raw, {"content-type": "application/json"}
    )
    assert response.status == 200
    assert decode(response)["file_count"] == 1

    response = await call(env, "GET", BASE + "/manifest")
    assert response.status == 200
    assert response.body == raw


@pytest.mark.asyncio
async def test_manifest_conflict_is_not_overwritten():
    env = fw.enabled_env()
    raw = manifest_bytes()
    await call(env, "PUT", BASE + "/manifest", raw, {"content-type": "application/json"})
    changed = manifest_bytes(exclusions={"secret_paths": 3})
    response = await call(
        env, "PUT", BASE + "/manifest", changed, {"content-type": "application/json"}
    )
    assert response.status == 409
    assert decode(response)["error"]["code"] == "backup_conflict_no_overwrite"


@pytest.mark.asyncio
async def test_manifest_requires_json_content_type():
    response = await call(
        fw.enabled_env(),
        "PUT",
        BASE + "/manifest",
        manifest_bytes(),
        {"content-type": "text/plain"},
    )
    assert response.status == 415
    assert decode(response)["error"]["code"] == "unsupported_media_type"


@pytest.mark.asyncio
async def test_manifest_validation_rejects_path_traversal():
    raw = manifest_bytes(
        files=[{"path": "../escape", "bytes": 1, "sha256": FILE_SHA}],
        total_bytes=1,
    )
    response = await call(
        fw.enabled_env(), "PUT", BASE + "/manifest", raw, {"content-type": "application/json"}
    )
    assert response.status == 400
    assert decode(response)["error"]["code"] == "invalid_manifest"


@pytest.mark.asyncio
async def test_verify_succeeds_and_detects_tampering():
    env = fw.enabled_env()
    await call(env, "PUT", BASE + "/payload", PAYLOAD, payload_request_headers())
    await call(
        env, "PUT", BASE + "/manifest", manifest_bytes(), {"content-type": "application/json"}
    )

    response = await call(env, "POST", BASE + "/verify")
    assert response.status == 200
    assert decode(response)["result"] == "verified"

    key = contract.object_key("com2", "20261019t120000z", "payload")
    env.COM2_BACKUP_BUCKET.objects[key] = PAYLOAD + b"tampered"
    response = await call(env, "POST", BASE + "/verify")
    assert response.status == 409
    assert decode(response)["error"]["code"] == "integrity_mismatch"


@pytest.mark.asyncio
async def test_verify_reports_missing_objects():
    env = fw.enabled_env()
    response = await call(env, "POST", BASE + "/verify")
    assert response.status == 404
    assert decode(response)["error"]["code"] == "manifest_not_found"

    await call(
        env, "PUT", BASE + "/manifest", manifest_bytes(), {"content-type": "application/json"}
    )
    response = await call(env, "POST", BASE + "/verify")
    assert response.status == 404
    assert decode(response)["error"]["code"] == "payload_not_found"


@pytest.mark.asyncio
async def test_there_is_no_delete_route_and_the_object_survives():
    env = fw.enabled_env()
    await call(env, "PUT", BASE + "/payload", PAYLOAD, payload_request_headers())
    response = await call(env, "DELETE", BASE + "/payload")
    assert response.status == 405
    assert decode(response)["error"]["code"] == "method_not_allowed"
    key = contract.object_key("com2", "20261019t120000z", "payload")
    assert key in env.COM2_BACKUP_BUCKET.objects
    assert not hasattr(env.COM2_BACKUP_BUCKET, "delete")


@pytest.mark.asyncio
async def test_unknown_route_is_404_after_authentication():
    response = await call(fw.enabled_env(), "GET", "/internal/v1/com2-backup/unknown")
    assert response.status == 404
    assert decode(response)["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_missing_bucket_and_storage_failure_are_bounded():
    response = await call(fw.enabled_env(COM2_BACKUP_BUCKET=None), "GET", BASE + "/payload")
    assert response.status == 503
    assert decode(response)["error"]["code"] == "storage_binding_missing"

    bucket = fw.FakeR2()
    bucket.fail_put = True
    response = await call(
        fw.enabled_env(COM2_BACKUP_BUCKET=bucket),
        "PUT",
        BASE + "/payload",
        PAYLOAD,
        payload_request_headers(),
    )
    assert response.status == 502
    assert decode(response)["error"]["code"] == "storage_write_failed"


class _PromiseLike:
    """Mimics a workerd JS Promise returned by ``arrayBuffer()``."""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def resolve():
            return self._value

        return resolve().__await__()


class _ArrayBufferProxy:
    """Mimics a Pyodide ArrayBuffer proxy: only ``to_bytes()`` exposes the data."""

    def __init__(self, data):
        self._data = data

    def to_bytes(self):
        return self._data


class _PromiseArrayBufferObject:
    def __init__(self, data):
        self.size = len(data)
        self._data = data

    def arrayBuffer(self):
        return _PromiseLike(_ArrayBufferProxy(self._data))


class _StreamOnlyObject:
    def __init__(self, data):
        self.size = len(data)
        self.body = fw._Stream(data, chunk=3)

    def arrayBuffer(self):
        raise RuntimeError("arrayBuffer unavailable")


def _bucket_serving(obj):
    bucket = fw.FakeR2()

    async def get(key):
        return obj

    bucket.get = get
    return bucket


@pytest.mark.asyncio
async def test_workerd_promise_arraybuffer_proxy_is_decoded():
    env = fw.enabled_env(COM2_BACKUP_BUCKET=_bucket_serving(_PromiseArrayBufferObject(PAYLOAD)))
    response = await call(env, "GET", BASE + "/payload")
    assert response.status == 200
    assert response.body == PAYLOAD


@pytest.mark.asyncio
async def test_workerd_null_proxy_is_treated_as_absent():
    """A missing R2 key returns a JS null proxy, not Python None."""
    js_null = type("JsNull", (), {})()
    env = fw.enabled_env(COM2_BACKUP_BUCKET=_bucket_serving(js_null))
    response = await call(env, "GET", BASE + "/payload")
    assert response.status == 404
    assert decode(response)["error"]["code"] == "payload_not_found"


@pytest.mark.asyncio
async def test_stream_body_is_used_when_arraybuffer_is_unavailable():
    env = fw.enabled_env(COM2_BACKUP_BUCKET=_bucket_serving(_StreamOnlyObject(PAYLOAD)))
    response = await call(env, "GET", BASE + "/payload")
    assert response.status == 200
    assert response.body == PAYLOAD
