#!/usr/bin/env python3
"""Pull-request contract report for the repository review chain.

The repository supports two reporting modes:

- COMPACT: default for bounded fixes/tiny glue. Keep only the fields needed to
  review the exact change, focused regression, relevant CI and validation
  decision.
- EXTENDED: broad/high-risk work or an explicit work-contract requirement.

The guard reports contract shape only. It never assigns a CTO verdict and never
turns automatically-triggered unrelated CI into a required gate.

Default is report-only. `PR_CONTRACT_GUARD_ENFORCE=1` may enforce the
appropriate shape for the selected report mode.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

COMPACT_REQUIRED_SECTIONS = (
    "Authority / revision",
    "Scope",
    "Implementation evidence",
    "Validation decision",
    "CTO final status",
)

EXTENDED_REQUIRED_SECTIONS = (
    "Authority / revision",
    "Scope",
    "Evidence dimensions",
    "Implementation evidence",
    "Owner-only decisions",
    "Completion checklist",
    "CTO final status",
)

REPORT_MODE_PATTERN = re.compile(r"(?im)^\s*REPORT_MODE\s*=\s*(COMPACT|EXTENDED)\s*$")
SHA_PATTERN = re.compile(r"\b[0-9a-f]{7,40}\b")
ISSUE_LINK_PATTERNS = (
    re.compile(
        r"(?i)\b(?:closes|close|closed|fixes|fix|fixed|resolves|resolve|refs|ref|references|advances|tracks|part of)\b[^\n#]{0,24}#\d+"
    ),
    re.compile(r"#\d{3,}"),
)
STATUS_PATTERN = re.compile(
    r"\b(NOT_REVIEWED|NOT_READY|CONDITIONALLY_READY|READY|READY_FOR_CUSTOMER_HANDOFF)\b"
)
APPROVAL_CLAIM_PATTERN = re.compile(
    r"(?i)(cto[\s_-]*approved|cto[\s_-]*approval|approved by (?:the )?cto|"
    r"cto[\s_-]*review(?:ed)? and approved)"
)


def _has_section(body: str, name: str) -> bool:
    pattern = re.compile(r"^#{1,6}\s*" + re.escape(name) + r"\s*$", re.MULTILINE)
    return bool(pattern.search(body))


def _has_issue_link(body: str) -> bool:
    return any(pattern.search(body) for pattern in ISSUE_LINK_PATTERNS)


def _report_mode(body: str) -> str:
    match = REPORT_MODE_PATTERN.search(body)
    # Backward compatibility for open PRs created before compact mode existed.
    return match.group(1) if match else "EXTENDED"


def audit(body: str | None) -> dict[str, object]:
    """Report contract compliance for one pull request body."""
    text = body or ""
    report_mode = _report_mode(text)
    required_sections = (
        COMPACT_REQUIRED_SECTIONS
        if report_mode == "COMPACT"
        else EXTENDED_REQUIRED_SECTIONS
    )

    present = [name for name in required_sections if _has_section(text, name)]
    missing = [name for name in required_sections if name not in present]

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
        "report_mode": report_mode,
        "required_sections": list(required_sections),
        "present_sections": present,
        "missing_sections": missing,
        "sections_recorded": f"{len(present)}/{len(required_sections)}",
        "revision_identity": "recorded" if has_sha else "MISSING",
        "work_order_link": "recorded" if has_link else "MISSING",
        "cto_status_token": status_token,
        "unrecorded_approval_claim": approval_claim,
        "contract_complete": contract_complete,
        "guard_mode": "report",
        "unrelated_ci_becomes_required": False,
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
        missing = list(report["missing_sections"])
        if report["revision_identity"] == "MISSING":
            missing.append("revision_identity")
        if report["work_order_link"] == "MISSING":
            missing.append("work_order_link")
        print(
            "PR_CONTRACT_GUARD=FAIL missing: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    print("PR_CONTRACT_GUARD=REPORT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
