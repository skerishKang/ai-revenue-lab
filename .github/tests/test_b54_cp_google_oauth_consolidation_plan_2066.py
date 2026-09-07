from __future__ import annotations

from pathlib import Path
import re

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CLAW_KAGENT_DIR = REPO_ROOT / "apps" / "korean-ai-code-agent" / "src" / "kagent"
CONTROL_PLANE_DIR = REPO_ROOT / "packages" / "padiem-control-plane"
PLAN_DOC = REPO_ROOT / "docs" / "architecture" / "B54_CP_GOOGLE_OAUTH_CONSOLIDATION_PLAN_2066.md"


def test_consolidation_plan_document_exists_and_contains_required_sections() -> None:
    assert PLAN_DOC.exists(), "Plan doc B54_CP_GOOGLE_OAUTH_CONSOLIDATION_PLAN_2066.md must exist"
    content = PLAN_DOC.read_text(encoding="utf-8")

    # References required issues
    assert "#1908" in content
    assert "#2066" in content

    # Records duplicate authority
    assert "DUPLICATE_AUTHORITY_DETECTED = YES" in content
    assert "SEPARATE_CONSOLIDATION_ISSUE_NEEDED = YES" in content

    # Identifies canonical owners
    required_owners = [
        "GOOGLE_CANONICAL_IDENTITY_AUTHORITY = CONTROL_PLANE",
        "CONNECT_TICKET_ISSUANCE = CONTROL_PLANE",
        "DEVICE_CREDENTIAL_AND_PAIRING_AUTHORITY = CONTROL_PLANE",
        "GMAIL_DRIVE_API_CALL_EXECUTION = CLAW_CONNECTOR_RUNTIME",
        "WINDOWS_LOCAL_EXECUTION = CLAW",
    ]
    norm_content = re.sub(r"\s+", " ", content)
    for owner in required_owners:
        norm_owner = re.sub(r"\s+", " ", owner)
        assert norm_owner in norm_content, f"Missing ownership specification: {owner}"

    # Reasserts no mutation in ACT-0
    required_freeze = [
        "PROVIDER_CALLS = 0",
        "OAUTH_FLOW_EXECUTION = 0",
        "CREDENTIAL_READS = 0",
        "SECRET_WRITES = 0",
        "STORAGE_MUTATION = 0",
        "PRODUCTION_MUTATION = 0",
    ]
    for freeze in required_freeze:
        assert freeze in content, f"Missing freeze assertion: {freeze}"

    # Does not claim consolidation has already been performed
    assert ("Consolidation is NOT performed in ACT-0" in content or "Consolidation is **NOT** performed in ACT-0" in content)
    assert ("Existing code is NOT refactored or deleted in ACT-0" in content or "Existing code is **NOT** refactored or deleted in ACT-0" in content)

    # Check for corruption: no ASCII control characters other than \t, \n, \r
    raw_bytes = PLAN_DOC.read_bytes()
    bad_control_chars = [b for b in raw_bytes if b < 32 and b not in (9, 10, 13)]
    assert not bad_control_chars, f"Plan doc contains control characters: {bad_control_chars}"

    # Check for path sanity
    assert "apps/korean-ai-code-agent/src/kagent/" in content
    assert not re.search(r"(?<![a-zA-Z0-9_-])pps/korean-ai-code-agent", content), (
        "Plan doc contains corrupted pps/ path without leading a"
    )

    # Check for dangling backticks or malformed code fences
    lines = content.splitlines()
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    assert non_empty_lines, "Plan doc must not be empty"
    last_line = non_empty_lines[-1]
    assert last_line != "`", "Plan doc must not end with a dangling single backtick"
    assert not last_line.startswith("`") or last_line.startswith("```"), (
        f"Plan doc ending line has malformed backtick: {last_line}"
    )

    # Markdown fence parity check: all code fences must properly open and close
    fence_matches = [line.strip() for line in lines if line.strip().startswith("```")]
    assert len(fence_matches) % 2 == 0, (
        f"Unbalanced markdown code fences (count: {len(fence_matches)}): {fence_matches}"
    )

    # Verify no dangling single-backtick-only lines anywhere in the document
    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        assert stripped != "`", f"Dangling single backtick on line {idx}: {line}"
        assert stripped != "``", f"Dangling double backtick on line {idx}: {line}"
        assert not re.match(r"^`[a-zA-Z0-9_-]+$", stripped), (
            f"Malformed fence opening on line {idx}: {line}"
        )

