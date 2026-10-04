from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    ROOT / ".github/workflows/b62-padiem-chat-ci.yml",
    ROOT / ".github/workflows/validate-b54-kagent.yml",
    ROOT / ".github/workflows/b62-browser-visual-qa.yml",
    ROOT / ".github/workflows/b62-accessibility-browser-qa.yml",
)

DRAFT_GATE = (
    "github.event_name == 'workflow_dispatch' || "
    "github.event.pull_request.draft == false"
)


def test_expensive_validation_waits_for_ready_for_review_and_cancels_superseded_heads() -> None:
    for workflow in WORKFLOWS:
        source = workflow.read_text(encoding="utf-8")
        assert "types: [opened, synchronize, reopened, ready_for_review]" in source
        assert "cancel-in-progress: true" in source
        assert "${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}" in source
        assert DRAFT_GATE in source


def test_accessibility_lane_does_not_repeat_the_full_b62_regression_suite() -> None:
    source = (ROOT / ".github/workflows/b62-accessibility-browser-qa.yml").read_text(
        encoding="utf-8"
    )
    assert "Run B62 regression suite" not in source
    assert "uv run pytest -q" not in source
    assert "uv run python -m compileall -q app worker.py" in source
