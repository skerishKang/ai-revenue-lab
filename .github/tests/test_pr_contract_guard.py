from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_guard():
    script = Path(__file__).resolve().parents[1] / "scripts" / "pr_contract_guard.py"
    spec = importlib.util.spec_from_file_location("pr_contract_guard", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPLETE_BODY = """## Authority / revision

- Issue / work order: #1900
- Exact starting base SHA: 18b6164b99aea0b7534064bd37136dc989b0259f
- Branch: feat/engine-resolver
- Exact current head SHA: 9162e1840b1a6f6d2f2a1c4c5b6d7e8f9a0b1c2d
- Product-evidence stage: MVP_VERTICAL_SLICE

## Purpose

Resolve trusted document references without touching routes.

## Scope

- Allowed paths: apps/padiem-ai-engine/app/**

## Evidence dimensions

- Technical implementation: REQUIRED
- Security / privacy: REQUIRED

## Implementation evidence

- Commands/checks run against this head: pytest -q (34 passed)
- Exit/status and pass/fail/skip counts: exit 0, 34 passed
- CI/check runs: Padiem AI Engine CI success

## Independent validation

- Required? yes + reason: production-adjacent security boundary
- Validator actor: pending
- Same actor as implementation? no

## Owner-only decisions

- Required? no

## Risks and limitations

- Known defects: none

## CTO final status

```text
NOT_REVIEWED
```

## Completion checklist

- [ ] Current remote main/head/diff were re-read before final review.
"""


def test_complete_body_reports_no_missing_sections() -> None:
    guard = _load_guard()
    result = guard.audit(COMPLETE_BODY)

    assert result["missing_sections"] == []
    assert result["sections_recorded"] == "7/7"
    assert result["revision_identity"] == "recorded"
    assert result["work_order_link"] == "recorded"
    assert result["cto_status_token"] == "NOT_REVIEWED"
    assert result["contract_complete"] is True
    assert result["unrecorded_approval_claim"] is False


def test_empty_body_reports_every_load_bearing_field_missing() -> None:
    guard = _load_guard()
    result = guard.audit("")

    assert result["pull_request_body_present"] is False
    assert result["missing_sections"] == list(guard.REQUIRED_SECTIONS)
    assert result["revision_identity"] == "MISSING"
    assert result["work_order_link"] == "MISSING"
    assert result["contract_complete"] is False


def test_narrative_body_without_template_fields_is_incomplete() -> None:
    guard = _load_guard()
    body = (
        "## Scope\n\n- resolver only\n\n"
        "## Verification (implementation self-checks)\n\n"
        "- S2 suite: 34 passed\n"
    )
    result = guard.audit(body)

    assert result["missing_sections"] == [
        "Authority / revision",
        "Evidence dimensions",
        "Implementation evidence",
        "Independent validation",
        "Owner-only decisions",
        "Completion checklist",
        "CTO final status",
    ]
    assert result["revision_identity"] == "MISSING"
    assert result["contract_complete"] is False


def test_sha_without_issue_link_is_incomplete() -> None:
    guard = _load_guard()
    body = (
        "## Authority / revision\n\n- Exact current head SHA: 9162e184\n\n"
        "## CTO final status\n\n```text\nREADY\n```\n"
    )
    result = guard.audit(body)

    assert result["revision_identity"] == "recorded"
    assert result["work_order_link"] == "MISSING"
    assert result["contract_complete"] is False


def test_unrecorded_approval_claim_is_detected() -> None:
    guard = _load_guard()
    body = "## Scope\n\nS2 previously CTO-approved; stacked on this DRAFT PR.\n"
    result = guard.audit(body)

    assert result["unrecorded_approval_claim"] is True
    assert result["cto_status_token"] == "MISSING"


def test_recorded_approval_is_not_flagged() -> None:
    guard = _load_guard()
    body = (
        "## Scope\n\nS2 previously CTO-approved.\n\n"
        "## CTO final status\n\n```text\nCONDITIONALLY_READY\n```\n"
    )
    result = guard.audit(body)

    assert result["unrecorded_approval_claim"] is False
    assert result["cto_status_token"] == "CONDITIONALLY_READY"


def test_guard_never_reports_a_review_verdict() -> None:
    guard = _load_guard()
    result = guard.audit(COMPLETE_BODY)

    assert "verdict" not in result
    assert "READY" not in [result["guard_mode"]]
    assert result["guard_mode"] == "report"


def main() -> int:
    test_complete_body_reports_no_missing_sections()
    test_empty_body_reports_every_load_bearing_field_missing()
    test_narrative_body_without_template_fields_is_incomplete()
    test_sha_without_issue_link_is_incomplete()
    test_unrecorded_approval_claim_is_detected()
    test_recorded_approval_is_not_flagged()
    test_guard_never_reports_a_review_verdict()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
