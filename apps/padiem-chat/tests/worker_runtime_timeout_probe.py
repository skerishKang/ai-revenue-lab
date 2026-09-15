from __future__ import annotations

import json
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(str(request.url)).path
        if path == "/ready":
            return Response("ok", status=200)

        if path != "/probe":
            return Response("not found", status=404)

        result = {
            "abortsignal_import": False,
            "abortsignal_timeout_call": False,
            "fetch_accepts_signal": False,
            "local_normal_fetch": False,
            "local_delay_timeout": False,
            "local_body_timeout": False,
        }

        try:
            from js import AbortSignal  # type: ignore

            result["abortsignal_import"] = True
            signal = AbortSignal.timeout(50)
            result["abortsignal_timeout_call"] = signal is not None

            from app import httpx_compat as compat

            async with compat.AsyncClient(
                timeout=compat.Timeout(1.0, connect=0.5),
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "GET",
                    "http://127.0.0.1:9099/normal",
                ) as response:
                    chunks = [chunk async for chunk in response.aiter_bytes()]
                    body = b"".join(chunks)
                    result["fetch_accepts_signal"] = response.status_code == 200
                    result["local_normal_fetch"] = body == b"normal-ok"

            try:
                async with compat.AsyncClient(
                    timeout=compat.Timeout(0.15, connect=0.05),
                    follow_redirects=False,
                ) as client:
                    async with client.stream(
                        "GET",
                        "http://127.0.0.1:9099/slow-headers",
                    ):
                        pass
            except compat.ReadTimeout:
                result["local_delay_timeout"] = True

            try:
                async with compat.AsyncClient(
                    timeout=compat.Timeout(0.15, connect=0.05),
                    follow_redirects=False,
                ) as client:
                    async with client.stream(
                        "GET",
                        "http://127.0.0.1:9099/slow-body",
                    ) as response:
                        async for _ in response.aiter_bytes():
                            pass
            except compat.ReadTimeout:
                result["local_body_timeout"] = True
        except Exception as exc:
            result["error_type"] = type(exc).__name__
            result["error"] = str(exc)

        ok = all(
            result.get(name) is True
            for name in (
                "abortsignal_import",
                "abortsignal_timeout_call",
                "fetch_accepts_signal",
                "local_normal_fetch",
                "local_delay_timeout",
                "local_body_timeout",
            )
        )
        return Response(
            json.dumps(result, sort_keys=True),
            status=200 if ok else 500,
            headers={"Content-Type": "application/json"},
        )
