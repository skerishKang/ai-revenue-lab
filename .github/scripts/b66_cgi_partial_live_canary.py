"""One-shot authenticated B66 CGI Production partial-input canary (#3391).

Consumes the existing Production Environment credential without printing it.
Per run: one password login, read-only auth/skill lookups, and exactly one B66
quote-interpret POST. No retry, fallback, Saved Quote Skill mutation, or raw
response output.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

BASE_URL = "https://quick-quote-kr.pages.dev"
PARTIAL_TEXT = "대한건설에 배관 100미터, 부가세 별도"
MAX_BODY_BYTES = 64 * 1024
MAX_INTERPRET_POSTS = 1
USER_AGENT = "padiem-b66-cgi-partial-canary/1.0 (+github-actions)"
RETRY = 0
FALLBACK = 0

ALLOWED_UPSTREAM_CLASSES = frozenset(
    {
        "upstream_timeout",
        "upstream_busy",
        "upstream_response_too_large",
        "malformed_upstream",
        "upstream_malformed_json",
        "upstream_unexpected_shape",
        "upstream_missing_content",
        "upstream_non_text_content",
        "upstream_empty_answer",
        "upstream_unavailable",
        "provider_auth_error",
        "provider_route_error",
        "provider_server_error",
        "upstream_execution_failed",
        "upstream_error",
    }
)
ALLOWED_PUBLIC_ERRORS = frozenset(
    {"quote_interpretation_failed", "quote_input_unrecognized"}
)
ALLOWED_MISSING_FIELDS = frozenset(
    {"recipient.company", "items[0].name", "items[0].qty", "items[0].unitPrice"}
)


@dataclass(frozen=True)
class SafeHttpResult:
    status: int
    headers: Any
    body: bytes


def _bounded_body(response: Any) -> bytes:
    body = response.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise RuntimeError("response_body_too_large")
    return body


def _request(opener: Any, request: urllib.request.Request) -> SafeHttpResult:
    try:
        response = opener.open(request, timeout=60)
        try:
            return SafeHttpResult(
                status=int(response.status),
                headers=response.headers,
                body=_bounded_body(response),
            )
        finally:
            response.close()
    except urllib.error.HTTPError as exc:
        try:
            return SafeHttpResult(
                status=int(exc.code),
                headers=exc.headers,
                body=_bounded_body(exc),
            )
        finally:
            exc.close()


def _json_request(
    opener: Any,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> SafeHttpResult:
    data = None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if payload is not None:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return _request(
        opener,
        urllib.request.Request(
            BASE_URL + path,
            data=data,
            headers=headers,
            method=method,
        ),
    )


def _decode_json(body: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(body.decode("utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def sanitize_upstream_class(value: Any) -> str:
    text = str(value or "")
    return text if text in ALLOWED_UPSTREAM_CLASSES else "ABSENT_OR_UNKNOWN"


def sanitize_public_error(value: Any) -> str:
    text = str(value or "")
    return text if text in ALLOWED_PUBLIC_ERRORS else "ABSENT_OR_UNKNOWN"


def sanitize_missing(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        text = str(item)
        out.append(text if text in ALLOWED_MISSING_FIELDS else "UNKNOWN_FIELD")
    return tuple(out)


def _header(headers: Any, name: str) -> str | None:
    try:
        return headers.get(name)
    except Exception:
        return None


def _bounded_diagnostic(value: Any) -> str:
    text = str(value or "")
    if not text:
        return "ABSENT"
    return text[:80] if re.fullmatch(r"[A-Za-z0-9_.\[\]-]{1,80}", text) else "PRESENT_REDACTED"


def _print_summary(summary: dict[str, Any]) -> None:
    order = (
        "LOGIN_HTTP",
        "AUTH_HTTP",
        "AUTHENTICATED",
        "SAVED_SKILL_HTTP",
        "SAVED_SKILL_COUNT",
        "INTERPRET_HTTP",
        "X_B66_UPSTREAM_CLASS",
        "X_B66_REJECTION_REASON",
        "X_B66_REJECTION_PATH",
        "X_B66_REJECTION_TYPE",
        "PUBLIC_ERROR",
        "CANDIDATE_PRESENT",
        "MISSING_FIELDS",
        "SAFE_RECIPIENT_MATCH",
        "SAFE_ITEM_MATCH",
        "SAFE_QTY_MATCH",
        "UNIT_PRICE_NULL",
        "INTERPRET_POSTS",
        "LIVE_PROVIDER_CALLS_EXECUTED",
        "COOKIE_OUTPUT",
        "PASSWORD_OUTPUT",
        "TOKEN_OUTPUT",
        "RAW_RESPONSE_OUTPUT",
        "PRODUCTION_DATA_MUTATION",
    )
    for key in order:
        if key in summary:
            print(f"{key}={summary[key]}")


def run_live(username: str, password: str) -> int:
    if not username or not password:
        print("B66_CGI_PARTIAL_CANARY=FAIL_CREDENTIAL_UNAVAILABLE")
        return 2

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    summary: dict[str, Any] = {
        "COOKIE_OUTPUT": 0,
        "PASSWORD_OUTPUT": 0,
        "TOKEN_OUTPUT": 0,
        "RAW_RESPONSE_OUTPUT": 0,
        "PRODUCTION_DATA_MUTATION": 0,
        "INTERPRET_POSTS": 0,
        "LIVE_PROVIDER_CALLS_EXECUTED": 0,
    }

    login = _json_request(
        opener,
        "/api/padiem/auth/password/login",
        method="POST",
        payload={"identifier": username, "password": password},
    )
    summary["LOGIN_HTTP"] = login.status
    if login.status != 200:
        _print_summary(summary)
        print("B66_CGI_PARTIAL_CANARY=FAIL_LOGIN")
        return 3

    auth = _json_request(opener, "/api/padiem/auth/status")
    auth_json = _decode_json(auth.body) or {}
    summary["AUTH_HTTP"] = auth.status
    summary["AUTHENTICATED"] = str(auth_json.get("authenticated") is True).upper()
    if auth.status != 200 or auth_json.get("authenticated") is not True:
        _print_summary(summary)
        print("B66_CGI_PARTIAL_CANARY=FAIL_AUTH")
        return 4

    skills_result = _json_request(opener, "/api/padiem/b66/saved-skills?limit=20")
    skills_json = _decode_json(skills_result.body) or {}
    skills = skills_json.get("skills")
    skills = skills if isinstance(skills, list) else []
    summary["SAVED_SKILL_HTTP"] = skills_result.status
    summary["SAVED_SKILL_COUNT"] = len(skills)
    if skills_result.status != 200 or skills_json.get("ok") is not True or len(skills) != 1:
        _print_summary(summary)
        print("B66_CGI_PARTIAL_CANARY=FAIL_SAVED_SKILL")
        return 5

    row = skills[0] if isinstance(skills[0], dict) else {}
    saved_skill_id = row.get("saved_skill_id")
    if not isinstance(saved_skill_id, str) or not re.fullmatch(
        r"b66skill_[0-9a-f]{32}",
        saved_skill_id,
    ):
        _print_summary(summary)
        print("B66_CGI_PARTIAL_CANARY=FAIL_SAVED_SKILL_ID")
        return 6

    summary["INTERPRET_POSTS"] = 1
    summary["LIVE_PROVIDER_CALLS_EXECUTED"] = 1
    interpreted = _json_request(
        opener,
        "/api/padiem/b66/quote/interpret",
        method="POST",
        payload={"saved_skill_id": saved_skill_id, "message": PARTIAL_TEXT},
    )
    summary["INTERPRET_HTTP"] = interpreted.status
    summary["X_B66_UPSTREAM_CLASS"] = sanitize_upstream_class(
        _header(interpreted.headers, "X-B66-Upstream-Class")
    )
    for header, key in (
        ("X-B66-Rejection-Reason", "X_B66_REJECTION_REASON"),
        ("X-B66-Rejection-Path", "X_B66_REJECTION_PATH"),
        ("X-B66-Rejection-Type", "X_B66_REJECTION_TYPE"),
    ):
        summary[key] = _bounded_diagnostic(_header(interpreted.headers, header))

    body = _decode_json(interpreted.body) or {}
    summary["PUBLIC_ERROR"] = sanitize_public_error(body.get("error_code"))

    candidate = body.get("candidate")
    summary["CANDIDATE_PRESENT"] = str(isinstance(candidate, dict)).upper()
    if interpreted.status == 200 and isinstance(candidate, dict):
        missing = sanitize_missing(candidate.get("missing"))
        summary["MISSING_FIELDS"] = ",".join(missing) if missing else "NONE"
        recipient = candidate.get("recipient")
        items = candidate.get("items")
        item = (
            items[0]
            if isinstance(items, list)
            and len(items) == 1
            and isinstance(items[0], dict)
            else {}
        )
        summary["SAFE_RECIPIENT_MATCH"] = str(
            isinstance(recipient, dict)
            and recipient.get("company") == "대한건설"
        ).upper()
        summary["SAFE_ITEM_MATCH"] = str(item.get("name") == "배관").upper()
        summary["SAFE_QTY_MATCH"] = str(item.get("qty") == 100).upper()
        summary["UNIT_PRICE_NULL"] = str(item.get("unitPrice") is None).upper()

    _print_summary(summary)

    accepted = (
        interpreted.status == 200
        and isinstance(candidate, dict)
        and sanitize_missing(candidate.get("missing")) == ("items[0].unitPrice",)
        and summary.get("SAFE_RECIPIENT_MATCH") == "TRUE"
        and summary.get("SAFE_ITEM_MATCH") == "TRUE"
        and summary.get("SAFE_QTY_MATCH") == "TRUE"
        and summary.get("UNIT_PRICE_NULL") == "TRUE"
    )
    print("B66_CGI_PARTIAL_CANARY=" + ("PASS" if accepted else "FAIL"))
    return 0 if accepted else 7


def self_test() -> int:
    assert MAX_INTERPRET_POSTS == 1
    assert USER_AGENT == "padiem-b66-cgi-partial-canary/1.0 (+github-actions)"
    assert RETRY == 0
    assert FALLBACK == 0
    assert sanitize_upstream_class("upstream_non_text_content") == "upstream_non_text_content"
    assert sanitize_upstream_class("secret-provider-detail") == "ABSENT_OR_UNKNOWN"
    assert sanitize_public_error("quote_interpretation_failed") == "quote_interpretation_failed"
    assert sanitize_public_error("raw-secret") == "ABSENT_OR_UNKNOWN"
    assert sanitize_missing(["items[0].unitPrice"]) == ("items[0].unitPrice",)
    assert sanitize_missing(["private.foo"]) == ("UNKNOWN_FIELD",)
    assert _bounded_diagnostic("items[0].unitPrice") == "items[0].unitPrice"
    assert _bounded_diagnostic("raw value with spaces") == "PRESENT_REDACTED"
    print("B66_CGI_PARTIAL_CANARY_SELF_TEST=PASS")
    print("DEFAULT_LIVE_EXECUTION=BLOCKED")
    print("SECRET_VALUE_OUTPUT=0")
    print("RAW_RESPONSE_OUTPUT=0")
    print("PRODUCTION_DATA_MUTATION=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorized-live-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.self_test:
        return self_test()
    if not args.authorized_live_run:
        print("B66_CGI_PARTIAL_CANARY=FAIL_AUTHORIZATION_REQUIRED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        return 1

    return run_live(
        os.getenv("B66_CGI_ALPHA_USERNAME", ""),
        os.getenv("B66_CGI_ALPHA_PASSWORD", ""),
    )


if __name__ == "__main__":
    raise SystemExit(main())
