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

# R5 0단계(R-01): 함수 경계는 app.js든 분리 모듈이든 같은 도우미로 찾는다.
from _r5_function_source import combined_source

STATIC = Path(__file__).resolve().parents[1] / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")


def _logout_block() -> str:
    session = (STATIC / "claw-session.js").read_text(encoding="utf-8")
    assert "window.PadiemClawSession.bind({" in APP_JS
    start = session.index("if (authenticated) return;")
    # The same signed-out cleanup lives in the session listener after R1.
    end = session.index("window.PadiemClawPdfPreview?.revokeAll?.()", start)
    return session[start:end]


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
    shipped = combined_source()
    start = shipped.index("async function loadApprovedMemoryDetail")
    end = shipped.index("function syncApprovedMemoryVisibility", start)
    body = shipped[start:end]
    assert "renderApprovedMemoryDetail(data.memory)" in body
    assert "clawApprovedDisclosure) clawApprovedDisclosure.open = true" in body


def test_both_disclosures_stay_outside_the_approval_surface() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for did in ("clawApprovedDisclosure", "clawRunHistoryDisclosure"):
        start = html.index(f'id="{did}"')
        end = html.index("</details>", start)
        assert "clawApprovalActions" not in html[start:end]
