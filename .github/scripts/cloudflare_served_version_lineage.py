#!/usr/bin/env python3
"""Canonical ``latest == active`` served-version lineage precondition.

Independent named primitive for #2451 P1 item 7 / child #2895.

Three served-version authorities exist, and this module deliberately merges none
of them:

```text
cloudflare_served_version.py     answers: which version is serving traffic right now?
                                 (refuses ambiguous envelopes, resolves ``deployments[0]``)

cloudflare_mutation_evidence.py  answers: did this mutation class require or observe a
                                 served-version change? (mutation-class evidence)

this module                      answers: do the two already-resolved canonical ids agree?
                                 (PASS | FAIL | FAIL_CLOSED)
```

Because it only compares two ids, it never resolves, never fetches an envelope,
never reads a secret and never mutates anything:

```text
HTTP_CALLS=0
ENVELOPE_FETCH=0
CLOUDFLARE_MUTATION=0
SECRET_READ=0
```

It consumes **only** ids the canonical resolver has already accepted
(``resolve_served_version_id`` / the guard lanes that call it), and it reuses the
canonical ``is_safe_version_id`` contract instead of restating the id charset.

This module defines no second input shape either: the CLI accepts a **bare
canonical version-id string** only (``--active-version <id> --latest-version <id>``).
It deliberately does not parse JSON objects, and it does not accept ``id`` /
``value`` aliases -- those are not the canonical resolver's output contract, and
admitting them would create a shadow input-shape adapter. A caller holding a
JSON object must extract the id itself and pass the bare value.

Rules, fail-closed with no positional guessing:

```text
latest == active          -> PASS
latest != active          -> FAIL
missing active id         -> FAIL_CLOSED
missing latest id         -> FAIL_CLOSED
unsafe active id          -> FAIL_CLOSED
unsafe latest id          -> FAIL_CLOSED
```

A caller that needs a stricter id shape (for example "exact lowercase UUID")
still layers that precondition locally, as ``cloudflare_served_version`` already
documents; this module owns only the equality precondition.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The scripts directory is not a package, so import the canonical id contract by
# path. This is the only cross-module dependency, and it is one-way: the
# precondition reuses the resolver's published contract and never reimplements it.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from cloudflare_served_version import is_safe_version_id  # noqa: E402

# Closed outcome vocabulary. Stable identifiers, not prose.
PASS = "PASS"
FAIL = "FAIL"
FAIL_CLOSED = "FAIL_CLOSED"

OUTCOMES = (PASS, FAIL, FAIL_CLOSED)

# Bounded marker the adopter surfaces; matches the marker the repository already
# publishes inline in three workflows so an adopter can switch without changing
# the operator-facing vocabulary.
LINEAGE_MARKER = "LATEST_VERSION_EQUALS_ACTIVE_VERSION"

REFUSED_PLACEHOLDER = "REFUSED"


class LineageReason:
    """Closed vocabulary of latest==active precondition outcomes."""

    EQUAL = "equal"
    DIFFERENT = "different"
    MISSING_ACTIVE = "missing-active"
    MISSING_LATEST = "missing-latest"
    UNSAFE_ACTIVE = "unsafe-active"
    UNSAFE_LATEST = "unsafe-latest"


@dataclass(frozen=True, slots=True)
class LineageDecision:
    """Bounded, non-secret result of the precondition.

    ``active_version_id`` / ``latest_version_id`` carry the raw inputs only when
    they are safe to echo; an unsafe or missing value is reported as
    ``REFUSED``/``None`` so no payload text can leak into CI output.
    """

    outcome: str
    reason: str
    active_version_id: str | None
    latest_version_id: str | None

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError("unknown lineage outcome")
        for value in (self.active_version_id, self.latest_version_id):
            if value is not None and not isinstance(value, str):
                raise ValueError("lineage ids must be strings or None")

    @property
    def passed(self) -> bool:
        return self.outcome == PASS

    @property
    def failed(self) -> bool:
        return self.outcome == FAIL

    @property
    def fail_closed(self) -> bool:
        return self.outcome == FAIL_CLOSED

    def _render(self, value: str | None) -> str:
        if isinstance(value, str) and is_safe_version_id(value):
            return value
        return REFUSED_PLACEHOLDER

    def render(self) -> list[str]:
        """Return the bounded marker lines an adopter publishes."""

        return [
            f"{LINEAGE_MARKER}={self.outcome if self.outcome != FAIL_CLOSED else FAIL}",
            f"SERVED_VERSION_LINEAGE_OUTCOME={self.outcome}",
            f"SERVED_VERSION_LINEAGE_REASON={self.reason}",
            f"SERVED_VERSION_LINEAGE_ACTIVE_VERSION={self._render(self.active_version_id)}",
            f"SERVED_VERSION_LINEAGE_LATEST_VERSION={self._render(self.latest_version_id)}",
            "SERVED_VERSION_LINEAGE_HTTP_CALLS=0",
            "SERVED_VERSION_LINEAGE_ENVELOPE_FETCH=0",
            "SERVED_VERSION_LINEAGE_MUTATION=0",
            "SERVED_VERSION_LINEAGE_SECRET_READ=0",
        ]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "reason": self.reason,
            "active_version_id": self._render(self.active_version_id),
            "latest_version_id": self._render(self.latest_version_id),
            "http_calls": 0,
            "envelope_fetch": 0,
            "cloudflare_mutation": 0,
            "secret_read": 0,
        }


def _missing(value: object) -> bool:
    """Report whether a caller supplied no id at all (absent or blank)."""

    if value is None:
        return True
    return isinstance(value, str) and value.strip() == ""


def evaluate_latest_equals_active(
    active_version_id: object, latest_version_id: object
) -> LineageDecision:
    """Decide whether the canonical active and latest version ids agree.

    The inputs must already be resolved canonical ids. This function performs no
    resolution, no fetch and no mutation: it validates presence and charset with
    the canonical contract and then compares.
    """

    if _missing(active_version_id):
        return LineageDecision(FAIL_CLOSED, LineageReason.MISSING_ACTIVE, None, None)
    if not is_safe_version_id(active_version_id):
        return LineageDecision(FAIL_CLOSED, LineageReason.UNSAFE_ACTIVE, None, None)
    if _missing(latest_version_id):
        return LineageDecision(
            FAIL_CLOSED, LineageReason.MISSING_LATEST, active_version_id, None
        )
    if not is_safe_version_id(latest_version_id):
        return LineageDecision(
            FAIL_CLOSED, LineageReason.UNSAFE_LATEST, active_version_id, None
        )
    if active_version_id == latest_version_id:
        return LineageDecision(
            PASS, LineageReason.EQUAL, active_version_id, latest_version_id
        )
    return LineageDecision(FAIL, LineageReason.DIFFERENT, active_version_id, latest_version_id)


def main(argv: list[str] | None = None) -> int:
    """CLI. Exit 0 only on PASS; FAIL and FAIL_CLOSED exit non-zero.

    Input is a bare canonical version-id string. A JSON object (or any other
    non-bare shape) is unsafe by the canonical charset rule and fails closed.
    """

    parser = argparse.ArgumentParser(
        description="Independent latest==active served-version lineage precondition."
    )
    parser.add_argument("--active-version", required=True)
    parser.add_argument("--latest-version", required=True)
    parser.add_argument(
        "--format",
        choices=("markers", "json"),
        default="markers",
        help="markers: bounded KEY=VALUE lines; json: bounded decision object",
    )
    args = parser.parse_args(argv)

    decision = evaluate_latest_equals_active(
        args.active_version,
        args.latest_version,
    )
    if args.format == "json":
        print(json.dumps(decision.safe_dict(), sort_keys=True))
    else:
        for line in decision.render():
            print(line)
    if decision.outcome == PASS:
        return 0
    if decision.outcome == FAIL_CLOSED:
        return 2
    return 1


if __name__ == "__main__":  # pragma: no cover - exercised via main() below
    raise SystemExit(main())
