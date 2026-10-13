#!/usr/bin/env python3
"""Validate GitHub's run-specific independent deployment review (no network)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class IndependentReviewRefused(ValueError):
    """Fail-closed reason safe to print without leaking approval tokens."""


def verify(
    reviews: Any,
    *,
    actor: str,
    triggering_actor: str,
    run_attempt: int,
    environment: str = "production",
) -> str:
    """Require a different human who approved THIS run's production environment."""
    if run_attempt != 1:
        raise IndependentReviewRefused("RERUN_REQUIRES_NEW_DISPATCH")
    if not isinstance(reviews, list):
        raise IndependentReviewRefused("INVALID_REVIEW_HISTORY")
    if not all(isinstance(x, str) and x.strip() for x in (actor, triggering_actor)):
        raise IndependentReviewRefused("INVALID_RUN_ACTOR")
    blocked = {actor.casefold(), triggering_actor.casefold()}
    reviewers: list[str] = []
    for entry in reviews:
        if not isinstance(entry, dict):
            raise IndependentReviewRefused("INVALID_REVIEW_ENTRY")
        targets = entry.get("environments")
        if not isinstance(targets, list):
            raise IndependentReviewRefused("INVALID_REVIEW_ENVIRONMENTS")
        if not any(isinstance(e, dict) and e.get("name") == environment for e in targets):
            continue
        state = entry.get("state")
        if state == "rejected":
            raise IndependentReviewRefused("PRODUCTION_REVIEW_REJECTED")
        if state != "approved":
            continue
        user = entry.get("user")
        if not isinstance(user, dict):
            raise IndependentReviewRefused("INVALID_REVIEWER")
        login, user_id = user.get("login"), user.get("id")
        if (
            not isinstance(login, str) or not login.strip()
            or not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0
            or user.get("type") != "User"
        ):
            raise IndependentReviewRefused("INVALID_REVIEWER")
        if login.casefold() not in blocked:
            reviewers.append(login)
    if not reviewers:
        raise IndependentReviewRefused("INDEPENDENT_PRODUCTION_APPROVAL_MISSING")
    return sorted(set(reviewers), key=str.casefold)[0]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--reviews", type=Path, required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--triggering-actor", required=True)
    p.add_argument("--run-attempt", type=int, required=True)
    a = p.parse_args()
    try:
        reviewer = verify(
            json.loads(a.reviews.read_text(encoding="utf-8")),
            actor=a.actor, triggering_actor=a.triggering_actor,
            run_attempt=a.run_attempt,
        )
    except (OSError, ValueError) as exc:
        print(f"P01_SSE_INDEPENDENT_REVIEW=BLOCKED:{exc}")
        return 2
    print("P01_SSE_INDEPENDENT_REVIEW=PASS")
    print(f"P01_SSE_REVIEWER={reviewer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
