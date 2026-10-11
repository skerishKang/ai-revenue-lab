#!/usr/bin/env python3
"""Standalone read-only snapshot of the five live Padiem Chat quota variables.

This gate exists so the exact current Production quota values can be captured
before any activation, with no mutation of any kind. It reuses the parsing and
fetch primitives already proven in ``b62_cloudflare_live_readiness.py`` so there
is no second Cloudflare parser to drift.

Guarantees:
  * GET-only. It reads Worker settings and nothing else; it never deploys,
    patches, PUTs, mutates secrets, writes D1, or calls a provider/model.
  * Bounded output. It emits, at most, exactly five
    ``QUOTA_SNAPSHOT_<KEY>=<integer>`` lines for the five allowlisted quota
    variables plus a closed ``QUOTA_SNAPSHOT_COMPLETE`` verdict.
  * Fail closed. A missing key, a non-``plain_text`` type, a non-integer value,
    or an out-of-range value suppresses the PASS verdict and every value line.
  * Never prints a secret_text value, an unknown plain_text value, an account
    or database identifier, the full settings JSON, a hash, a fingerprint, a
    length, a prefix/suffix, or an arbitrary response body.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Reuse the proven readiness parser/fetchers instead of duplicating them. The
# scripts directory is not a package, so make it importable whether this module
# is run directly or loaded through importlib in a test.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from b62_cloudflare_live_readiness import (  # noqa: E402
    CF_API,
    QUOTA_LIMITS,
    USER_AGENT,
    WORKER_NAME,
    binding_inventory,
    get_json,
    required_env,
)

# The exact five quota variables whose live values may be surfaced. This is the
# complete output surface; nothing else is ever printed as a value.
QUOTA_SNAPSHOT_KEYS: tuple[str, ...] = (
    "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT",
    "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT",
    "PADIEM_CHAT_USER_BURST_LIMIT",
    "PADIEM_CHAT_USER_DAILY_LIMIT",
    "PADIEM_CHAT_GLOBAL_DAILY_LIMIT",
)

# Closed verdict vocabulary. Only these tokens ever appear after the reason key.
SNAPSHOT_PASS = "PASS"
SNAPSHOT_FAIL = "FAIL"
FAILURE_READ = "READ_FAILED"
FAILURE_MISSING = "MISSING"
FAILURE_WRONG_TYPE = "WRONG_TYPE"
FAILURE_NON_INTEGER = "NON_INTEGER"
FAILURE_RANGE = "RANGE_VIOLATION"
FAILURE_MINIMUM = 1


def evaluate_quota_snapshot(
    types: dict[str, str],
    safe_text: dict[str, str],
) -> tuple[bool, str, dict[str, int]]:
    """Return ``(ok, reason, values)`` for the five quota variables.

    ``ok`` is True only when every key is present, is ``plain_text``, parses as
    an integer, and lies within ``[FAILURE_MINIMUM, QUOTA_LIMITS[key]]``. On any
    failure ``values`` is empty so no partial value can be rendered.
    """
    values: dict[str, int] = {}
    for key in QUOTA_SNAPSHOT_KEYS:
        kind = types.get(key)
        if kind is None:
            return False, FAILURE_MISSING, {}
        if kind != "plain_text":
            return False, FAILURE_WRONG_TYPE, {}
        raw = safe_text.get(key)
        if raw is None:
            return False, FAILURE_MISSING, {}
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return False, FAILURE_NON_INTEGER, {}
        maximum = QUOTA_LIMITS[key]
        if not FAILURE_MINIMUM <= value <= maximum:
            return False, FAILURE_RANGE, {}
        values[key] = value
    return True, "", values


def render_snapshot(ok: bool, reason: str, values: dict[str, int]) -> list[str]:
    """Render the closed-vocabulary output lines.

    Value lines are produced only on a fully valid snapshot. On failure a single
    closed reason token is emitted so the offending raw value is never leaked.
    """
    lines: list[str] = []
    if ok:
        for key in QUOTA_SNAPSHOT_KEYS:
            lines.append(f"QUOTA_SNAPSHOT_{key}={values[key]}")
        lines.append(f"QUOTA_SNAPSHOT_COMPLETE={SNAPSHOT_PASS}")
    else:
        lines.append(f"QUOTA_SNAPSHOT_COMPLETE={SNAPSHOT_FAIL}")
        lines.append(f"QUOTA_SNAPSHOT_FAILURE={reason}")
    return lines


def main() -> int:
    try:
        token = required_env("CLOUDFLARE_API_TOKEN")
        account_id = required_env("CLOUDFLARE_ACCOUNT_ID")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        settings_status, settings_payload = get_json(
            f"{CF_API}/accounts/{account_id}/workers/scripts/{WORKER_NAME}/settings",
            headers,
        )
        if settings_status != 200 or settings_payload.get("success") is not True:
            for line in render_snapshot(False, FAILURE_READ, {}):
                print(line)
            print("REAL_PROVIDER_CALLS=0")
            return 1

        types, safe_text = binding_inventory(settings_payload)
        ok, reason, values = evaluate_quota_snapshot(types, safe_text)
        lines = render_snapshot(ok, reason, values)
        for line in lines:
            print(line)
        print("REAL_PROVIDER_CALLS=0")

        summary = os.getenv("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write("\n## B62 chat quota read-only snapshot\n\n")
                handle.write("```text\n")
                for line in lines:
                    handle.write(f"{line}\n")
                handle.write("PRODUCTION_MUTATION=0\n")
                handle.write("```\n")
        return 0 if ok else 1
    except Exception:
        # Never echo exception detail: it could contain identifiers or bodies.
        print("QUOTA_SNAPSHOT_COMPLETE=FAIL", file=sys.stderr)
        print(f"QUOTA_SNAPSHOT_FAILURE={FAILURE_READ}", file=sys.stderr)
        print("REAL_PROVIDER_CALLS=0", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
