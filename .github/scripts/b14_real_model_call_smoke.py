"""#5895 ④: one real model call against the B14 version that was just promoted.

The deploy gate already proves the promoted version is the single version serving
100 percent, that /health answers and that the catalog matches the owner registry
byte for byte. What it did not prove was that the promoted version can finish one
request end to end, which is the check a person used to do by hand afterwards.

The grade routing decides the model: this script sends ``b14/auto`` with one
declared product tier and names no model of its own, so it exercises exactly the
route the product serves. It carries no credential - B14 spends its own provider
keys - and it never prints provider text, response bytes or any secret.

Verdict contract (CTO 2026-10-27):
  200 plus at least one character of assistant text -> REAL_MODEL_CALL=PASS
  provider-side 429 or 503                         -> REAL_MODEL_CALL=PASS_PROVIDER_LIMIT (a pass)
  anything else: other status, malformed body, empty text, timeout -> REAL_MODEL_CALL=FAIL and exit 1

CTO 2026-11-02: a 503 ``entitlement_unavailable`` is an entitlement refusal,
not a provider limit, so it is a FAIL. ``--report`` adds one bounded
``GRADE_SMOKE tier=... status=... error_code=...`` line for the nightly issue;
the default output line is unchanged.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

SERVED_ORIGIN = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev"
COMPLETIONS_PATH = "/api/pilot/v1/chat/completions"
USER_AGENT = "b14-gate/1.0"
REQUESTED_ROUTE = "b14/auto"
PRODUCT_TIER = "free"
PRODUCT_TIERS = ("free", "plus", "pro", "max")
PROMPT = "Synthetic release check: reply with one word."
MAX_TOKENS = 48
REQUEST_TIMEOUT_SECONDS = 40
MAX_RESPONSE_BYTES = 65_536
PROVIDER_LIMIT_STATUSES = frozenset({429, 503})
# A refusal code that means "the product will not spend on this request", which
# no amount of provider recovery fixes. It must never read as a provider limit.
ENTITLEMENT_DENIAL_CODES = frozenset({"entitlement_unavailable", "entitlement_denied"})
_SAFE_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
_SAFE_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")

Transport = Callable[[str, bytes, float], tuple[int, bytes]]


def request_body(*, max_tokens: int = MAX_TOKENS,
                 product_tier: str = PRODUCT_TIER) -> bytes:
    """The one bounded completion request. No model is selected here."""
    return json.dumps(
        {
            "model": REQUESTED_ROUTE,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": max_tokens,
            "business14": {"product_tier": product_tier, "max_retries": 0},
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def urlopen_transport(user_agent: str = USER_AGENT) -> Transport:
    """The real transport, built only when a caller actually asks for it."""

    def call(url: str, body: bytes, timeout: float) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": user_agent,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read(MAX_RESPONSE_BYTES + 1)

    return call


def resolved_model(payload: Any) -> str:
    """The model the route answered with, or the declared route when unnamed.

    Only a safe identifier is returned, so the verdict line can never carry a
    fragment of a provider response.
    """
    candidates: list[Any] = []
    if isinstance(payload, dict):
        candidates.append(payload.get("model"))
        business = payload.get("business14")
        if isinstance(business, dict):
            candidates.append(business.get("model_route"))
    for candidate in candidates:
        if isinstance(candidate, str) and _SAFE_MODEL_ID.match(candidate):
            return candidate
    return REQUESTED_ROUTE


def assistant_text(payload: Any) -> str | None:
    """The first completion's text, or None when the body is not that shape."""
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    return text if isinstance(text, str) else None


def _payload(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def error_code(payload: Any) -> str:
    """The refusal code the Worker named, as a safe token, or ``-``.

    Only a short lowercase token survives, so neither provider text nor a
    malformed body can reach a log line.
    """
    if isinstance(payload, dict):
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, str) and _SAFE_ERROR_CODE.match(code):
            return code
    return "-"


def decide(status: int, raw: bytes) -> tuple[str, str]:
    """Return ``(verdict, model)``. A non-pass verdict is a gate failure."""
    payload = _payload(raw)
    if error_code(payload) in ENTITLEMENT_DENIAL_CODES:
        return "FAIL", resolved_model(payload)
    if status in PROVIDER_LIMIT_STATUSES:
        return "PASS_PROVIDER_LIMIT", resolved_model(payload)
    if status != 200:
        return "FAIL", resolved_model(payload)
    text = assistant_text(payload)
    if text is None or not text.strip():
        return "FAIL", resolved_model(payload)
    return "PASS", resolved_model(payload)


def run(*, base_url: str, transport: Transport, timeout: float = REQUEST_TIMEOUT_SECONDS,
        max_tokens: int = MAX_TOKENS, product_tier: str = PRODUCT_TIER,
        report: dict[str, Any] | None = None) -> tuple[str, str]:
    body = request_body(max_tokens=max_tokens, product_tier=product_tier)
    try:
        status, raw = transport(base_url.rstrip("/") + COMPLETIONS_PATH, body, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        # An unreachable or unanswered Worker is a failed release check, never a
        # provider limit and never a silent pass.
        if report is not None:
            report.update(status=0, error_code="transport_error")
        return "FAIL", REQUESTED_ROUTE
    if len(raw) > MAX_RESPONSE_BYTES:
        if report is not None:
            report.update(status=status, error_code="response_too_large")
        return "FAIL", REQUESTED_ROUTE
    if report is not None:
        report.update(status=status, error_code=error_code(_payload(raw)))
    return decide(status, raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=SERVED_ORIGIN)
    parser.add_argument("--tier", choices=PRODUCT_TIERS, default=PRODUCT_TIER,
                        help="declared product grade whose route is proven")
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--timeout", type=float, default=REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--report", action="store_true",
                        help="also print one bounded grade/status/error_code line")
    args = parser.parse_args(argv)
    detail: dict[str, Any] = {"status": 0, "error_code": "origin_not_https"}
    if not args.base_url.startswith("https://"):
        print("REAL_MODEL_CALL=FAIL model=" + REQUESTED_ROUTE)
        if args.report:
            print(f"GRADE_SMOKE tier={args.tier} status=0 "
                  "error_code=origin_not_https verdict=FAIL")
        print("B14_REAL_MODEL_CALL_ORIGIN_NOT_HTTPS", file=sys.stderr)
        return 1
    verdict, model = run(base_url=args.base_url, transport=urlopen_transport(),
                         timeout=args.timeout, max_tokens=args.max_tokens,
                         product_tier=args.tier, report=detail)
    print(f"REAL_MODEL_CALL={verdict} model={model}")
    if args.report:
        print(f"GRADE_SMOKE tier={args.tier} status={detail['status']} "
              f"error_code={detail['error_code']} verdict={verdict}")
    if verdict == "FAIL":
        print("B14_REAL_MODEL_CALL_FAILED=1", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
