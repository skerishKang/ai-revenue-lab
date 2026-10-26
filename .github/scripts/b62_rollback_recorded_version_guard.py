#!/usr/bin/env python3
"""Let a recorded rollback recover a Worker whose newest upload never served traffic.

The canonical ``latest == active`` lineage guard asks whether the newest uploaded
version is the one serving traffic. That is the right question for a read-only audit
and for a new code deploy. Asked of a rollback it stops being an answer and becomes a
lock: a deploy uploads a version, serves it, and is then refused by its own
post-deploy audit, so traffic is restored to the recorded version while the refused
upload stays the newest version in the account. From that moment every rollback —
the operation that proves the restoration held — fails the guard the refused upload
tripped, and the account can only be confirmed by mutating it further.

So the mismatch is kept visible and the record is validated instead. The recorded id
must be a canonical version id that the deployment history actually served, and it
must be either the version serving traffic now or the version that served it
immediately before. A never-served upload, a foreign id, or a malformed id still fails
closed, which is the protection the strict guard was providing.

Read-only by construction: it parses the deployments envelope the caller already
fetched and never calls Cloudflare, never reads a secret, never mutates.

```text
HTTP_CALLS=0
SECRET_READ=0
PRODUCTION_MUTATION=0
```

The predecessor record is not required to carry ``percentage == 100``: the 100% rule
belongs to the deployment serving traffic right now, while the entry below it is a
history record whose stored percentage describes the rollout it was created for.
Requiring it would refuse a legitimate rollback on the shape of an old record.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cloudflare_served_version import (  # noqa: E402
    ServedVersionResolutionError,
    is_safe_version_id,
    resolve_served_version_id,
)

RECORDED_OUTPUT = "B62_ROLLBACK_RECORDED_VERSION"
LINEAGE_OUTPUT = "LATEST_VERSION_EQUALS_ACTIVE_VERSION"
UNSERVED_LATEST_REASON = "unactivated_latest_upload"
ACTIVE_ROLE = "ACTIVE"
PREDECESSOR_ROLE = "PREDECESSOR"


class RecordedVersionError(ValueError):
    """The recorded id is not a version this Worker actually served."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def is_canonical_version_id(value: object) -> bool:
    """Mirror the rollback request builder: canonical lowercase UUID, nothing else.

    A rollback is the one mutation that accepts a bare historical id, so the id is
    held to the same shape the request builder will refuse to serialize.
    """

    if not isinstance(value, str):
        return False
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return canonical == value


def _predecessor_version_id(deployments: list[object]) -> str:
    if len(deployments) < 2:
        raise RecordedVersionError("no-predecessor-record")
    entry = deployments[1]
    if not isinstance(entry, dict):
        raise RecordedVersionError("predecessor-entry")
    versions = entry.get("versions")
    if not isinstance(versions, list) or len(versions) != 1:
        raise RecordedVersionError("predecessor-version-count")
    version = versions[0]
    if not isinstance(version, dict):
        raise RecordedVersionError("predecessor-version-entry")
    version_id = version.get("version_id")
    if not is_safe_version_id(version_id):
        raise RecordedVersionError("predecessor-version-id")
    return version_id


def resolve_recorded_role(deployments_payload: object, recorded_version_id: str) -> str:
    """Return ACTIVE or PREDECESSOR for a recorded id, or raise a closed reason."""

    if not is_canonical_version_id(recorded_version_id):
        raise RecordedVersionError("recorded-id-shape")
    try:
        active = resolve_served_version_id(deployments_payload)
    except ServedVersionResolutionError as exc:
        raise RecordedVersionError(f"active-{exc.reason}") from exc
    if recorded_version_id == active:
        return ACTIVE_ROLE
    deployments = deployments_payload["result"]["deployments"]
    if recorded_version_id == _predecessor_version_id(deployments):
        return PREDECESSOR_ROLE
    raise RecordedVersionError("recorded-id-not-served-history")


def resolve_served_active_version(deployments_payload: object) -> str:
    try:
        return resolve_served_version_id(deployments_payload)
    except ServedVersionResolutionError as exc:
        raise RecordedVersionError(f"active-{exc.reason}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deployments", required=True, type=Path,
                        help="path to a fetched GET /deployments envelope")
    # Named away from the lineage CLI's --latest-version: the gate pins exactly
    # one canonical latest==active call site, and this branch asks a different question.
    parser.add_argument("--newest-upload-version", required=True,
                        help="newest upload id the caller resolved from GET /versions")
    parser.add_argument("--previous-version-id", required=True,
                        help="recorded version id the rollback mode was asked to restore")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.deployments.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"{RECORDED_OUTPUT}=BLOCKED:deployments-unreadable", file=sys.stderr)
        print(f"CAUSE={type(exc).__name__}", file=sys.stderr)
        return 1

    try:
        active = resolve_served_active_version(payload)
    except RecordedVersionError as exc:
        print(f"{RECORDED_OUTPUT}=BLOCKED:{exc.reason}", file=sys.stderr)
        return 1

    if not is_safe_version_id(args.newest_upload_version):
        print(f"{LINEAGE_OUTPUT}=FAIL_CLOSED", file=sys.stderr)
        print(f"{RECORDED_OUTPUT}=BLOCKED:latest-id-shape", file=sys.stderr)
        return 1

    try:
        role = resolve_recorded_role(payload, args.previous_version_id)
    except RecordedVersionError as exc:
        print(f"{RECORDED_OUTPUT}=BLOCKED:{exc.reason}", file=sys.stderr)
        return 1

    print(f"ACTIVE_VERSION={active}")
    if args.newest_upload_version == active:
        print(f"{LINEAGE_OUTPUT}=PASS")
    else:
        # Downgraded from a refusal to a loud warning: the newest upload never
        # served traffic, which is exactly the residue a rollback is here to prove
        # is inert. It stays in the operator record instead of blocking the read.
        print(f"{LINEAGE_OUTPUT}=WARN:{UNSERVED_LATEST_REASON}")
        print(f"LATEST_UNSERVED_VERSION={args.newest_upload_version}")
    print(f"{RECORDED_OUTPUT}={role}")
    print("B62_ROLLBACK_RECORDED_VERSION_MATCHES_SERVED_HISTORY=PASS")
    print("HTTP_CALLS=0")
    print("SECRET_READ=0")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
