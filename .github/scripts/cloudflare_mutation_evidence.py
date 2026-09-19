#!/usr/bin/env python3
"""Mutation-class served-version evidence decisions (#2752, #2451 item 6).

A served-version read only means something relative to the mutation that
preceded it. Three classes, three different obligations:

```text
CODE_DEPLOY  the served version MUST change              post != pre
SECRET_PUT   a change is evidence-only, never mandatory  YES | NO both pass
ROLLBACK     the served version MUST EQUAL what was named post == target
```

Treating these alike is what produced the contradictions the #2451 audit found:
one Engine secret-PUT gate required a version change it must not require, and
the rollback job claimed success from a command exit without naming a target at
all (#2748). This module is the single place that decides.

Pure and read-only by construction: it performs no HTTP, no curl, no file
discovery, and no Cloudflare envelope parsing. It consumes the ordered
observations a caller already obtained from the canonical resolver
(``cloudflare_served_version.py`` via ``b54_engine_served_version_guard.py``),
so envelope shape rules stay in exactly one place. The #2453 secret-PUT
semantics are preserved deliberately, including the stable-observation floor, so
a caller in another lane can adopt this contract without re-deriving it.

Observations are one entry per poll, in order:

- ``(True, version_id)``  an acceptable read: the canonical resolver succeeded;
- ``(False, None)``       a rejected read: non-canonical, ambiguous, or a
                          transport failure. A rejected read is never evidence
                          in either direction; it is skipped, and it does not
                          finalize anything while the window is still open.

The verdict carries ``final`` so a caller polling on a bounded window can tell a
closed failure apart from "not decided yet, keep reading".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

# The scripts directory is not a package, so make the canonical resolver
# importable whether this module is used directly or loaded through importlib in
# a test.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Reuse the canonical safe-version-id contract (#2740) rather than deriving a
# second regex: an id this resolver would refuse must never become evidence, an
# output token, or a log line here.
from cloudflare_served_version import is_safe_version_id  # noqa: E402

CODE_DEPLOY = "CODE_DEPLOY"
SECRET_PUT = "SECRET_PUT"
ROLLBACK = "ROLLBACK"

MUTATION_CLASSES = (CODE_DEPLOY, SECRET_PUT, ROLLBACK)

# A classes' "must the version change?" obligation, kept next to the classes so
# a new class cannot silently inherit the wrong rule.
REQUIRES_CHANGE = {
    CODE_DEPLOY: True,
    SECRET_PUT: False,
    ROLLBACK: None,  # rollback requires equality with a target, not change
}

# #2453 provenance: a secret PUT may legitimately not roll a version, so "NO"
# is admissible only after enough stable observations to exclude propagation
# lag. Fewer than the floor is undecided, not negative evidence.
MIN_SAME_VERSION_OBSERVATIONS = 15
POLL_ATTEMPTS = 30

# The read window is a ceiling, not a suggestion. It equals the 30-attempt
# polling contract the gates implement, and it is deliberately NOT a parameter:
# a caller must not be able to widen the evidence window by handing over a
# longer sequence.
MAX_OBSERVATIONS = POLL_ATTEMPTS

YES = "YES"
NO = "NO"
FAIL = "FAIL"

# Closed, bounded reason codes. Reasons are never free prose and never carry a
# version id, so no input string can be reflected into stdout/stderr through
# them (#2752 review blocker 3).
REASON_CODES = (
    "ROLLBACK_TARGET_OBSERVED",
    "ROLLBACK_TARGET_NOT_OBSERVED",
    "CODE_DEPLOY_DIVERGED",
    "SECRET_PUT_DIVERGED",
    "SECRET_PUT_NO_DIVERGENCE_STABLE",
    "CODE_DEPLOY_DID_NOT_DIVERGE",
    "BELOW_STABLE_OBSERVATION_FLOOR",
    "NO_ACCEPTABLE_OBSERVATION",
    "INVALID_VERSION_ID",
    "UNUSABLE_ACCEPTED_OBSERVATION_ID",
    "OBSERVATION_LIMIT_EXCEEDED",
)


class EvidenceInputError(ValueError):
    """The caller's inputs cannot express a well-formed evidence question."""


class Evidence:
    """The verdict plus the observation counts that justify it.

    A plain class rather than a dataclass/NamedTuple so the module stays
    loadable through ``importlib.util.spec_from_file_location`` without a
    ``sys.modules`` entry, which is how this repository's guard tests import
    scripts under test.
    """

    __slots__ = (
        "verdict", "final", "post_version_id", "observations",
        "same_observations", "rejected_observations", "diverged_at", "reason",
    )

    def __init__(
        self,
        verdict: str,
        final: bool,
        post_version_id: "str | None",
        observations: int,
        same_observations: int,
        rejected_observations: int,
        diverged_at: "int | None",
        reason: str,
    ) -> None:
        self.verdict = verdict
        self.final = final
        self.post_version_id = post_version_id
        self.observations = observations
        self.same_observations = same_observations
        self.rejected_observations = rejected_observations
        self.diverged_at = diverged_at
        self.reason = reason

    def as_kv(self) -> "dict[str, str]":
        return {
            "MUTATION_CLASS_VERDICT": self.verdict,
            "MUTATION_CLASS_FINAL": "YES" if self.final else "NO",
            "POST_MUTATION_SERVED_VERSION_ID": self.post_version_id or "NONE",
            "MUTATION_EVIDENCE_OBSERVATIONS": str(self.observations),
            "MUTATION_EVIDENCE_SAME_OBSERVATIONS": str(self.same_observations),
            "MUTATION_EVIDENCE_REJECTED_OBSERVATIONS": str(self.rejected_observations),
            "MUTATION_EVIDENCE_DIVERGED_AT": (
                "NONE" if self.diverged_at is None else str(self.diverged_at)
            ),
            "MUTATION_EVIDENCE_REASON": self.reason,
        }


def _counts(observations: Sequence[tuple[bool, object]], acceptable: "list[tuple[int, str]]",
            pre_version_id: str) -> "dict[str, int]":
    return {
        "observations": len(observations),
        "same_observations": sum(1 for _, value in acceptable if value == pre_version_id),
        "rejected_observations": sum(1 for accepted, _ in observations if not accepted),
    }


def _fail(reason: str, *, final: bool, **observed: object) -> Evidence:
    return Evidence(
        verdict=FAIL,
        final=final,
        post_version_id=observed.get("post_version_id", None),  # type: ignore[arg-type]
        observations=int(observed.get("observations", 0)),  # type: ignore[arg-type,call-overload]
        same_observations=int(observed.get("same_observations", 0)),  # type: ignore[arg-type,call-overload]
        rejected_observations=int(observed.get("rejected_observations", 0)),  # type: ignore[arg-type,call-overload]
        diverged_at=observed.get("diverged_at", None),  # type: ignore[arg-type]
        reason=reason,
    )


def decide(
    mutation_class: str,
    pre_version_id: object,
    observations: Sequence[tuple[bool, object]],
    *,
    target_version_id: object = None,
    window_open: bool = False,
    min_same_observations: int = MIN_SAME_VERSION_OBSERVATIONS,
) -> Evidence:
    """Classify what ordered served-version reads prove about one mutation.

    ``window_open`` says whether the caller can still read again. With it set, an
    undecided verdict is reported as ``final=False`` so a poll keeps going
    instead of closing early on a slow propagation.

    Every version id is validated against the canonical safe-id contract before
    it can be evidence, and the returned ``post_version_id`` is therefore always
    a value that passed that contract. No reason string interpolates an id.
    """
    if mutation_class not in MUTATION_CLASSES:
        raise EvidenceInputError("mutation class is not one of the closed vocabulary")
    if min_same_observations < 1:
        raise EvidenceInputError("minimum same-version observation floor must be positive")
    if min_same_observations > MAX_OBSERVATIONS:
        raise EvidenceInputError("stable-observation floor exceeds the canonical read window")
    if not is_safe_version_id(pre_version_id):
        # Raised, not classified: the caller cannot ask a well-formed evidence
        # question about a pre-state this module would not accept as served.
        raise EvidenceInputError("pre-mutation version id is not a canonical safe version id")
    if mutation_class == ROLLBACK and not is_safe_version_id(target_version_id):
        raise EvidenceInputError(
            "rollback requires an explicit canonical target version id"
        )

    if len(observations) > MAX_OBSERVATIONS:
        # The window is a ceiling. Over-window input is refused closed instead
        # of being quietly classified, so a caller cannot widen the evidence
        # window by handing over more reads than the gate contract allows.
        return _fail(
            "OBSERVATION_LIMIT_EXCEEDED",
            final=True,
            observations=len(observations),
            same_observations=0,
            rejected_observations=0,
        )

    acceptable: list[tuple[int, str]] = []
    for index, entry in enumerate(observations):
        try:
            accepted, value = entry
        except (TypeError, ValueError):
            raise EvidenceInputError("each observation must be an (acceptable, version) pair")
        if not accepted:
            continue  # a rejected read never finalizes anything
        if value is None or (isinstance(value, str) and not value.strip()):
            return _fail(
                "UNUSABLE_ACCEPTED_OBSERVATION_ID",
                final=True,
                **_counts(observations, acceptable, pre_version_id),
            )
        if not is_safe_version_id(value):
            # Claimed acceptable but unsafe: it must not satisfy an equality or
            # change claim, and its value is deliberately never echoed.
            return _fail(
                "INVALID_VERSION_ID",
                final=True,
                **_counts(observations, acceptable, pre_version_id),
            )
        acceptable.append((index, str(value)))

    counts = _counts(observations, acceptable, pre_version_id)

    if not acceptable:
        return _fail(
            "NO_ACCEPTABLE_OBSERVATION",
            final=not window_open,
            **counts,
        )

    if mutation_class == ROLLBACK:
        for _, value in acceptable:
            if value == target_version_id:
                return Evidence(
                    verdict=YES,
                    final=True,
                    post_version_id=value,
                    diverged_at=None,
                    reason="ROLLBACK_TARGET_OBSERVED",
                    **counts,
                )
        return _fail(
            "ROLLBACK_TARGET_NOT_OBSERVED",
            final=not window_open,
            post_version_id=acceptable[-1][1],
            **counts,
        )

    for index, value in acceptable:
        if value != pre_version_id:
            diverged_at = index + 1
            if mutation_class == SECRET_PUT:
                return Evidence(
                    verdict=YES,
                    final=True,
                    post_version_id=value,
                    diverged_at=diverged_at,
                    reason="SECRET_PUT_DIVERGED",
                    **counts,
                )
            return Evidence(
                verdict=YES,
                final=True,
                post_version_id=value,
                diverged_at=diverged_at,
                reason="CODE_DEPLOY_DIVERGED",
                **counts,
            )

    # Every acceptable read still names the pre-mutation version.
    if mutation_class == SECRET_PUT:
        if counts["same_observations"] >= min_same_observations:
            return Evidence(
                verdict=NO,
                final=True,
                post_version_id=acceptable[-1][1],
                diverged_at=None,
                reason="SECRET_PUT_NO_DIVERGENCE_STABLE",
                **counts,
            )
        return _fail(
            "BELOW_STABLE_OBSERVATION_FLOOR",
            final=not window_open,
            post_version_id=acceptable[-1][1],
            **counts,
        )

    return _fail(
        "CODE_DEPLOY_DID_NOT_DIVERGE",
        final=not window_open,
        post_version_id=acceptable[-1][1],
        **counts,
    )


def _parse_observations(path: Path) -> list[tuple[bool, object]]:
    """Read one observation per line: ``ok <version_id>`` or ``reject -``."""
    observations: list[tuple[bool, object]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        kind, _, value = line.partition(" ")
        if kind == "ok":
            observations.append((True, value.strip() or None))
        elif kind == "reject":
            observations.append((False, None))
        else:
            raise EvidenceInputError("observation lines must start with ok or reject")
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cloudflare_mutation_evidence.py")
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser(
        "evaluate",
        help="classify ordered canonical served-version reads for one mutation class",
    )
    evaluate.add_argument("--class", dest="mutation_class", required=True,
                          choices=MUTATION_CLASSES)
    evaluate.add_argument("--pre-version", required=True, help="served version before the mutation")
    evaluate.add_argument("--target-version", help="required for ROLLBACK")
    evaluate.add_argument("--observations", required=True, type=Path,
                          help="file of ordered observations, one 'ok <id>' / 'reject -' per line")
    evaluate.add_argument("--window-open", action="store_true",
                          help="the caller may still poll again")
    evaluate.add_argument("--min-same-observations", type=int,
                          default=MIN_SAME_VERSION_OBSERVATIONS)

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        evidence = decide(
            args.mutation_class,
            args.pre_version,
            _parse_observations(args.observations),
            target_version_id=args.target_version,
            window_open=args.window_open,
            min_same_observations=args.min_same_observations,
        )
    except EvidenceInputError as exc:
        print("MUTATION_CLASS_EVIDENCE=INPUT_ERROR", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1
    except OSError:
        print("MUTATION_CLASS_EVIDENCE=INPUT_ERROR", file=sys.stderr)
        print("REASON=observation file could not be read", file=sys.stderr)
        return 1

    for key, value in evidence.as_kv().items():
        print(f"{key}={value}")
    print("HTTP_CALLS=0")
    print("CLOUDFLARE_ENVELOPE_PARSING=0")
    print("PRODUCTION_MUTATION=0")
    # Exit vocabulary for a polling caller: 0 decided-and-accepted,
    # 1 closed failure, 3 not final yet so keep reading.
    if evidence.verdict == FAIL:
        return 1 if evidence.final else 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
