from __future__ import annotations

import json
import time
from urllib.parse import urlparse

import httpx
from workers import Response, WorkerEntrypoint

from worker import CloudflareExternalHttpTransport


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(str(request.url)).path
        if path == "/ready":
            return Response("ok", status=200)

        if path != "/probe":
            return Response("not found", status=404)

        result = {
            "real_httpx_transport_class": False,
            "js_fetch_import": False,
            "abortsignal_import": False,
            "fetch_accepts_signal": False,
            "local_normal_fetch": False,
            "local_incremental_body": False,
            "local_delay_timeout": False,
            "local_body_timeout": False,
            "early_close_release": False,
        }

        try:
            from js import AbortSignal, fetch  # type: ignore

            result["js_fetch_import"] = fetch is not None
            result["abortsignal_import"] = AbortSignal.timeout(50) is not None

            transport = CloudflareExternalHttpTransport()
            result["real_httpx_transport_class"] = isinstance(
                transport,
                httpx.AsyncBaseTransport,
            )

            async with httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(1.0),
            ) as client:
                normal = await client.get("http://127.0.0.1:9099/normal")
                result["fetch_accepts_signal"] = normal.status_code == 200
                result["local_normal_fetch"] = normal.content == b"normal-ok"

                started = time.monotonic()
                first_elapsed = None
                chunks = []
                async with client.stream(
                    "GET",
                    "http://127.0.0.1:9099/chunks",
                ) as streamed:
                    async for chunk in streamed.aiter_bytes():
                        if first_elapsed is None:
                            first_elapsed = time.monotonic() - started
                        chunks.append(chunk)
                total_elapsed = time.monotonic() - started
                result["incremental_first_ms"] = (
                    None if first_elapsed is None else round(first_elapsed * 1000)
                )
                result["incremental_total_ms"] = round(total_elapsed * 1000)
                result["local_incremental_body"] = (
                    b"".join(chunks) == b"chunk-onechunk-two"
                    and first_elapsed is not None
                    and first_elapsed < 0.35
                    and total_elapsed >= 0.35
                )

                try:
                    async with client.stream(
                        "GET",
                        "http://127.0.0.1:9099/slow-headers",
                        timeout=httpx.Timeout(0.15),
                    ):
                        pass
                except httpx.ReadTimeout:
                    result["local_delay_timeout"] = True

                try:
                    async with client.stream(
                        "GET",
                        "http://127.0.0.1:9099/slow-body",
                        timeout=httpx.Timeout(0.15),
                    ) as slow_body:
                        async for _ in slow_body.aiter_bytes():
                            pass
                except httpx.ReadTimeout:
                    result["local_body_timeout"] = True

                async with client.stream(
                    "GET",
                    "http://127.0.0.1:9099/chunks",
                ) as early:
                    iterator = early.aiter_bytes()
                    first = await anext(iterator)
                    if first:
                        await early.aclose()
                        result["early_close_release"] = True
        except Exception as exc:
            result["error_type"] = type(exc).__name__
            result["error"] = str(exc)

        ok = all(
            result.get(name) is True
            for name in (
                "real_httpx_transport_class",
                "js_fetch_import",
                "abortsignal_import",
                "fetch_accepts_signal",
                "local_normal_fetch",
                "local_incremental_body",
                "local_delay_timeout",
                "local_body_timeout",
                "early_close_release",
            )
        )
        return Response(
            json.dumps(result, sort_keys=True),
            status=200 if ok else 500,
            headers={"Content-Type": "application/json"},
        )
