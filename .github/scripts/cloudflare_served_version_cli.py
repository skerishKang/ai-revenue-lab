#!/usr/bin/env python3
"""CLI adapter for the canonical Cloudflare served-version resolver (#3656).

The canonical rules remain owned by cloudflare_served_version.py. This adapter
exists only so shell/YAML consumers can reuse those rules instead of
reimplementing result.deployments[0].versions[0] with jq.

It performs no network calls and no mutation. On success, stdout contains only
the safe served-version id, or for ``validate-version-id`` the single
``VERSION_ID_SAFE=YES`` token. Failures expose only a bounded status/reason
vocabulary and never echo response payloads or a rejected candidate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from cloudflare_served_version import (
    ServedVersionReason,
    ServedVersionResolutionError,
    is_safe_version_id,
    resolve_served_version_id,
)


def _load_payload(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("deployments-payload-unreadable") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cloudflare_served_version_cli.py")
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser(
        "resolve-active",
        help="print the canonical served Worker version id",
    )
    resolve.add_argument(
        "--deployments",
        required=True,
        type=Path,
        help="Cloudflare deployments API response JSON file",
    )

    # A rollback target is typed by a dispatcher, so it is untrusted input and it
    # must clear the same contract the resolver applies to a served id before it
    # reaches a mutating command. This subcommand reuses is_safe_version_id; it
    # adds no charset rule of its own.
    validate = sub.add_parser(
        "validate-version-id",
        help="accept a caller-supplied version id under the canonical safe-id contract",
    )
    validate.add_argument(
        "--version-id",
        required=True,
        help="candidate version id",
    )

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.command == "validate-version-id":
        # The candidate is never echoed, in either direction: a rejected string
        # must not be reflected into CI output (#2752 review blocker 3).
        if is_safe_version_id(args.version_id):
            print("VERSION_ID_SAFE=YES")
            return 0
        print("VERSION_ID_SAFE=NO", file=sys.stderr)
        print(f"REASON={ServedVersionReason.VERSION_ID}", file=sys.stderr)
        return 1

    try:
        payload = _load_payload(args.deployments)
        version_id = resolve_served_version_id(payload)
    except ValueError as exc:
        print("SERVED_VERSION_RESOLUTION=INPUT_ERROR", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 2
    except ServedVersionResolutionError as exc:
        print("SERVED_VERSION_RESOLUTION=FAIL", file=sys.stderr)
        print(f"REASON={exc.reason}", file=sys.stderr)
        return 1

    print(version_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
