"""Post-deploy / nightly grade smoke: one real model call per declared grade.

CTO 2026-11-02 (컴1로컬1): the retired ``b14/auto`` id answers 422
``auto_routing_deferred``, so the grade smoke must stop naming it. This script
reads the executable route for one declared product tier from the shared
product-tier declaration (``packages/padiem-control-plane``) and sends that
exact model id to the B14 Worker, once, with a short greeting prompt and a
small ``max_tokens``.

Authentication is the existing B14 service proof (HMAC-SHA256 over
``<unix timestamp>.<raw body>``, headers ``x-padiem-b14-time`` /
``x-padiem-b14-proof``). The secret value comes from the
``PADIEM_B14_SERVICE_PROOF_SECRET`` environment entry — the same binding name
the Workers already use; this script references the name only, never prints a
value, and fails closed when the runner has none. No new credential kind is
introduced here.

Verdict contract (CTO 2026-10-27, unchanged):
  200 plus at least one character of assistant text -> REAL_MODEL_CALL=PASS
  provider-side 429 or 503                         -> REAL_MODEL_CALL=PASS_PROVIDER_LIMIT (a pass)
  anything else: other status, malformed body, empty text, timeout, missing
  proof secret                                     -> REAL_MODEL_CALL=FAIL and exit 1

A 503 ``entitlement_unavailable`` stays an entitlement refusal, not a provider
limit. ``--report`` adds one bounded ``GRADE_SMOKE tier=... status=...
error_code=... verdict=...`` line for the nightly issue; the default output
line is unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

SERVED_ORIGIN = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev"
COMPLETIONS_PATH = "/api/pilot/v1/chat/completions"
USER_AGENT = "b14-gate/1.0"
PRODUCT_TIER = "free"
PRODUCT_TIERS = ("free", "plus", "pro", "max")
PROMPT = "Synthetic release check: reply with one greeting word."
MAX_TOKENS = 16
REQUEST_TIMEOUT_SECONDS = 40
MAX_RESPONSE_BYTES = 65_536
PROVIDER_LIMIT_STATUSES = frozenset({429, 503})
ENTITLEMENT_DENIAL_CODES = frozenset({"entitlement_unavailable", "entitlement_denied"})
PROOF_SECRET_ENV = "PADIEM_B14_SERVICE_PROOF_SECRET"
PROOF_TIME_HEADER = "x-padiem-b14-time"
PROOF_HEADER = "x-padiem-b14-proof"
REPO_ROOT = Path(__file__).resolve().parents[2]
_SAFE_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
_SAFE_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")

Transport = Callable[[str, bytes, float], tuple[int, bytes]]


def declared_tier_model(tier: str) -> str:
    """The executable model id the shared declaration names for one tier.

    Read from the canonical product-tier declaration at run time, so a future
    owner-approved route change flows into this smoke without editing it.
    """
    control_plane = str(REPO_ROOT / "packages" / "padiem-control-plane")
    if control_plane not in sys.path:
        sys.path.insert(0, control_plane)
    from padiem_control_plane.product_tier_routes import (  # noqa: E402
        ProductTierLabel,
        active_route_for,
    )

    labels = {
        "free": ProductTierLabel.FREE,
        "plus": ProductTierLabel.PLUS,
        "pro": ProductTierLabel.PRO,
        "max": ProductTierLabel.MAX,
    }
    route = active_route_for(labels[tier])
    if route is None or not isinstance(route.model_id, str):
        raise SystemExit(f"declared_tier_model: no executable route for tier {tier}")
    return route.model_id


def proof_secret() -> str:
    """The proof secret value from the runner environment, or ``""``.

    The name is the existing binding name; the value never leaves this
    process except inside the HMAC computation.
    """
    raw = os.environ.get(PROOF_SECRET_ENV, "")
    return raw if isinstance(raw, str) else ""


def proof_headers(raw_body: bytes, *, secret: str, now_seconds: int | None = None) -> dict[str, str]:
    """The existing B14 service proof headers for one exact request body."""
    stamp = str(int(time.time()) if now_seconds is None else now_seconds)
    message = stamp.encode("ascii") + b"." + bytes(raw_body)
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {PROOF_TIME_HEADER: stamp, PROOF_HEADER: digest}


def request_body(*, max_tokens: int = MAX_TOKENS,
                 product_tier: str = PRODUCT_TIER,
                 model_id: str | None = None) -> bytes:
    """The one bounded completion request naming the declared tier model."""
    return json.dumps(
        {
            "model": model_id or declared_tier_model(product_tier),
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
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        }
        secret = proof_secret()
        if secret:
            headers.update(proof_headers(body, secret=secret))
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read(MAX_RESPONSE_BYTES + 1)

    return call


def resolved_model(payload: Any, requested_model: str) -> str:
    """The model the route answered with, or the requested id when unnamed.

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
    return requested_model


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
    """The refusal code the Worker named, as a safe token, or ``-``."""
    if isinstance(payload, dict):
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, str) and _SAFE_ERROR_CODE.match(code):
            return code
    return "-"


def decide(status: int, raw: bytes, requested_model: str) -> tuple[str, str]:
    """Return ``(verdict, model)``. A non-pass verdict is a gate failure."""
    payload = _payload(raw)
    if error_code(payload) in ENTITLEMENT_DENIAL_CODES:
        return "FAIL", resolved_model(payload, requested_model)
    if status in PROVIDER_LIMIT_STATUSES:
        return "PASS_PROVIDER_LIMIT", resolved_model(payload, requested_model)
    if status != 200:
        return "FAIL", resolved_model(payload, requested_model)
    text = assistant_text(payload)
    if text is None or not text.strip():
        return "FAIL", resolved_model(payload, requested_model)
    return "PASS", resolved_model(payload, requested_model)


def run(*, base_url: str, transport: Transport, timeout: float = REQUEST_TIMEOUT_SECONDS,
        max_tokens: int = MAX_TOKENS, product_tier: str = PRODUCT_TIER,
        model_id: str | None = None,
        report: dict[str, Any] | None = None) -> tuple[str, str]:
    requested = model_id or declared_tier_model(product_tier)
    body = request_body(max_tokens=max_tokens, product_tier=product_tier,
                        model_id=requested)
    if not proof_secret():
        # Fail closed before any request: an unproven caller would only get a
        # 401, and a missing runner secret must read as a gate failure.
        if report is not None:
            report.update(status=0, error_code="b14_proof_unconfigured")
        return "FAIL", requested
    try:
        status, raw = transport(base_url.rstrip("/") + COMPLETIONS_PATH, body, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        # An unreachable or unanswered Worker is a failed release check, never a
        # provider limit and never a silent pass.
        if report is not None:
            report.update(status=0, error_code="transport_error")
        return "FAIL", requested
    if len(raw) > MAX_RESPONSE_BYTES:
        if report is not None:
            report.update(status=status, error_code="response_too_large")
        return "FAIL", requested
    if report is not None:
        report.update(status=status, error_code=error_code(_payload(raw)))
    return decide(status, raw, requested)


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
        print("REAL_MODEL_CALL=FAIL model=-")
        if args.report:
            print(f"GRADE_SMOKE tier={args.tier} status=0 "
                  "error_code=origin_not_https verdict=FAIL")
        print("B14_REAL_MODEL_CALL_ORIGIN_NOT_HTTPS", file=sys.stderr)
        return 1
    try:
        requested = declared_tier_model(args.tier)
    except SystemExit as exc:
        print("REAL_MODEL_CALL=FAIL model=-")
        if args.report:
            print(f"GRADE_SMOKE tier={args.tier} status=0 "
                  f"error_code=declaration_error verdict=FAIL")
        print(f"B14_DECLARED_MODEL_UNRESOLVED {exc}", file=sys.stderr)
        return 1
    verdict, model = run(base_url=args.base_url, transport=urlopen_transport(),
                         timeout=args.timeout, max_tokens=args.max_tokens,
                         product_tier=args.tier, model_id=requested, report=detail)
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
