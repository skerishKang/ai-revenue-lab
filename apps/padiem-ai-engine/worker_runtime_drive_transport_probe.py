from __future__ import annotations

import json
import time
from urllib.parse import urlparse

import httpx
from workers import Response, WorkerEntrypoint

from app.cloudflare_external_transport import CloudflareExternalHttpTransport


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(str(request.url)).path
        if path == "/ready":
            return Response("ok", status=200)
        if path != "/probe":
            return Response("not found", status=404)

        result = {
            "real_httpx_transport_class": False,
            "worker_fetch_get": False,
            "incremental_body": False,
            "timeout_enforced": False,
            "host_gate": False,
        }
        try:
            transport = CloudflareExternalHttpTransport(
                allowed_hosts=frozenset({"127.0.0.1"}),
                allow_insecure_localhost=True,
            )
            result["real_httpx_transport_class"] = isinstance(
                transport, httpx.AsyncBaseTransport
            )
            async with httpx.AsyncClient(transport=transport, timeout=1.0) as client:
                normal = await client.get("http://127.0.0.1:9101/normal")
                result["worker_fetch_get"] = (
                    normal.status_code == 200 and normal.content == b"normal-ok"
                )

                started = time.monotonic()
                chunks = []
                first_elapsed = None
                async with client.stream("GET", "http://127.0.0.1:9101/chunks") as streamed:
                    async for chunk in streamed.aiter_bytes():
                        if first_elapsed is None:
                            first_elapsed = time.monotonic() - started
                        chunks.append(chunk)
                total_elapsed = time.monotonic() - started
                result["incremental_body"] = (
                    b"".join(chunks) == b"chunk-onechunk-two"
                    and first_elapsed is not None
                    and first_elapsed < 0.35
                    and total_elapsed >= 0.35
                )

                try:
                    await client.get(
                        "http://127.0.0.1:9101/slow-headers",
                        timeout=httpx.Timeout(0.15),
                    )
                except httpx.ReadTimeout:
                    result["timeout_enforced"] = True

                try:
                    await client.get("https://evil.example/drive/v3/files")
                except httpx.RequestError:
                    result["host_gate"] = True
        except Exception as exc:
            result["error_type"] = type(exc).__name__

        ok = all(result.get(key) is True for key in (
            "real_httpx_transport_class",
            "worker_fetch_get",
            "incremental_body",
            "timeout_enforced",
            "host_gate",
        ))
        return Response(
            json.dumps(result, sort_keys=True),
            status=200 if ok else 500,
            headers={"Content-Type": "application/json"},
        )
