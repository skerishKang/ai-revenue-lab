#!/usr/bin/env python3
"""Proof of B62 public origins; precise control-plane 504 fallback.

Only a 504 from the Cloudflare script subdomain metadata endpoint may fall
back to independent public data-plane evidence from BOTH exact origins.
All other management errors, wrong service, and invalid health fail closed.

Every refusal names its own condition. A stopped release has to say which fact
it refused on, because exit 1 alone cannot tell a disabled workers.dev subdomain
apart from a lost health GET, and the two need different repairs. Cause lines
carry condition codes only: never a URL, a body, or a token.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PLANES = {"workers": "WORKERS_DEV", "custom": "CUSTOM_DOMAIN"}
NO_RESPONSE = {"", "000"}


class OriginProofError(ValueError):
    """A public-safe refusal carrying only its condition code."""


def health_verdict(plane: str, code: str, body: str) -> None:
    if code in NO_RESPONSE:
        raise OriginProofError(f"HEALTH_{plane}_NO_RESPONSE")
    if code != "200":
        raise OriginProofError(f"HEALTH_{plane}_HTTP_{code}")
    if not _exact_health_envelope(body):
        raise OriginProofError(f"HEALTH_{plane}_ENVELOPE_MISMATCH")


def _exact_health_envelope(body: str) -> bool:
    try:
        obj = json.loads(body)
    except (TypeError, ValueError):
        return False
    return (isinstance(obj, dict) and obj.get("status") == "ok"
            and obj.get("app") == "padiem-chat"
            and obj.get("runtime") == "b14")


def prove(meta_code: str, meta_body: str,
          workers_code: str, workers_body: str,
          custom_code: str, custom_body: str) -> str:
    health_verdict(PLANES["workers"], workers_code, workers_body)
    health_verdict(PLANES["custom"], custom_code, custom_body)
    if meta_code == "504":
        return "DATAPLANE_504_FALLBACK"
    if meta_code in NO_RESPONSE:
        raise OriginProofError("METADATA_NO_RESPONSE")
    if meta_code != "200":
        raise OriginProofError(f"METADATA_HTTP_{meta_code}")
    try:
        obj = json.loads(meta_body)
    except (TypeError, ValueError) as exc:
        raise OriginProofError("METADATA_NOT_JSON") from exc
    if not isinstance(obj, dict) or obj.get("success") is not True:
        raise OriginProofError("METADATA_SUCCESS_NOT_TRUE")
    result = obj.get("result")
    if not isinstance(result, dict):
        raise OriginProofError("SUBDOMAIN_RESULT_NOT_OBJECT")
    if "enabled" not in result:
        # The per-Worker /subdomain contract carries `enabled`, verified against
        # the live account. Its absence is an anomaly and never a pass.
        raise OriginProofError("SUBDOMAIN_FLAG_ABSENT")
    if result["enabled"] is not True:
        raise OriginProofError("SUBDOMAIN_DISABLED_EXPLICIT")
    return "CONTROL_AND_DATA_PLANE"


def main() -> int:
    p = argparse.ArgumentParser()
    for name in ("metadata", "workers", "custom"):
        p.add_argument("--" + name + "-status", required=True)
        p.add_argument("--" + name + "-body", type=Path, required=True)
    a = p.parse_args()
    planes = ("METADATA", "WORKERS_DEV", "CUSTOM_DOMAIN")
    paths = {"METADATA": a.metadata_body, "WORKERS_DEV": a.workers_body,
             "CUSTOM_DOMAIN": a.custom_body}
    status = {"METADATA": a.metadata_status, "WORKERS_DEV": a.workers_status,
              "CUSTOM_DOMAIN": a.custom_status}
    body = {}
    for plane in planes:
        try:
            body[plane] = paths[plane].read_text(encoding="utf-8")
        except OSError:
            return _blocked(f"GUARD_INPUT_UNREADABLE_{plane}")
    try:
        mode = prove(status["METADATA"], body["METADATA"],
                     status["WORKERS_DEV"], body["WORKERS_DEV"],
                     status["CUSTOM_DOMAIN"], body["CUSTOM_DOMAIN"])
    except OriginProofError as exc:
        return _blocked(str(exc))
    print("B62_PUBLIC_ORIGIN_PROOF=PASS")
    print("B62_PUBLIC_ORIGIN_PROOF_MODE=" + mode)
    print("SECRET_VALUES_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")
    return 0


def _blocked(cause: str) -> int:
    print("B62_PUBLIC_ORIGIN_PROOF=BLOCKED")
    print("B62_PUBLIC_ORIGIN_PROOF_CAUSE=" + cause)
    print("SECRET_VALUES_OUTPUT=0")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
