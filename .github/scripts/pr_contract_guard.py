#!/usr/bin/env python3
"""Pull-request contract report for the Web CTO review chain.

`AGENTS.md` and `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` separate
product authority, the Web CTO contract/review, the Web Developer
implementation and independent Local Validation. Those separations are only
auditable when a pull request body carries the fields the chain depends on:
exact revision identity, the evidence dimensions in play, implementation
evidence, the independent-validation decision, owner-only decisions, the
completion checklist and the Web CTO final status.

This guard never edits a pull request and never claims a review verdict. It
reports which load-bearing fields are present.

- default: report only (exit 0) so an in-flight pipeline is not blocked;
- `PR_CONTRACT_GUARD_ENFORCE=1`: fail when a load-bearing field is missing.

A pull request body that claims a CTO approval without recording the CTO final
status block is reported as `unrecorded_approval_claim`. The claim may be true,
but it is not attributable to a revision until it is recorded in the pull
request or in a committed `CTO_FINAL_REVIEW` artifact.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Sections the pull request template declares and the review chain depends on.
REQUIRED_SECTIONS = (
    "Authority / revision",
    "Evidence dimensions",
    "Implementation evidence",
    "Independent validation",
    "Owner-only decisions",
    "Completion checklist",
    "CTO final status",
)

# Revision identity: at least one git object id (short or full).
SHA_PATTERN = re.compile(r"\b[0-9a-f]{7,40}\b")

# Issue / work-order authority link.
ISSUE_LINK_PATTERNS = (
    re.compile(
        r"(?i)\b(?:closes|close|closed|fixes|fix|fixed|resolves|resolve|refs|ref|references|advances|tracks|part of)\b[^\n#]{0,24}#\d+"
    ),
    re.compile(r"#\d{3,}"),
)

# Web CTO final status vocabulary from WORKFLOW_STATUS_MODEL.md §8.
STATUS_PATTERN = re.compile(
    r"\b(NOT_REVIEWED|NOT_READY|CONDITIONALLY_READY|READY)\b"
)

# A CTO approval claim that is not accompanied by the CTO final status block.
APPROVAL_CLAIM_PATTERN = re.compile(
    r"(?i)(cto[\s_-]*approved|cto[\s_-]*approval|approved by (?:the )?cto|"
    r"cto[\s_-]*review(?:ed)? and approved)"
)


def _has_section(body: str, name: str) -> bool:
    pattern = re.compile(r"^#{1,6}\s*" + re.escape(name) + r"\s*$", re.MULTILINE)
    return bool(pattern.search(body))


def _has_issue_link(body: str) -> bool:
    return any(pattern.search(body) for pattern in ISSUE_LINK_PATTERNS)


def audit(body: str | None) -> dict[str, object]:
    """Report contract compliance for one pull request body."""
    text = body or ""
    present = [name for name in REQUIRED_SECTIONS if _has_section(text, name)]
    missing = [name for name in REQUIRED_SECTIONS if name not in present]

    status_match = STATUS_PATTERN.search(text)
    status_token = status_match.group(1) if status_match else "MISSING"

    approval_claim = bool(APPROVAL_CLAIM_PATTERN.search(text)) and (
        "CTO final status" not in present
    )

    has_sha = bool(SHA_PATTERN.search(text))
    has_link = _has_issue_link(text)

    contract_complete = not missing and has_sha and has_link

    return {
        "pull_request_body_present": bool(body),
        "present_sections": present,
        "missing_sections": missing,
        "sections_recorded": f"{len(present)}/{len(REQUIRED_SECTIONS)}",
        "revision_identity": "recorded" if has_sha else "MISSING",
        "work_order_link": "recorded" if has_link else "MISSING",
        "cto_status_token": status_token,
        "unrecorded_approval_claim": approval_claim,
        "contract_complete": contract_complete,
        "guard_mode": "report",
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        body = Path(argv[0]).read_text(encoding="utf-8")
    else:
        body = os.environ.get("PR_BODY") or ""

    if not body.strip():
        report = {
            "pull_request_contract": "not_evaluated",
            "reason": "no pull request body supplied",
            "guard_mode": "report",
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    report = audit(body)
    report["pull_request_contract"] = (
        "complete" if report["contract_complete"] else "incomplete"
    )
    print(json.dumps(report, indent=2, sort_keys=True))

    enforce = os.environ.get("PR_CONTRACT_GUARD_ENFORCE", "") == "1"
    if enforce and not report["contract_complete"]:
        print(
            "PR_CONTRACT_GUARD=FAIL missing: "
            + ", ".join(
                list(report["missing_sections"])
                + (
                    ["revision_identity"]
                    if report["revision_identity"] == "MISSING"
                    else []
                )
                + (
                    ["work_order_link"]
                    if report["work_order_link"] == "MISSING"
                    else []
                )
            ),
            file=sys.stderr,
        )
        return 1

    print("PR_CONTRACT_GUARD=REPORT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
