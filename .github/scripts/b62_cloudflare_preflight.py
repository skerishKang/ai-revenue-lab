#!/usr/bin/env python3
"""Read-only Cloudflare/B14 preflight for Padiem Chat deployment.

Prints and records only safe state. It never prints token values or full
Cloudflare response bodies and it makes no provider/model request.

B14 health-check semantics (#3109)
----------------------------------
``read_b14_health()`` used to wrap the whole B14 request in a bare
``except Exception: pass``, so a DNS failure, a timeout, a malformed body or an
arbitrary programming error all collapsed into the same indistinguishable
projection as a legitimately unavailable service. That made a real check
failure indistinguishable from an expected degraded state, so a broken health
probe could never be told apart from a healthy one.

The B14 result is now an explicit three-way classification, and no branch is
reachable without one:

``b14_health``
    ``ok``                   the endpoint answered HTTP 200 with a parseable
                             object and reported its own status;
    ``unavailable_expected`` the service answered and is intentionally not
                             ready (its documented ``not_configured`` state), or
                             it returned a definite non-200 HTTP status;
    ``check_error``          the check itself could not be completed — network
                             error, timeout, malformed/unparseable response, or
                             an unexpected exception.

``b14_reason`` is a stable code drawn from a closed set (``B14_REASON_CODES``).
Neither field ever carries exception text, a response body, a header, a token
or any other secret: an unexpected exception is reported by *category only*,
never by ``str(exc)``.

``malformed_response`` covers every unparseable-body case, not just an
already-parsed non-object payload. ``get_json()`` runs
``json.loads(raw.decode("utf-8"))``, so a truncated or non-JSON HTTP-200 body
raises :class:`json.JSONDecodeError` and an invalid-UTF-8 body raises
:class:`UnicodeDecodeError`. Both are caught explicitly and reported as
``malformed_response``; neither may fall through to ``unexpected_error``, which
is reserved for genuinely unanticipated conditions. This matters because the two
parse exceptions are ``ValueError`` subclasses, so the ordering against
``except Exception`` is load-bearing rather than cosmetic.

Cloudflare gate semantics — decision and rationale
---------------------------------------------------
``FAIL_OPEN_OR_DEGRADE_DECISION = DEGRADE_RECORDED_NOT_GATING`` (#3109)

The B14 health result is **observability, not a deployment gate**, and this
patch deliberately does not change that:

* ``main()`` returns 0/1 from the *Cloudflare* checks only — token verify,
  Workers script read, and subdomain lookup. B14 health never contributed to
  the exit code before this patch and does not now.
* ``deploy-mock`` in ``b62-cloudflare-worker-deploy.yml`` is gated on
  ``needs.preflight.outputs.worker_state == 'absent'``, a Cloudflare fact.
* B14 readiness is already reported truthfully by the B14 service itself, and
  its own health-truth regressions show a legitimately unready service answers
  HTTP 200 with ``status="not_configured"`` rather than failing the caller.

Turning a B14 health failure into a hard deployment blocker would therefore
change deployment behaviour with no evidence that the current behaviour is
wrong, and would make an unrelated deploy fail whenever an optional downstream
readiness probe is unavailable. The bounded, auditable fix is to make the
failure *explicit and categorised* while preserving the exit code, which is
what this module does. Any future change to that decision belongs in a separate
issue that owns the deployment contract.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CF_API = "https://api.cloudflare.com/client/v4"
B14_HEALTH = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev/api/pilot/health"
WORKER_NAME = "padiem-chat"
USER_AGENT = "b62-preflight/1.0"

# --- B14 health classification (#3109) -------------------------------------

B14_HEALTH_OK = "ok"
B14_HEALTH_UNAVAILABLE_EXPECTED = "unavailable_expected"
B14_HEALTH_CHECK_ERROR = "check_error"

B14_HEALTH_STATES = frozenset(
    {B14_HEALTH_OK, B14_HEALTH_UNAVAILABLE_EXPECTED, B14_HEALTH_CHECK_ERROR}
)

B14_REASON_OK = "health_ok"
B14_REASON_SERVICE_UNAVAILABLE = "service_unavailable"
B14_REASON_HTTP_STATUS = "http_status"
B14_REASON_NETWORK_ERROR = "network_error"
B14_REASON_TIMEOUT = "timeout"
B14_REASON_MALFORMED_RESPONSE = "malformed_response"
B14_REASON_UNEXPECTED_ERROR = "unexpected_error"

#: Closed set of B14 reason codes. A code outside this set is a contract bug,
#: and because only these literals are ever emitted, no exception text, URL,
#: header or response body can reach an output.
B14_REASON_CODES = frozenset(
    {
        B14_REASON_OK,
        B14_REASON_SERVICE_UNAVAILABLE,
        B14_REASON_HTTP_STATUS,
        B14_REASON_NETWORK_ERROR,
        B14_REASON_TIMEOUT,
        B14_REASON_MALFORMED_RESPONSE,
        B14_REASON_UNEXPECTED_ERROR,
    }
)

#: The preflight's published output keys, in emission order.
B14_STATE_KEYS = (
    "b14_http",
    "b14_health",
    "b14_reason",
    "b14_status",
    "b14_provider_mode",
    "b14_has_key",
    "b14_catalog_models",
)

UNKNOWN = "unknown"

#: Values echoed from a remote payload are constrained to a short opaque token
#: before they are emitted, so a hostile or accidentally secret-bearing value
#: cannot ride along in a "status" field.
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def safe_remote_token(value: Any, fallback: str = UNKNOWN) -> str:
    """Reduce a remote value to a short opaque token, or the fallback.

    This is the single choke point for every string that originates outside the
    process. Anything that is not a short ``[A-Za-z0-9_.:-]`` token is replaced
    rather than echoed, which keeps spaces, ``=``, ``/``, newlines and any
    secret-shaped value out of the outputs.
    """

    if not isinstance(value, str):
        return fallback
    candidate = value.strip()
    if not _SAFE_TOKEN_RE.fullmatch(candidate):
        return fallback
    return candidate


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"required GitHub secret/env is missing: {name}")
    return value


def cf_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def get_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    request = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(262_144)
            return response.status, json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read(262_144)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            data = {}
        return exc.code, data
    except URLError as exc:
        raise RuntimeError(f"network error while requesting {url}: {exc.reason}") from exc


def get_status_without_body(url: str, headers: dict[str, str]) -> int:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except URLError as exc:
        raise RuntimeError(f"network error while requesting Workers API: {exc.reason}") from exc


def write_output(name: str, value: str) -> None:
    target = os.getenv("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def append_summary(lines: list[str]) -> None:
    target = os.getenv("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def b14_state(
    *,
    http: str,
    health: str,
    reason: str,
    status: str = UNKNOWN,
    provider_mode: str = UNKNOWN,
    has_key: str = UNKNOWN,
    catalog_models: str = UNKNOWN,
) -> dict[str, str]:
    """Build one B14 projection, rejecting any value outside the contract.

    Every state that leaves ``read_b14_health`` is built here, so there is no
    path that can return an unclassified default. Out-of-contract health states
    and reason codes collapse to the fail-closed check error rather than being
    emitted, which keeps the output space closed even if a caller is wrong.
    """

    if health not in B14_HEALTH_STATES or reason not in B14_REASON_CODES:
        return {
            "b14_http": http,
            "b14_health": B14_HEALTH_CHECK_ERROR,
            "b14_reason": B14_REASON_UNEXPECTED_ERROR,
            "b14_status": UNKNOWN,
            "b14_provider_mode": UNKNOWN,
            "b14_has_key": UNKNOWN,
            "b14_catalog_models": UNKNOWN,
        }
    return {
        "b14_http": http,
        "b14_health": health,
        "b14_reason": reason,
        "b14_status": status,
        "b14_provider_mode": provider_mode,
        "b14_has_key": has_key,
        "b14_catalog_models": catalog_models,
    }


def read_b14_health() -> dict[str, str]:
    """Read B14 health and classify the outcome explicitly (#3109).

    The three outcomes are deliberately distinct:

    * a reachable service that reports itself unready is
      ``unavailable_expected`` — a degraded state, not a broken probe;
    * a completed HTTP exchange that is not 200 is ``unavailable_expected``,
      because the service did answer and the HTTP status is the safe, useful
      fact;
    * anything that prevented the check from completing at all — DNS/connection
      failure, timeout, unparseable body, or an unexpected exception — is
      ``check_error``.

    Exceptions are classified by type and reported as a stable reason code.
    ``str(exc)`` is never used, so a message carrying a token, header or
    response fragment cannot reach an output, a step summary or a log.
    """

    try:
        status, payload = get_json(
            B14_HEALTH,
            {"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
    except TimeoutError:
        return b14_state(http="0", health=B14_HEALTH_CHECK_ERROR, reason=B14_REASON_TIMEOUT)
    except URLError:
        return b14_state(http="0", health=B14_HEALTH_CHECK_ERROR, reason=B14_REASON_NETWORK_ERROR)
    except RuntimeError:
        # get_json() reports a transport failure as RuntimeError; it is still a
        # network class failure, never a silent default.
        return b14_state(http="0", health=B14_HEALTH_CHECK_ERROR, reason=B14_REASON_NETWORK_ERROR)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # A body that arrived but could not be parsed. get_json() does
        # `json.loads(raw.decode("utf-8"))`, so an HTTP 200 carrying invalid
        # JSON raises JSONDecodeError and invalid UTF-8 raises
        # UnicodeDecodeError. Both are a malformed response, not an unexpected
        # programming error, and the contract says so explicitly.
        #
        # This must be caught before `except Exception`, otherwise a genuinely
        # unparseable body would be reported as `unexpected_error` and the
        # documented `malformed_response` reason would be reachable only for an
        # already-parsed non-dict payload.
        #
        # Both are ValueError subclasses, so ordering is load-bearing. Neither
        # the raw body nor the exception text is used: json's message can quote
        # the offending document, and the decode error can quote the offending
        # bytes.
        return b14_state(
            http="0", health=B14_HEALTH_CHECK_ERROR, reason=B14_REASON_MALFORMED_RESPONSE
        )
    except Exception:
        # Deliberately not bare `pass`. An unexpected exception is still an
        # explicit, categorised outcome, and its text is discarded.
        return b14_state(
            http="0", health=B14_HEALTH_CHECK_ERROR, reason=B14_REASON_UNEXPECTED_ERROR
        )

    http = str(status)
    if status != 200:
        # The service answered. The HTTP status is the safe fact; no body is
        # read back out of the payload.
        return b14_state(
            http=http,
            health=B14_HEALTH_UNAVAILABLE_EXPECTED,
            reason=B14_REASON_HTTP_STATUS,
        )

    if not isinstance(payload, dict):
        return b14_state(
            http=http, health=B14_HEALTH_CHECK_ERROR, reason=B14_REASON_MALFORMED_RESPONSE
        )

    reported = safe_remote_token(payload.get("status"), UNKNOWN)
    info = payload.get("business14")
    if not isinstance(info, dict):
        info = {}
    provider_mode = safe_remote_token(info.get("provider_mode"), UNKNOWN)
    catalog_models = safe_remote_token(info.get("catalog_models"), UNKNOWN)
    key_value = info.get("has_key")
    has_key = ("true" if key_value else "false") if isinstance(key_value, bool) else UNKNOWN

    # The B14 service documents an intentionally unready state: it answers 200
    # with status "not_configured". That is a degraded service, not a failed
    # check, and collapsing the two is exactly what #3109 forbids.
    if reported != "ok":
        return b14_state(
            http=http,
            health=B14_HEALTH_UNAVAILABLE_EXPECTED,
            reason=B14_REASON_SERVICE_UNAVAILABLE,
            status=reported,
            provider_mode=provider_mode,
            has_key=has_key,
            catalog_models=catalog_models,
        )

    return b14_state(
        http=http,
        health=B14_HEALTH_OK,
        reason=B14_REASON_OK,
        status=reported,
        provider_mode=provider_mode,
        has_key=has_key,
        catalog_models=catalog_models,
    )


def emit_b14(state: dict[str, str]) -> None:
    for key in B14_STATE_KEYS:
        write_output(key, state[key])
    print(f"B14_HEALTH_HTTP={state['b14_http']}")
    print(f"B14_HEALTH_STATE={state['b14_health']}")
    print(f"B14_HEALTH_REASON={state['b14_reason']}")
    print(f"B14_STATUS={state['b14_status']}")
    print(f"B14_PROVIDER_MODE={state['b14_provider_mode']}")
    print(f"B14_HAS_KEY={state['b14_has_key']}")
    print(f"B14_CATALOG_MODELS={state['b14_catalog_models']}")
    print("REAL_PROVIDER_CALLS=0")


def b14_summary_rows(state: dict[str, str]) -> list[str]:
    """The bounded B14 rows shared by both step-summary tables."""

    return [
        f"| B14 health state | `{state['b14_health']}` |",
        f"| B14 health reason | `{state['b14_reason']}` |",
        f"| B14 health HTTP | `{state['b14_http']}` |",
        f"| B14 status | `{state['b14_status']}` |",
        f"| B14 provider mode | `{state['b14_provider_mode']}` |",
        f"| B14 has server key | `{state['b14_has_key']}` |",
        f"| B14 catalog models | `{state['b14_catalog_models']}` |",
    ]


def main() -> int:
    b14 = read_b14_health()
    emit_b14(b14)

    try:
        token = required_env("CLOUDFLARE_API_TOKEN")
        account_id = required_env("CLOUDFLARE_ACCOUNT_ID")
        headers = cf_headers(token)

        verify_status, verify = get_json(f"{CF_API}/user/tokens/verify", headers)
        if verify_status != 200 or verify.get("success") is not True:
            raise RuntimeError(f"Cloudflare token verification failed with HTTP {verify_status}")

        worker_status = get_status_without_body(
            f"{CF_API}/accounts/{account_id}/workers/scripts/{WORKER_NAME}", headers
        )
        if worker_status == 200:
            worker_state = "existing"
        elif worker_status == 404:
            worker_state = "absent"
        elif worker_status in {401, 403}:
            worker_state = "permission_denied"
            write_output("worker_state", worker_state)
            append_summary([
                "## B62 Cloudflare read-only preflight",
                "",
                "| Check | Result |",
                "|---|---|",
                "| Cloudflare token verify | PASS |",
                f"| Workers script read | `HTTP {worker_status} — permission denied` |",
                *b14_summary_rows(b14),
                "| Provider/model calls | `0` |",
                "",
                "B14 health is recorded, not gating: a `check_error` is a failed",
                "readiness probe, while `unavailable_expected` is a degraded",
                "service. Neither blocks this Cloudflare deploy.",
            ])
            raise RuntimeError(
                f"Cloudflare token lacks Workers script read permission (HTTP {worker_status})"
            )
        else:
            raise RuntimeError(f"unexpected Workers script lookup HTTP {worker_status}")

        subdomain_status, subdomain_payload = get_json(
            f"{CF_API}/accounts/{account_id}/workers/subdomain", headers
        )
        if subdomain_status != 200 or subdomain_payload.get("success") is not True:
            raise RuntimeError(f"workers.dev subdomain lookup failed with HTTP {subdomain_status}")
        subdomain = str((subdomain_payload.get("result") or {}).get("subdomain") or "").strip()
        if not subdomain:
            raise RuntimeError("workers.dev subdomain is empty")

        write_output("worker_state", worker_state)
        write_output("subdomain", subdomain)

        print("CLOUDFLARE_TOKEN_VERIFY=PASS")
        print(f"PADIEM_CHAT_WORKER_STATE={worker_state}")
        print(f"WORKERS_DEV_SUBDOMAIN={subdomain}")

        append_summary([
            "## B62 Cloudflare read-only preflight",
            "",
            "| Check | Result |",
            "|---|---|",
            "| Cloudflare token verify | PASS |",
            f"| `padiem-chat` Worker | `{worker_state}` |",
            f"| workers.dev subdomain | `{subdomain}` |",
            *b14_summary_rows(b14),
            "| Provider/model calls | `0` |",
            "",
            "B14 health is recorded, not gating: a `check_error` is a failed",
            "readiness probe, while `unavailable_expected` is a degraded",
            "service. Neither blocks this Cloudflare deploy.",
        ])
        return 0
    except Exception as exc:
        print(f"B62_PREFLIGHT_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
