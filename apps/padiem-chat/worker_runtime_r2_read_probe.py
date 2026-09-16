from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from app.workspace_storage import ClawDocumentMetadata, DOCX_MEDIA_TYPE, WorkspaceDocumentStore

_PAYLOAD = b"PK-worker-r2-objectbody-probe"
_TENANT = "tenant_worker_r2_probe"
_DOC_ID = "doc_" + "a" * 32
_NOW = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)


class _MetadataStore:
    async def get_active(self, document_id):
        if document_id != _DOC_ID:
            return None
        return ClawDocumentMetadata(
            document_id=_DOC_ID,
            tenant_id=_TENANT,
            object_key="synthetic/private/object",
            filename="probe.docx",
            media_type=DOCX_MEDIA_TYPE,
            byte_length=len(_PAYLOAD),
            created_at=_NOW,
            expires_at=_NOW + timedelta(days=1),
        )


class _UnreadableStreamBody:
    def __bytes__(self):
        raise RuntimeError("stream body conversion must not be used")


class _RuntimeR2ObjectBody:
    def __init__(self) -> None:
        self.body = _UnreadableStreamBody()
        self.array_buffer_calls = 0

    async def arrayBuffer(self):
        from js import Uint8Array  # type: ignore

        self.array_buffer_calls += 1
        view = Uint8Array.new(len(_PAYLOAD))
        for index, value in enumerate(_PAYLOAD):
            view[index] = value
        return view.buffer


class _Bucket:
    def __init__(self) -> None:
        self.obj = _RuntimeR2ObjectBody()
        self.get_calls = 0

    async def get(self, key):
        if key != "synthetic/private/object":
            raise RuntimeError("unexpected key")
        self.get_calls += 1
        return self.obj


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(str(request.url)).path
        if path == "/ready":
            return Response("ok", status=200)
        if path != "/probe":
            return Response("not found", status=404)

        result = {
            "js_arraybuffer_to_bytes": False,
            "object_arraybuffer_called_once": False,
            "bucket_get_called_once": False,
            "stream_body_not_used": False,
            "payload_matches": False,
            "unexpected_exception": False,
        }
        bucket = _Bucket()
        try:
            store = WorkspaceDocumentStore(_MetadataStore(), bucket)
            metadata, payload = await store.get_for_tenant(
                tenant_id=_TENANT,
                document_id=_DOC_ID,
                now=_NOW,
            )
            del metadata
            result["object_arraybuffer_called_once"] = bucket.obj.array_buffer_calls == 1
            result["bucket_get_called_once"] = bucket.get_calls == 1
            result["stream_body_not_used"] = bucket.obj.array_buffer_calls == 1
            result["payload_matches"] = payload == _PAYLOAD
            result["js_arraybuffer_to_bytes"] = payload == _PAYLOAD
        except Exception as exc:
            result["unexpected_exception"] = True
            result["error_type"] = type(exc).__name__

        ok = all(
            result[name] is True
            for name in (
                "js_arraybuffer_to_bytes",
                "object_arraybuffer_called_once",
                "bucket_get_called_once",
                "stream_body_not_used",
                "payload_matches",
            )
        ) and not result["unexpected_exception"]
        return Response(
            json.dumps(result, sort_keys=True),
            status=200 if ok else 500,
            headers={"Content-Type": "application/json"},
        )
