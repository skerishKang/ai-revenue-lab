#!/usr/bin/env python3
"""Post-deploy smoke for the mock-only Padiem Chat Worker."""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "b62-preflight/1.0"


def request(url: str, *, method: str = "GET", payload: dict | None = None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method=method)
    with urlopen(req, timeout=20) as response:
        raw = response.read(1_048_576)
        return response.status, response.headers, raw


def request_with_retry(url: str, *, method: str = "GET", payload: dict | None = None):
    last = None
    for attempt in range(8):
        try:
            return request(url, method=method, payload=payload)
        except (HTTPError, URLError) as exc:
            last = exc
            if attempt == 7:
                raise
            time.sleep(3)
    raise RuntimeError(str(last))


def require_security(headers, *, api: bool) -> None:
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "no-referrer"
    if api:
        assert headers.get("Cache-Control") == "no-store"


def append_summary(lines: list[str]) -> None:
    target = os.getenv("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    base = os.getenv("B62_BASE_URL", "").strip().rstrip("/")
    if not base.startswith("https://"):
        print("B62_BASE_URL must be an https URL", file=sys.stderr)
        return 1

    try:
        root_status, _, root_raw = request_with_retry(base + "/")
        root_text = root_raw.decode("utf-8", "replace")
        assert root_status == 200
        assert "Padiem Chat" in root_text
        assert "무엇을 도와드릴까요" in root_text

        health_status, health_headers, health_raw = request_with_retry(base + "/health")
        assert health_status == 200
        require_security(health_headers, api=True)
        health = json.loads(health_raw.decode("utf-8"))
        assert health.get("status") == "ok"
        assert health.get("app") == "padiem-chat"
        assert health.get("runtime") == "mock"
        assert health.get("b14_configured") is False
        assert health.get("live_enabled") is False
        assert health.get("deep_research_ready") is False

        chat_status, chat_headers, chat_raw = request_with_retry(
            base + "/api/chat",
            method="POST",
            payload={"messages": [{"role": "user", "content": "안녕하세요"}], "mode": "auto"},
        )
        assert chat_status == 200
        require_security(chat_headers, api=True)
        chat = json.loads(chat_raw.decode("utf-8"))
        assert chat.get("runtime") == "mock"
        assert "실제 모델을 호출하지 않았습니다" in str(chat.get("answer", ""))

        print(f"B62_BASE_URL={base}")
        print("ROOT_HTTP=200")
        print("HEALTH_HTTP=200")
        print("RUNTIME=mock")
        print("B14_CONFIGURED=false")
        print("LIVE_ENABLED=false")
        print("DEEP_RESEARCH_READY=false")
        print("MOCK_CHAT_HTTP=200")
        print("REAL_PROVIDER_CALLS=0")
        append_summary([
            "## B62 post-deploy mock smoke",
            "",
            f"- URL: `{base}`",
            "- Root: PASS",
            "- Health: PASS (`runtime=mock`, `b14_configured=false`, `live_enabled=false`)",
            "- Deep Research readiness: `false`",
            "- Mock chat: PASS",
            "- API security headers: PASS",
            "- Real provider/model calls: `0`",
        ])
        return 0
    except Exception as exc:
        print(f"B62_MOCK_SMOKE_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
