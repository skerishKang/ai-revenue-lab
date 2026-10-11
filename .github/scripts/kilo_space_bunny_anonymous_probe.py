"""Retired Kilo Space Bunny anonymous live probe (fail-closed).

Owner final retirement decision (2026-10-07): the Space Bunny lane
(``stealth/space-bunny-alpha``) executes nowhere. This probe is retained as
historical source only and can no longer construct or send any request: the
default invocation and every authorized-live invocation both fail closed
before any network I/O.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

KILO_CHAT_URL = "https://api.kilo.ai/api/gateway/chat/completions"
UPSTREAM_MODEL = "stealth/space-bunny-alpha"
MODALITY_TEXT = "text"
MODALITY_IMAGE = "image"
TEXT_MAX_TOKENS = 32
IMAGE_MAX_TOKENS = 1024
REQUEST_TIMEOUT_SECONDS = 60
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
IMAGE_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "padiem-ai-core"
    / "tests"
    / "fixtures"
    / "b66_e2e_corpus"
    / "f11-simple-logo.png"
)
_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
Transport = Callable[[dict[str, Any], dict[str, str]], tuple[int, bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def canonical_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "User-Agent": "padiem-kilo-space-bunny-anonymous-probe/1.0",
    }


def _image_data_url() -> str:
    raw = IMAGE_FIXTURE.read_bytes()
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image_fixture_unavailable")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    elif len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        media_type = "image/webp"
    else:
        raise ValueError("image_fixture_unavailable")
    return f"data:{media_type};base64," + base64.b64encode(raw).decode("ascii")


def canonical_body(modality: str) -> dict[str, Any]:
    if modality == MODALITY_TEXT:
        content: Any = "Reply with the single word OK."
    elif modality == MODALITY_IMAGE:
        content = [
            {"type": "text", "text": "Describe this synthetic image briefly."},
            {"type": "image_url", "image_url": {"url": _image_data_url()}},
        ]
    else:
        raise ValueError("unsupported_modality")
    return {
        "model": UPSTREAM_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": IMAGE_MAX_TOKENS if modality == MODALITY_IMAGE else TEXT_MAX_TOKENS,
    }


def _http_post_once(body: dict[str, Any], headers: dict[str, str]) -> tuple[int, bytes]:
    if any(key.lower() == "authorization" for key in headers):
        raise ValueError("authorization_forbidden")
    request = urllib.request.Request(
        KILO_CHAT_URL,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return 599, b'{"error":{"code":"response_too_large"}}'
            return int(response.status), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raw = b'{"error":{"code":"response_too_large"}}'
        return int(exc.code), raw


def _parse(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _safe_error_code(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return "non_object_error"
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return "missing_error_code"
    code = error.get("code")
    if isinstance(code, str) and _SAFE_CODE_RE.fullmatch(code):
        return code
    return "unsafe_error_code"


def _success(payload: Any) -> tuple[bool, str]:
    if not isinstance(payload, Mapping):
        return False, "NONE"
    model = payload.get("model")
    choices = payload.get("choices")
    if not isinstance(model, str) or not model:
        return False, "NONE"
    if not isinstance(choices, list) or not choices:
        return False, model
    first = choices[0]
    if not isinstance(first, Mapping):
        return False, model
    message = first.get("message")
    if not isinstance(message, Mapping):
        return False, model
    answer = message.get("content")
    return isinstance(answer, str) and bool(answer.strip()), model


def run(modality: str, *, transport: Transport = _http_post_once) -> int:
    """Fail closed: the retired Space Bunny lane must never POST.

    Owner final retirement decision (2026-10-07). Retained for source
    continuity only; it now always reports the retirement block with zero
    posts and never touches the transport.
    """
    prefix = "SPACE_BUNNY_ANON_TEXT" if modality == MODALITY_TEXT else "SPACE_BUNNY_ANON_IMAGE"
    print(f"{prefix}=FAIL_RETIRED_LANE")
    print("KILO_POST_COUNT=0")
    print("NETWORK_RETRY_COUNT=0")
    print("RETIRED_LANE_EXECUTION=BLOCKED")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--authorized-live-run" not in args:
        print("KILO_SPACE_BUNNY_ANON_PROBE=FAIL_AUTHORIZATION_REQUIRED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        return 1
    modality = ""
    for token in args:
        if token.startswith("--modality="):
            modality = token.split("=", 1)[1]
    if modality not in (MODALITY_TEXT, MODALITY_IMAGE):
        print("KILO_SPACE_BUNNY_ANON_PROBE=FAIL_MODALITY")
        print("KILO_POST_COUNT=0")
        return 1
    # Owner final retirement decision (2026-10-07): the lane is retired, so
    # every authorized-live invocation now fails closed with zero posts.
    print("KILO_SPACE_BUNNY_ANON_PROBE=FAIL_RETIRED_LANE")
    print("KILO_POST_COUNT=0")
    print("NETWORK_RETRY_COUNT=0")
    print("RETIRED_LANE_EXECUTION=BLOCKED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
