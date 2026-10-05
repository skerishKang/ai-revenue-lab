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


COMPACT_BODY = """# Change mode

REPORT_MODE=COMPACT
DELIVERY_MODE=NORMAL
TEST_CLASS=T1

## Authority / revision

- Issue / work order: #3521
- Exact starting base SHA: 3b8e4c4d0dc7b18a5d30803cc8456620cf4038dd
- Branch: fix/bounded-worker-composition
- Exact current head SHA: 9162e1840b1a6f6d2f2a1c4c5b6d7e8f9a0b1c2d

## Scope

- Exact changed files: worker.py + one focused test
- Explicit non-goals: no UI/browser rewrite

## Implementation evidence

- Focused load-bearing regression: PASS
- Relevant configured CI: PASS
- Observational/non-blocking CI: not waited

## Validation decision

- Independent validation: NOT_REQUIRED
- Reason: deterministic composition regression + relevant CI

## CTO final status

```text
NOT_REVIEWED
```
"""


EXTENDED_BODY = """# Change mode

REPORT_MODE=EXTENDED
DELIVERY_MODE=NORMAL
TEST_CLASS=T3

## Authority / revision

- Issue / work order: #1900
- Exact starting base SHA: 18b6164b99aea0b7534064bd37136dc989b0259f
- Branch: feat/engine-resolver
- Exact current head SHA: 9162e1840b1a6f6d2f2a1c4c5b6d7e8f9a0b1c2d

## Scope

- Allowed paths: apps/padiem-ai-engine/app/**

## Evidence dimensions

- Technical implementation: REQUIRED
- Security / privacy: REQUIRED

## Implementation evidence

- Commands/checks run against this head: pytest -q (34 passed)
- CI/check runs: Padiem AI Engine CI success

## Owner-only decisions

- Required? no

## CTO final status

```text
NOT_REVIEWED
```

## Completion checklist

- [ ] Current remote main/head/diff were re-read before final review.
"""


def test_compact_body_is_complete_without_extended_ceremony() -> None:
    guard = _load_guard()
    result = guard.audit(COMPACT_BODY)

    assert result["report_mode"] == "COMPACT"
    assert result["missing_sections"] == []
    assert result["sections_recorded"] == "5/5"
    assert result["revision_identity"] == "recorded"
    assert result["work_order_link"] == "recorded"
    assert result["contract_complete"] is True
    assert result["unrelated_ci_becomes_required"] is False


def test_extended_body_uses_extended_contract() -> None:
    guard = _load_guard()
    result = guard.audit(EXTENDED_BODY)

    assert result["report_mode"] == "EXTENDED"
    assert result["missing_sections"] == []
    assert result["sections_recorded"] == "7/7"
    assert result["contract_complete"] is True


def test_legacy_body_without_mode_defaults_to_extended() -> None:
    guard = _load_guard()
    body = EXTENDED_BODY.replace("REPORT_MODE=EXTENDED\n", "")
    result = guard.audit(body)
    assert result["report_mode"] == "EXTENDED"
    assert result["contract_complete"] is True


def test_compact_does_not_require_independent_validation_section() -> None:
    guard = _load_guard()
    result = guard.audit(COMPACT_BODY)
    assert "Independent validation" not in result["required_sections"]
    assert "Evidence dimensions" not in result["required_sections"]
    assert "Owner-only decisions" not in result["required_sections"]
    assert "Completion checklist" not in result["required_sections"]


def test_empty_body_is_incomplete() -> None:
    guard = _load_guard()
    result = guard.audit("")
    assert result["pull_request_body_present"] is False
    assert result["contract_complete"] is False


def test_sha_without_issue_link_is_incomplete() -> None:
    guard = _load_guard()
    body = """# Change mode
REPORT_MODE=COMPACT
## Authority / revision
- Exact current head SHA: 9162e184
## Scope
- files: worker.py
## Implementation evidence
- focused: PASS
## Validation decision
- Independent validation: NOT_REQUIRED
## CTO final status
NOT_REVIEWED
"""
    result = guard.audit(body)
    assert result["revision_identity"] == "recorded"
    assert result["work_order_link"] == "MISSING"
    assert result["contract_complete"] is False


def test_ready_for_customer_handoff_is_recognized() -> None:
    guard = _load_guard()
    body = COMPACT_BODY.replace("NOT_REVIEWED", "READY_FOR_CUSTOMER_HANDOFF")
    result = guard.audit(body)
    assert result["cto_status_token"] == "READY_FOR_CUSTOMER_HANDOFF"


def test_unrecorded_approval_claim_is_detected() -> None:
    guard = _load_guard()
    body = "## Scope\n\nS2 previously CTO-approved; stacked on this DRAFT PR.\n"
    result = guard.audit(body)
    assert result["unrecorded_approval_claim"] is True


def test_guard_never_assigns_a_review_verdict() -> None:
    guard = _load_guard()
    result = guard.audit(COMPACT_BODY)
    assert "verdict" not in result
    assert result["guard_mode"] == "report"


def main() -> int:
    test_compact_body_is_complete_without_extended_ceremony()
    test_extended_body_uses_extended_contract()
    test_legacy_body_without_mode_defaults_to_extended()
    test_compact_does_not_require_independent_validation_section()
    test_empty_body_is_incomplete()
    test_sha_without_issue_link_is_incomplete()
    test_ready_for_customer_handoff_is_recognized()
    test_unrecorded_approval_claim_is_detected()
    test_guard_never_assigns_a_review_verdict()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
