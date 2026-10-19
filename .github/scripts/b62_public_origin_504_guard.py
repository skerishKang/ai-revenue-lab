#!/usr/bin/env python3
"""Proof of B62 public origins; precise control-plane 504 fallback.

Only a 504 from the Cloudflare script subdomain metadata endpoint may fall
back to independent public data-plane evidence from BOTH exact origins.
All other management errors, wrong service, and invalid health fail closed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


class OriginProofError(ValueError):
    pass


def healthy(code: str, body: str) -> bool:
    if code != "200":
        return False
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
    if not healthy(workers_code, workers_body) or not healthy(custom_code, custom_body):
        raise OriginProofError("PUBLIC_HEALTH_NOT_PROVEN")
    if meta_code == "504":
        return "DATAPLANE_504_FALLBACK"
    if meta_code != "200":
        raise OriginProofError("METADATA_HTTP_NOT_ACCEPTED")
    try:
        obj = json.loads(meta_body)
    except (TypeError, ValueError) as exc:
        raise OriginProofError("METADATA_NOT_JSON") from exc
    if (not isinstance(obj, dict) or obj.get("success") is not True
            or not isinstance(obj.get("result"), dict)
            or obj["result"].get("enabled") is not True):
        raise OriginProofError("SUBDOMAIN_NOT_ENABLED")
    return "CONTROL_AND_DATA_PLANE"


def main() -> int:
    p = argparse.ArgumentParser()
    for name in ("metadata", "workers", "custom"):
        p.add_argument("--" + name + "-status", required=True)
        p.add_argument("--" + name + "-body", type=Path, required=True)
    a = p.parse_args()
    try:
        mode = prove(
            a.metadata_status, a.metadata_body.read_text(encoding="utf-8"),
            a.workers_status, a.workers_body.read_text(encoding="utf-8"),
            a.custom_status, a.custom_body.read_text(encoding="utf-8"),
        )
    except (OriginProofError, OSError):
        print("B62_PUBLIC_ORIGIN_PROOF=BLOCKED")
        print("SECRET_VALUES_OUTPUT=0")
        return 1
    print("B62_PUBLIC_ORIGIN_PROOF=PASS")
    print("B62_PUBLIC_ORIGIN_PROOF_MODE=" + mode)
    print("SECRET_VALUES_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
