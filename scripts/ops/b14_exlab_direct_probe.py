"""B14/ExLab outage triage: one opt-in local *direct* provider request.

Default performs zero network calls. Never prints credentials, prompt content,
response text, authorization headers, vendor raw errors, or private file paths.

Local usage:
  python scripts/ops/b14_exlab_direct_probe.py                  # dry run
  $env:PADIEM_EXLAB_CREDENTIAL_NOTE = "<owner's local private note path>"
  python scripts/ops/b14_exlab_direct_probe.py --send           # one call
Requires httpx installed (python -m pip install httpx).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

URL = "https://api.experientiallabs.ai/v1/chat/completions"
MODEL = "qwen3.8-flash-next-uncensored"
MARKER = "EXLAB_OK"
PROMPT = "Connection test. Reply with exactly: EXLAB_OK"
KEY_ENV = "PADIEM_EXLAB_API_KEY"
NOTE_ENV = "PADIEM_EXLAB_CREDENTIAL_NOTE"
KNOWN_VENDOR_CODES = frozenset(
    {"unavailable_route", "deadline_exceeded", "insufficient_quota",
     "rate_limit_exceeded", "invalid_api_key", "model_not_found"}
)


class CredentialSourceError(Exception):
    """No credential available; details deliberately not retained."""


def _valid_key(key: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{30,200}", key))


def _key_from_private_note(note_path: str) -> str:
    try:
        lines = Path(note_path).read_text(
            encoding="utf-8-sig", errors="replace"
        ).splitlines()
    except (OSError, ValueError) as exc:
        raise CredentialSourceError from exc
    indices = []
    for index, value in enumerate(lines):
        try:
            u = urlsplit(value.strip())
            if (
                u.scheme in ("https", "http")
                and u.hostname == "platform.experientiallabs.ai"
                and not u.username and not u.password
                and not u.query and not u.fragment
                and u.path in ("", "/")
            ):
                indices.append(index)
        except ValueError:
            continue
    if len(indices) != 1 or indices[0] + 1 >= len(lines):
        raise CredentialSourceError
    key = lines[indices[0] + 1].strip()
    if not _valid_key(key):
        raise CredentialSourceError
    return key


def _get_key() -> str:
    value = os.environ.get(KEY_ENV, "").strip()
    path = os.environ.get(NOTE_ENV, "").strip()
    if bool(value) == bool(path):
        raise CredentialSourceError
    if path:
        return _key_from_private_note(path)
    if not _valid_key(value):
        raise CredentialSourceError
    return value


def _safe_vendor_code(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) and code in KNOWN_VENDOR_CODES else None


def _classification(status: int, code: str | None) -> str:
    if status == 429 and code == "unavailable_route":
        return "ROUTE_UNAVAILABLE"
    if status == 503 or code == "deadline_exceeded":
        return "PROVIDER_UNAVAILABLE_OR_DEADLINE"
    if status == 429:
        return "RATE_LIMIT_OR_CAPACITY"
    if status in (401, 403):
        return "AUTH_OR_PERMISSION"
    if status >= 500:
        return "PROVIDER_SERVER_ERROR"
    if status == 200:
        return "PROVIDER_REPLIED"
    return "OTHER_HTTP_ERROR"


def execute(send: bool) -> tuple[dict[str, object], int]:
    result: dict[str, object] = {
        "route": "direct_exlab",
        "model": MODEL,
        "calls_sent": 0,
        "retry_count": 0,
        "fallback_used": False,
    }
    if not send:
        result["result"] = "DRY_RUN_NO_NETWORK"
        return result, 0

    try:
        key = _get_key()
    except CredentialSourceError:
        result["result"] = "CREDENTIAL_SOURCE_MISSING_OR_AMBIGUOUS"
        return result, 2

    try:
        import httpx
    except ImportError:
        result["result"] = "HTTPX_DEPENDENCY_MISSING"
        return result, 2

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 32,
        "stream": False,
    }
    started = time.monotonic()
    result["calls_sent"] = 1
    try:
        # Explicitly single request; httpx does not retry by default.
        with httpx.Client(
            timeout=httpx.Timeout(connect=15.0, read=40.0, write=15.0, pool=5.0),
            follow_redirects=False,
            trust_env=True,
        ) as client:
            response = client.post(
                URL,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {key}"},
                json=payload,
            )
        result["http_status"] = response.status_code
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            body = {}
        code = _safe_vendor_code(body)
        result["vendor_code"] = code
        result["classification"] = _classification(response.status_code, code)
        result["retry_after_present"] = bool(response.headers.get("retry-after"))
        choices = body.get("choices") if isinstance(body, dict) else None
        first = (
            choices[0] if isinstance(choices, list) and choices
            and isinstance(choices[0], dict) else {}
        )
        message = first.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        actual_model = body.get("model") if isinstance(body, dict) else None
        result["actual_model_matched"] = actual_model == MODEL
        result["response_marker_matched"] = (
            isinstance(content, str) and content.strip() == MARKER
        )
        passed = (
            response.status_code == 200
            and result["actual_model_matched"]
            and result["response_marker_matched"]
        )
        result["result"] = "PASS" if passed else "FAIL"
        exit_code = 0 if passed else 1
    except httpx.TimeoutException as exc:
        result.update(
            classification="TRANSPORT_TIMEOUT",
            exception_class=type(exc).__name__,
            result="UNKNOWN_DELIVERY_NO_AUTO_RETRY",
        )
        exit_code = 1
    except httpx.RequestError as exc:
        result.update(
            classification="TRANSPORT_ERROR",
            exception_class=type(exc).__name__,
            result="UNKNOWN_DELIVERY_NO_AUTO_RETRY",
        )
        exit_code = 1
    finally:
        key = ""
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send", action="store_true",
        help="Send exactly one real provider POST; default is NO NETWORK.",
    )
    args = parser.parse_args(argv)
    result, exit_code = execute(args.send)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
