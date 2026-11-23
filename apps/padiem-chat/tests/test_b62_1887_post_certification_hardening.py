# #8060: shipped reads live in _support; the source and workflow checks stay.
from _support import post_certification_hardening_source as sheets


def test_long_answer_browser_qa_proves_no_client_truncation_contract() -> None:
    source = sheets.qa_script()
    assert "len(answer) < 6000" in source
    assert '"LONG_ANSWER_END_SENTINEL_1887"' in source
    assert 'raw_dom != LONG_ANSWER' in source
    assert 'copied != LONG_ANSWER' in source
    assert 'downloaded != LONG_ANSWER' in source
    assert '"client_side_truncation"] = 0' in source
    assert '"max_tokens"' in source
    assert "browser asserted hidden execution authority" in source


def test_long_answer_browser_qa_covers_rich_response_and_workspace_geometry() -> None:
    source = sheets.qa_script()
    for marker in (
        ".rich-code-block",
        'locator("table")',
        ".rich-response-heading",
        # #4783 (edbbe75811e) replaced the fixed lane with a rail-aware clamp;
        # #5661 (2026-10-24) capped the lane at 960px. The composer stays a
        # deliberate inner inset of the reading lane, so the measured invariants
        # below keep guarding that design.
        'abs(conversation_box["width"] - 960) > 1',
        "composer is not the designed inner inset of the lane",
        "conversation/composer left gutter is not the designed inset",
        "composer right inset left the designed frame",
        "wide rich surface did not exceed prose measure",
        "horizontal overflow",
    ):
        assert marker in source


def test_multiline_composer_and_visual_viewport_contract_is_bounded() -> None:
    source = sheets.sheet("interaction-polish.js")
    css = sheets.sheet("interaction-polish.css")
    assert "COMPOSER_MIN_HEIGHT = 50" in source
    assert "COMPOSER_MAX_HEIGHT = 180" in source
    assert 'input.style.height = "auto"' in source
    assert "input.scrollHeight" in source
    assert "window.visualViewport" in source
    assert "visualKeyboardInset" in source
    assert '"--padiem-visual-keyboard-inset"' in source
    assert "bottom: var(--padiem-visual-keyboard-inset, 0px) !important" in css


def test_large_desktop_glass_lane_does_not_jump_on_first_message() -> None:
    css = sheets.sheet("padiem-glass-gutter-alignment.css")
    assert "--padiem-chat-reading-measure: 76ch" in css
    assert "FIRST SCREEN = ACTIVE CHAT FRAME" in css
    assert "--padiem-chat-lane-offset:" not in css
    assert "--padiem-chat-lane-width:" not in css
    assert ".rich-response-paragraph" in css
    assert "max-inline-size: min(var(--padiem-chat-reading-measure), 100%)" in css


def test_visual_workflow_runs_post_certification_gate_and_uploads_report() -> None:
    workflow = sheets.workflow()
    assert ".github/scripts/b62_post_certification_browser_qa.py" in workflow
    assert "Post-certification long-answer and mobile hardening QA" in workflow
    assert "post-certification-hardening-report.json" in workflow
