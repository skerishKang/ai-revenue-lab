from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"


def test_b62_browser_qa_does_not_fan_out_for_tests_or_worker_entrypoint_only() -> None:
    """Browser QA should follow browser/runtime surfaces, not every Chat file.

    The B62 browser workflows run the ASGI app via uvicorn, not the Cloudflare
    Worker entrypoint. Test-file-only changes also cannot affect the rendered
    product. If a browser workflow keeps the broad apps/padiem-chat/** trigger,
    it must explicitly exclude those two non-browser surfaces.
    """

    browser_workflows = sorted(WORKFLOWS.glob("b62-*-browser-qa.yml"))
    assert browser_workflows, "expected B62 browser QA workflows"

    for path in browser_workflows:
        text = path.read_text(encoding="utf-8")
        if 'apps/padiem-chat/**' not in text:
            continue
        assert '!apps/padiem-chat/tests/**' in text, (
            f"{path.name} broadly watches apps/padiem-chat/** but does not "
            "exclude tests-only changes"
        )
        assert '!apps/padiem-chat/worker.py' in text, (
            f"{path.name} broadly watches apps/padiem-chat/** but does not "
            "exclude the Cloudflare Worker entrypoint that this browser QA "
            "does not execute"
        )


def test_repository_wide_test_scope_policy_is_canonical() -> None:
    policy = REPO / "docs" / "operations" / "TEST_SCOPE_AND_DELIVERY_POLICY.md"
    text = policy.read_text(encoding="utf-8")
    assert "CANONICAL REPOSITORY-WIDE POLICY" in text
    assert "TEST_COUNT != CONFIDENCE" in text
    assert "OBSERVATIONAL_NONBLOCKING_CHECK" in text
    assert "AUTOMATIC_WHOLE_REPOSITORY_SUITE=NO" in text
