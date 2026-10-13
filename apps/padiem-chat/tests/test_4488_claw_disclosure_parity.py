"""#4488 final QA — approved-memory disclosure parity guards (CLAW2).

Two real-browser reproductions from exact main ``88f2ccc5``:

1. Logout left ``#clawApprovedDisclosure`` open while ``#clawRunHistoryDisclosure``
   was hidden+cleared — the approved-memory wrapper must not outlive the session.
2. Opening an approved-memory detail never opened its ``<details>`` wrapper,
   while the run-history focus path did — the detail must be visible.

These guards bind the source contract (no browser needed): the logout cleanup
block must hide+close+clear the approved-memory surface exactly like the
run-history surface, and ``loadApprovedMemoryDetail`` must open the disclosure.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")


def _logout_block() -> str:
    start = APP_JS.index("if (!authenticated) {")
    # The logout cleanup block ends at the auth-loss PDF/timer teardown.
    end = APP_JS.index("window.PadiemClawPdfPreview?.revokeAll?.()", start)
    return APP_JS[start:end]


def test_logout_hides_and_closes_the_approved_memory_disclosure() -> None:
    block = _logout_block()
    assert 'getElementById("clawApprovedDisclosure")' in block
    assert re.search(r"approvedDisclosure\) \{\s*\n?.*approvedDisclosure\.hidden = true", block)
    assert "approvedDisclosure.open = false" in block


def test_logout_clears_the_approved_memory_list_and_error() -> None:
    block = _logout_block()
    assert 'getElementById("clawApprovedList")' in block
    assert "approvedList) approvedList.replaceChildren()" in block
    assert 'getElementById("clawApprovedError")' in block


def test_memory_detail_opens_its_disclosure_like_run_history_focus() -> None:
    start = APP_JS.index("async function loadApprovedMemoryDetail")
    end = APP_JS.index("function syncApprovedMemoryVisibility", start)
    body = APP_JS[start:end]
    assert "renderApprovedMemoryDetail(data.memory)" in body
    assert "clawApprovedDisclosure) clawApprovedDisclosure.open = true" in body


def test_both_disclosures_stay_outside_the_approval_surface() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for did in ("clawApprovedDisclosure", "clawRunHistoryDisclosure"):
        start = html.index(f'id="{did}"')
        end = html.index("</details>", start)
        assert "clawApprovalActions" not in html[start:end]
