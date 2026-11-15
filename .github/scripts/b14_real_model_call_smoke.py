"""#5895 ④ / CTO 2026-11-02: one real model call through a declared grade route.

Two invocations share the verdict table but not the wire.

* The deploy gate runs this script with no arguments. That call names the
  Free grade's exact declared model, carries no credential of its own, and
  prints one ``REAL_MODEL_CALL=`` line.
* The nightly grade smoke runs it with ``--tier``. That call reads the tier's
  executable model id from the shared declaration contract
  (``packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py``)
  and signs the request with the existing B14 service proof,
  ``HMAC-SHA256(secret, "<unix time>.<body>")``. The secret is referenced by
  its existing deployment binding name (``PADIEM_B14_SERVICE_PROOF_SECRET``);
  when it is absent no proof header is sent, B14 refuses the dispatch, and the
  check fails closed.
  #7450: a runner that holds the proof but not the private registry file
  (the model values live only on the serving host, #7238) reads the tier's
  route from the serving B14 itself — ``GET /api/pilot/admin/models`` behind
  the same proof, the empty GET body bound like any other. The declaration
  contract stays the first source; the serving authority is the fallback, and
  a refused or unusable answer fails closed, never a guessed model.

The script never prints provider text, response bytes, the secret, or any
fragment of them. #7450 review: it never prints a model value either — the
repository and the CI logs are public and #7238 moved the model values to the
private registry. Every line names the tier and carries ``model_match``
(``yes`` when the answer came back on the requested route, ``no`` when the
server named a different model, ``unknown`` when nothing answered); if a
model identifier ever must appear in output, only a value-free short hash
(sha256 prefix) may stand in for it.

Verdict contract (CTO 2026-10-27):
  200 plus at least one character of assistant text -> REAL_MODEL_CALL=PASS
  provider-side 429 or 503                         -> REAL_MODEL_CALL=PASS_PROVIDER_LIMIT (a pass)
  anything else: other status, malformed body, empty text, timeout -> REAL_MODEL_CALL=FAIL and exit 1

CTO 2026-11-02: a 503 ``entitlement_unavailable`` is an entitlement refusal,
not a provider limit, so it is a FAIL. ``--report`` adds one bounded
``GRADE_SMOKE tier=... status=... error_code=... verdict=... model_match=...``
line for the nightly issue; the default output line is unchanged.
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
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

SERVED_ORIGIN = "https://b14.padiem.net"
COMPLETIONS_PATH = "/api/pilot/v1/chat/completions"
ADMIN_MODELS_PATH = "/api/pilot/admin/models"
TIER_ROUTES_FIELD = "tier_routes"
USER_AGENT = "b14-gate/1.0"
# Both invocations name a grade's exact declared model; neither keeps a
# second model list of its own.
PRODUCT_TIER = "free"
PRODUCT_TIERS = ("free", "plus", "pro", "max")
# CLI token -> the label the shared product-tier declaration defines.
TIER_LABELS = {
    "free": "Padiem Free",
    "plus": "Padiem Plus",
    "pro": "Padiem Pro",
    "max": "Padiem Max",
}
ROUTE_CONTRACT_DIR = (
    Path(__file__).resolve().parents[2] / "packages" / "padiem-control-plane"
)
PROMPT = "안녕하세요. 한 문장으로 짧게 인사해 주세요."
# #7071: keep a bounded budget, but large enough that reasoning-capable models
# can return visible text. 32 was below real Chat usage and made the probe
# sensitive to reasoning consuming the whole output budget.
MAX_TOKENS = 256
REQUEST_TIMEOUT_SECONDS = 40
MAX_RESPONSE_BYTES = 65_536
PROVIDER_LIMIT_STATUSES = frozenset({429, 503})
# A refusal code that means "the product will not spend on this request", which
# no amount of provider recovery fixes. It must never read as a provider limit.
ENTITLEMENT_DENIAL_CODES = frozenset({"entitlement_unavailable", "entitlement_denied"})
# The same server-to-server proof the Chat and Engine callers already sign.
PROOF_HEADER = "x-padiem-b14-proof"
PROOF_TIME_HEADER = "x-padiem-b14-time"
PROOF_SECRET_ENV = "PADIEM_B14_SERVICE_PROOF_SECRET"
MIN_PROOF_SECRET_LENGTH = 32
_SAFE_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
_SAFE_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")

Transport = Callable[[str, bytes, dict[str, str], float], tuple[int, bytes]]
TransportGet = Callable[[str, dict[str, str], float], tuple[int, bytes]]


def declared_tier_model(tier: str) -> str:
    """The executable model id the shared declaration assigns to this tier.

    The declaration contract is the only source; this script names no model of
    its own. An unknown tier, a tier without an executable route, or a missing
    contract package yields ``""`` so the caller fails closed.
    """
    directory = str(ROUTE_CONTRACT_DIR)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    try:
        from padiem_control_plane.product_tier_routes import ProductTierLabel
        from padiem_control_plane.product_tier_routes_private import (
            effective_active_route_for,
        )
    except ImportError:
        return ""
    label = TIER_LABELS.get(tier)
    if label is None:
        return ""
    try:
        route = effective_active_route_for(ProductTierLabel(label))
    except ValueError:
        return ""
    model = route.model_id if route is not None else None
    return model if isinstance(model, str) and _SAFE_MODEL_ID.match(model) else ""


def proof_headers(
    secret: str | None, body: bytes, *, now_seconds: int | None = None
) -> dict[str, str]:
    """The existing B14 service-proof headers, or none when unconfigured.

    B14 verifies ``HMAC-SHA256(secret, "<unix timestamp>.<raw body>")``. A
    missing or short secret yields no headers, so the dispatch is refused
    instead of silently passing as an unproven caller. The secret is only
    hashed; it is never returned or printed.
    """
    if not isinstance(secret, str) or len(secret) < MIN_PROOF_SECRET_LENGTH:
        return {}
    timestamp = str(int(time.time()) if now_seconds is None else int(now_seconds))
    message = timestamp.encode("ascii") + b"." + bytes(body)
    proof = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {PROOF_HEADER: proof, PROOF_TIME_HEADER: timestamp}


def request_body(*, model: str, max_tokens: int = MAX_TOKENS,
                 product_tier: str = PRODUCT_TIER) -> bytes:
    """The one bounded completion request."""
    return json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": max_tokens,
            "business14": {"product_tier": product_tier, "max_retries": 0},
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def urlopen_transport(user_agent: str = USER_AGENT) -> Transport:
    """The real transport, built only when a caller actually asks for it."""

    def call(url: str, body: bytes, headers: dict[str, str],
             timeout: float) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": user_agent,
                **headers,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read(MAX_RESPONSE_BYTES + 1)

    return call


def urlopen_get_transport(user_agent: str = USER_AGENT) -> TransportGet:
    """The real GET transport, built only when a caller actually asks for it."""

    def call(url: str, headers: dict[str, str],
             timeout: float) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": user_agent,
                **headers,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read(MAX_RESPONSE_BYTES + 1)

    return call


def resolved_model(payload: Any, fallback: str = "") -> str:
    """The route the answer came on, or the upstream identity, or the request.

    The server contract fills the top-level ``model`` with the upstream
    identity the provider actually answered with, while
    ``business14.model_route`` names the product route the answer came on
    (2026-11-15 rel203 finding: comparing the upstream name against the
    requested route id answered ``no`` on every grade of a fully green
    smoke). The route identity is compared first, so ``model_match`` proves
    route conformance; the upstream name stays a second candidate so a
    response that carries only it is still comparable. Only safe identifiers
    are returned, so the verdict line can never carry a fragment of a
    provider response.
    """
    candidates: list[Any] = []
    if isinstance(payload, dict):
        business = payload.get("business14")
        if isinstance(business, dict):
            candidates.append(business.get("model_route"))
        candidates.append(payload.get("model"))
    for candidate in candidates:
        if isinstance(candidate, str) and _SAFE_MODEL_ID.match(candidate):
            return candidate
    return fallback


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


def decide(status: int, raw: bytes,
           fallback: str = "") -> tuple[str, str]:
    """Return ``(verdict, model)``. A non-pass verdict is a gate failure."""
    payload = _payload(raw)
    if error_code(payload) in ENTITLEMENT_DENIAL_CODES:
        return "FAIL", resolved_model(payload, fallback)
    if status in PROVIDER_LIMIT_STATUSES:
        return "PASS_PROVIDER_LIMIT", resolved_model(payload, fallback)
    if status != 200:
        return "FAIL", resolved_model(payload, fallback)
    text = assistant_text(payload)
    if text is None or not text.strip():
        return "FAIL", resolved_model(payload, fallback)
    return "PASS", resolved_model(payload, fallback)


def route_from_admin_models(
    *, base_url: str, transport_get: TransportGet,
    service_proof_secret: str, tier: str, timeout: float,
    report: dict[str, Any] | None = None,
) -> str:
    """The tier's declared model id from the serving B14 itself, or ``""``.

    #7450: a runner holds the service proof but not the private registry file,
    so the tier route is read from the same authority that serves the grade —
    ``GET /api/pilot/admin/models`` behind the existing proof. A GET has no
    body, so the proof binds to the empty body exactly as the endpoint
    verifies it. Any refusal, transport failure or unusable shape answers
    ``""`` with a bounded reason code: the check fails closed instead of
    guessing a model, and no response text reaches a log line.
    """
    headers = proof_headers(service_proof_secret, b"")
    if not headers:
        if report is not None:
            report["code"] = "route_proof_unconfigured"
        return ""
    url = base_url.rstrip("/") + ADMIN_MODELS_PATH
    try:
        status, raw = transport_get(url, headers, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        if report is not None:
            report["code"] = "route_transport_error"
        return ""
    payload = _payload(raw)
    if status != 200 or not isinstance(payload, dict):
        if report is not None:
            named = error_code(payload)
            report["code"] = named if named != "-" else "route_read_failed"
        return ""
    routes = payload.get(TIER_ROUTES_FIELD)
    if not isinstance(routes, dict):
        if report is not None:
            report["code"] = "route_read_failed"
        return ""
    model = routes.get(tier)
    if isinstance(model, str) and _SAFE_MODEL_ID.match(model):
        return model
    if report is not None:
        report["code"] = "tier_route_unavailable"
    return ""


def run(*, base_url: str, transport: Transport, tier: str | None = None,
        service_proof_secret: str = "", timeout: float = REQUEST_TIMEOUT_SECONDS,
        max_tokens: int = MAX_TOKENS, product_tier: str | None = None,
        report: dict[str, Any] | None = None,
        transport_get: TransportGet | None = None) -> tuple[str, str]:
    """Make one call. ``tier`` selects the exact declared grade route."""
    effective_tier = tier or PRODUCT_TIER
    model = declared_tier_model(effective_tier)
    if not model and tier is not None:
        # #7450: the nightly runner holds no private registry, so the route
        # comes from the serving authority itself. The deploy gate (no tier)
        # keeps its exact former source and stays unsigned.
        route_detail: dict[str, Any] = {}
        model = route_from_admin_models(
            base_url=base_url,
            transport_get=transport_get if transport_get is not None
            else urlopen_get_transport(),
            service_proof_secret=service_proof_secret,
            tier=effective_tier, timeout=timeout, report=route_detail,
        )
        if not model:
            if report is not None:
                report.update(status=0, error_code=route_detail.get(
                    "code", "tier_route_unavailable"))
            return "FAIL", effective_tier
    if not model:
        if report is not None:
            report.update(status=0, error_code="tier_route_unavailable")
        return "FAIL", effective_tier
    body = request_body(model=model, max_tokens=max_tokens,
                        product_tier=product_tier or effective_tier)
    # Only the nightly numbered-grade invocation signs; the deploy gate's
    # default call still carries no credential of its own.
    headers: dict[str, str] = (
        proof_headers(service_proof_secret, body) if tier is not None else {}
    )
    try:
        status, raw = transport(
            base_url.rstrip("/") + COMPLETIONS_PATH, body, headers, timeout
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        # An unreachable or unanswered Worker is a failed release check, never a
        # provider limit and never a silent pass.
        if report is not None:
            report.update(status=0, error_code="transport_error")
        return "FAIL", model
    if len(raw) > MAX_RESPONSE_BYTES:
        if report is not None:
            report.update(status=status, error_code="response_too_large",
                          model_match="unknown")
        return "FAIL", model
    payload = _payload(raw)
    if report is not None:
        report.update(status=status, error_code=error_code(payload))
        # #7450 review: the answer's own model id never reaches a log line. Whether
        # the server named the requested route is recorded value-free instead; a
        # response that names no model cannot be compared and answers unknown.
        resolved = resolved_model(payload, "")
        report["model_match"] = (
            "unknown" if not resolved else ("yes" if resolved == model else "no")
        )
    return decide(status, raw, model)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=SERVED_ORIGIN)
    parser.add_argument("--tier", choices=PRODUCT_TIERS, default=None,
                        help="declared product grade whose exact model route is proven")
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--timeout", type=float, default=REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--report", action="store_true",
                        help="also print one bounded grade/status/error_code line")
    args = parser.parse_args(argv)
    tier = args.tier
    effective_tier = tier or PRODUCT_TIER
    detail: dict[str, Any] = {"status": 0, "error_code": "origin_not_https"}
    # Loopback http://127.0.0.1[:port] is allowed for the COM2 self-hosted
    # runner, which shares a host with the COM2 B14 service. Everything else
    # must still be HTTPS.
    parsed = urllib.parse.urlsplit(args.base_url)
    is_loopback = (
        parsed.scheme == "http"
        and parsed.hostname in ("127.0.0.1", "localhost", "::1")
    )
    if not args.base_url.startswith("https://") and not is_loopback:
        print(f"REAL_MODEL_CALL=FAIL tier={effective_tier} model_match=unknown")
        if args.report:
            print(f"GRADE_SMOKE tier={effective_tier} status=0 "
                  "error_code=origin_not_https verdict=FAIL model_match=unknown")
        print("B14_REAL_MODEL_CALL_ORIGIN_NOT_HTTPS", file=sys.stderr)
        return 1
    verdict, model = run(
        base_url=args.base_url,
        transport=urlopen_transport(),
        tier=tier,
        service_proof_secret=os.environ.get(PROOF_SECRET_ENV, ""),
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        report=detail,
    )
    match = detail.get("model_match", "unknown")
    print(f"REAL_MODEL_CALL={verdict} tier={effective_tier} model_match={match}")
    if args.report:
        print(f"GRADE_SMOKE tier={effective_tier} status={detail['status']} "
              f"error_code={detail['error_code']} verdict={verdict} "
              f"model_match={match}")
    if verdict == "FAIL":
        print("B14_REAL_MODEL_CALL_FAILED=1", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
