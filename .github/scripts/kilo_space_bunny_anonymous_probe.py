"""One-shot anonymous Kilo Space Bunny live probe (#3221).

This proves only the raw anonymous Kilo Gateway path. It never reads an API
key, never sends Authorization, never retries, and prints bounded evidence.
Default invocation cannot reach the network; live execution requires an
explicit authorized marker.
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
    prefix = "SPACE_BUNNY_ANON_TEXT" if modality == MODALITY_TEXT else "SPACE_BUNNY_ANON_IMAGE"
    post_count = 0
    try:
        body = canonical_body(modality)
        headers = canonical_headers()
        if any(key.lower() == "authorization" for key in headers):
            raise ValueError("authorization_forbidden")
        post_count += 1
        status, raw = transport(body, headers)
    except Exception:
        print(f"{prefix}=FAIL_NETWORK")
        print(f"KILO_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    payload = _parse(raw)
    if status != 200:
        print(f"{prefix}=FAIL_HTTP")
        print(f"KILO_ANON_HTTP={status}")
        print(f"ERROR_CODE={_safe_error_code(payload)}")
        print(f"KILO_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        print("REQUEST_AUTH_MODE=ANONYMOUS")
        print(f"REQUEST_MODEL={UPSTREAM_MODEL}")
        print("RAW_RESPONSE_OUTPUT=0")
        print("RAW_IMAGE_OUTPUT=0")
        return 1

    nonempty, response_model = _success(payload)
    if not nonempty:
        print(f"{prefix}=FAIL_NONCANONICAL_SUCCESS")
        print("KILO_ANON_HTTP=200")
        print(f"KILO_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    print(f"{prefix}=PASS")
    print("KILO_ANON_HTTP=200")
    print("REQUEST_AUTH_MODE=ANONYMOUS")
    print(f"REQUEST_MODEL={UPSTREAM_MODEL}")
    print(f"RESPONSE_MODEL={response_model}")
    print(f"RESPONSE_MODEL_MATCH={'YES' if response_model == UPSTREAM_MODEL else 'NO'}")
    print("NONEMPTY_TEXT_OUTPUT=YES")
    print(f"IMAGE_ACCEPTED={'YES' if modality == MODALITY_IMAGE else 'N/A'}")
    print(f"KILO_POST_COUNT={post_count}")
    print("NETWORK_RETRY_COUNT=0")
    print("FALLBACK=0")
    print("RAW_RESPONSE_OUTPUT=0")
    print("RAW_IMAGE_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    return 0


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
    return run(modality)


if __name__ == "__main__":
    raise SystemExit(main())
