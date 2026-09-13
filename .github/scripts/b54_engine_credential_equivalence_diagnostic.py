#!/usr/bin/env python3
"""Bounded credential-equivalence diagnostic for the Engine caller authority.

Issue #2503. The #2439 source audit proved the storage path preserves the
``B62_P01_ENGINE_CREDENTIAL`` bytes exactly (env -> JSON -> ``--data-binary``
secret PUT), while the HTTP header transport normalizes leading/trailing
whitespace at the edge and the served verifier never strips credentials. Two
candidates survive and are indistinguishable from public 401 evidence:

1. the GitHub secret carries boundary whitespace, so the stored digest and the
   presented digest differ (BOUNDARY_WHITESPACE_MATCH); or
2. the stored overlay credential is simply not the value this run resolves
   (NEITHER_MATCH).

This CLI answers exactly one question with AT MOST TWO requests to the served
Engine ``/internal/v1/idempotency/completed/replay`` route:

* R1 presents the RAW credential from the environment;
* R2 presents the SAME value with leading/trailing whitespace stripped.

The replay route authenticates every non-health request BEFORE any durable
lookup (worker.py), and a valid credential paired with a fresh nonexistent
idempotency key returns a 200 ``completed_execution_not_found`` projection.
That makes the route a read-only authentication oracle: no provider call, no
D1 write, no state change.

Output is a closed evidence vocabulary only:

    R1_HTTP_STATUS=<integer>            R1_HTTP_CLASS=<1xx..5xx|blocked>
    R1_ERROR_CODE=<public code|none|unrecognized|transport_blocked>
    R2_HTTP_STATUS=<integer>            R2_HTTP_CLASS=<1xx..5xx|blocked>
    R2_ERROR_CODE=<public code|none|unrecognized|transport_blocked>
    RAW_ACCEPTED=YES|NO
    STRIPPED_ACCEPTED=YES|NO
    DISPOSITION=RAW_MATCH|BOUNDARY_WHITESPACE_MATCH|NEITHER_MATCH|UNEXPECTED

A request counts as ACCEPTED only when it returned 200 with
``{"ok": true, "replayed": false, "reason": "completed_execution_not_found"}``.

The credential is consumed strictly as an environment variable and NEVER
leaves this process except as the ``x-padiem-engine-credential`` header value.
No plaintext, hash, fingerprint, byte length, prefix, suffix, registry
payload, response body, or derived secret material is ever printed. Exception
text is never propagated; failures are fixed strings. The random idempotency
key is generated per run and never echoed.

Exit codes: 0 for a valid finding (RAW_MATCH, BOUNDARY_WHITESPACE_MATCH,
NEITHER_MATCH), 1 for UNEXPECTED or preflight refusal, 2 for usage faults.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request

REQUEST_BUDGET_MAX = 2
ENGINE_BASE_URL = "https://engine.padiem.net"
REPLAY_PATH = "/internal/v1/idempotency/completed/replay"
CALLER_ID = "b54-kagent"
APP_ID = "b54-padiem-claw"
CALLER_ID_HEADER = "x-padiem-engine-caller"
CALLER_CREDENTIAL_HEADER = "x-padiem-engine-credential"
NOT_FOUND_REASON = "completed_execution_not_found"
FINGERPRINT = "0" * 64
KEY_PREFIX = "b54-cred-eq-diag"
# Explicit diagnostic User-Agent (repo convention: padiem-<purpose>/1.0
# (+github-actions)). The Cloudflare edge for padiem.net blocks the default
# ``Python-urllib`` UA before the Worker oracle is reached (2026-09-13
# 2-request UA differential); without this header both probe requests would
# never reach the Engine auth oracle.
DIAGNOSTIC_USER_AGENT = "padiem-credential-diagnostic/1.0 (+github-actions)"
# Deployed validator: ^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")

# Closed allowlist of public Engine error codes reachable on this route
# (worker.py auth gate + idempotency_replay_service.py validation). Any other
# code is reported as "unrecognized" so a future server message can never
# reflect request material into the log.
PUBLIC_ERROR_CODES = frozenset(
    {
        "service_authentication_failed",
        "service_identity_unavailable",
        "service_app_not_authorized",
        "invalid_request",
        "invalid_json",
        "unsupported_media_type",
        "request_too_large",
        "method_not_allowed",
        "not_found",
        "idempotency_unavailable",
    }
)

DISPOSITIONS = ("RAW_MATCH", "BOUNDARY_WHITESPACE_MATCH", "NEITHER_MATCH", "UNEXPECTED")

SAFETY_MARKERS = (
    ("REQUEST_BUDGET_MAX", "2"),
    ("REQUESTS_ISSUED", None),  # filled at runtime
    ("SECRET_VALUE_OUTPUT", "0"),
    ("SECRET_HASH_OUTPUT", "0"),
    ("SECRET_LENGTH_OUTPUT", "0"),
    ("SECRET_PREFIX_SUFFIX_OUTPUT", "0"),
    ("RAW_REGISTRY_OUTPUT", "0"),
    ("PROVIDER_CALL", "0"),
    ("D1_WRITE", "0"),
    ("DEPLOY", "0"),
    ("SECRET_MUTATION", "0"),
    ("PHASE_A", "0"),
    ("PRODUCTION_MUTATION", "0"),
)


def _http_class(status: int) -> str:
    if 100 <= status <= 599:
        return f"{status // 100}xx"
    return "blocked"


def build_request(base_url: str, credential: str, idempotency_key: str) -> urllib.request.Request:
    body = json.dumps(
        {
            "app_id": APP_ID,
            "idempotency_key": idempotency_key,
            "request_fingerprint": FINGERPRINT,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + REPLAY_PATH,
        data=body,
        method="POST",
        headers={
            "User-Agent": DIAGNOSTIC_USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
            CALLER_ID_HEADER: CALLER_ID,
            CALLER_CREDENTIAL_HEADER: credential,
        },
    )
    return request


def classify_response(status: int, raw_body: bytes) -> dict[str, str]:
    """Project one response onto the closed evidence vocabulary."""
    error_code = "none"
    accepted = False
    if 200 <= status <= 299:
        payload = _safe_json(raw_body)
        if (
            isinstance(payload, dict)
            and payload.get("ok") is True
            and payload.get("replayed") is False
            and payload.get("reason") == NOT_FOUND_REASON
        ):
            accepted = True
        else:
            error_code = "unrecognized"
    else:
        payload = _safe_json(raw_body)
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                code = error["code"]
                error_code = code if code in PUBLIC_ERROR_CODES else "unrecognized"
            else:
                error_code = "unrecognized"
        else:
            error_code = "unrecognized"
    return {
        "http_status": str(status),
        "http_class": _http_class(status),
        "error_code": error_code,
        "accepted": accepted,
    }


def _safe_json(raw_body: bytes):
    try:
        return json.loads(raw_body.decode("utf-8"))
    except Exception:
        return None


def _transport_post(request: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read()
        except Exception:
            payload = b""
        return int(exc.code), payload


def probe(
    credential: str,
    base_url: str = ENGINE_BASE_URL,
    transport=_transport_post,
) -> dict[str, str]:
    """Run the bounded two-request probe and return the closed evidence map."""
    idempotency_key = f"{KEY_PREFIX}-{secrets.token_hex(16)}"
    if not _IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
        raise AssertionError("generated idempotency key violates the deployed validator")
    evidence: dict[str, str] = {}
    requests_issued = 0
    accepted: dict[str, bool] = {}
    for label, credential_value in (("R1", credential), ("R2", credential.strip())):
        if requests_issued >= REQUEST_BUDGET_MAX:
            raise AssertionError("request budget exceeded")
        requests_issued += 1
        try:
            status, raw_body = transport(build_request(base_url, credential_value, idempotency_key))
            result = classify_response(status, raw_body)
        except Exception:
            # Local transport faults (e.g. a credential value that cannot be
            # encoded as an HTTP field value) are themselves evidence that the
            # presented form cannot byte-match the stored overlay. Fixed
            # strings only; exception text never reaches the log.
            result = {
                "http_status": "0",
                "http_class": "blocked",
                "error_code": "transport_blocked",
                "accepted": False,
            }
        accepted[label] = bool(result["accepted"])
        evidence[f"{label}_HTTP_STATUS"] = result["http_status"]
        evidence[f"{label}_HTTP_CLASS"] = result["http_class"]
        evidence[f"{label}_ERROR_CODE"] = result["error_code"]
    evidence["RAW_ACCEPTED"] = "YES" if accepted["R1"] else "NO"
    evidence["STRIPPED_ACCEPTED"] = "YES" if accepted["R2"] else "NO"
    evidence["DISPOSITION"] = disposition(accepted["R1"], accepted["R2"], evidence)
    evidence["REQUESTS_ISSUED"] = str(requests_issued)
    return evidence


def disposition(raw_ok: bool, stripped_ok: bool, evidence: dict[str, str]) -> str:
    if raw_ok:
        return "RAW_MATCH"
    if stripped_ok:
        return "BOUNDARY_WHITESPACE_MATCH"
    if (
        evidence["R1_HTTP_STATUS"] == "401"
        and evidence["R2_HTTP_STATUS"] == "401"
        and evidence["R1_ERROR_CODE"] == "service_authentication_failed"
        and evidence["R2_ERROR_CODE"] == "service_authentication_failed"
    ):
        return "NEITHER_MATCH"
    return "UNEXPECTED"


EVIDENCE_ORDER = (
    "R1_HTTP_STATUS",
    "R1_HTTP_CLASS",
    "R1_ERROR_CODE",
    "R2_HTTP_STATUS",
    "R2_HTTP_CLASS",
    "R2_ERROR_CODE",
    "RAW_ACCEPTED",
    "STRIPPED_ACCEPTED",
    "DISPOSITION",
)


def render(evidence: dict[str, str]) -> str:
    lines = [f"{name}={evidence[name]}" for name in EVIDENCE_ORDER]
    lines.extend(
        f"{name}={value if value is not None else evidence['REQUESTS_ISSUED']}"
        for name, value in SAFETY_MARKERS
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "--credential-env":
        print(
            "usage: b54_engine_credential_equivalence_diagnostic.py "
            "--credential-env <ENV_NAME>",
            file=sys.stderr,
        )
        return 2
    credential_env = args[1]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", credential_env):
        print("B54_CREDENTIAL_EQUIVALENCE=FAIL REASON=unsafe_env_name", file=sys.stderr)
        return 2
    credential = os.environ.get(credential_env, "")
    if not credential:
        # Fail closed WITHOUT consuming any of the request budget: an absent
        # secret here is a dispatch-environment fault, not a product finding.
        print(
            "B54_CREDENTIAL_EQUIVALENCE=FAIL REASON=credential_env_empty "
            "REQUESTS_ISSUED=0 PRODUCTION_MUTATION=0",
            file=sys.stderr,
        )
        return 1
    try:
        evidence = probe(credential)
    except Exception:
        print(
            "B54_CREDENTIAL_EQUIVALENCE=FAIL REASON=internal_fault PRODUCTION_MUTATION=0",
            file=sys.stderr,
        )
        return 2
    print(render(evidence))
    return 0 if evidence["DISPOSITION"] in ("RAW_MATCH", "BOUNDARY_WHITESPACE_MATCH", "NEITHER_MATCH") else 1


if __name__ == "__main__":
    raise SystemExit(main())
