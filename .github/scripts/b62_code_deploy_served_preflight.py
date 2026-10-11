#!/usr/bin/env python3
"""Read-only B62 new-code-deploy preflight, without latest==active requirement.

An unactivated uploaded version must never be promoted as a shortcut.
Before mutation the caller checks both the served and uploaded version IDs
are unchanged and deploys newly built exact-main source.
"""
from __future__ import annotations
import argparse
from cloudflare_served_version import is_safe_version_id


def verify_new_main_deploy_preflight(active: object, latest: object) -> bool:
    return is_safe_version_id(active) and is_safe_version_id(latest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-version", required=True)
    parser.add_argument("--latest-version", required=True)
    args = parser.parse_args(argv)
    if not verify_new_main_deploy_preflight(args.active_version, args.latest_version):
        print("NEW_MAIN_DEPLOY_VERSION_PREFLIGHT=FAIL_CLOSED")
        return 1
    print("NEW_MAIN_DEPLOY_VERSION_PREFLIGHT=PASS")
    print("CURRENT_SERVED_VERSION=VALIDATED")
    print("LATEST_UPLOADED_VERSION=VALIDATED")
    print("UNDEPLOYED_UPLOAD_PRESENT=" + ("YES" if args.active_version != args.latest_version else "NO"))
    print("PREDEPLOY_LATEST_ACTIVE_EQUALITY_REQUIRED=NO")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
