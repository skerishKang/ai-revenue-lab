from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "apps" / "padiem-chat" / "static"
QA = ROOT / ".github" / "scripts" / "b62_post_certification_browser_qa.py"
WORKFLOW = ROOT / ".github" / "workflows" / "b62-browser-visual-qa.yml"


def test_long_answer_browser_qa_proves_no_client_truncation_contract() -> None:
    source = QA.read_text(encoding="utf-8")
    assert "len(answer) < 6000" in source
    assert '"LONG_ANSWER_END_SENTINEL_1887"' in source
    assert 'raw_dom != LONG_ANSWER' in source
    assert 'copied != LONG_ANSWER' in source
    assert 'downloaded != LONG_ANSWER' in source
    assert '"client_side_truncation"] = 0' in source
    assert '"max_tokens"' in source
    assert "browser asserted hidden execution authority" in source


def test_long_answer_browser_qa_covers_rich_response_and_workspace_geometry() -> None:
    source = QA.read_text(encoding="utf-8")
    for marker in (
        ".rich-code-block",
        'locator("table")',
        ".rich-response-heading",
        "conversation_box[\"width\"] < 1000",
        "conversation/composer width drift",
        "wide rich surface did not exceed prose measure",
        "horizontal overflow",
    ):
        assert marker in source


def test_multiline_composer_and_visual_viewport_contract_is_bounded() -> None:
    source = (STATIC / "interaction-polish.js").read_text(encoding="utf-8")
    css = (STATIC / "interaction-polish.css").read_text(encoding="utf-8")
    assert "COMPOSER_MIN_HEIGHT = 50" in source
    assert "COMPOSER_MAX_HEIGHT = 180" in source
    assert 'input.style.height = "auto"' in source
    assert "input.scrollHeight" in source
    assert "window.visualViewport" in source
    assert "visualKeyboardInset" in source
    assert '"--padiem-visual-keyboard-inset"' in source
    assert "bottom: var(--padiem-visual-keyboard-inset, 0px) !important" in css


def test_large_desktop_glass_lane_is_content_first_but_prose_stays_bounded() -> None:
    css = (STATIC / "padiem-glass-gutter-alignment.css").read_text(encoding="utf-8")
    assert "--padiem-chat-reading-measure: 76ch" in css
    assert "@media (min-width: 1440px)" in css
    assert "--padiem-chat-lane-offset: clamp(36px, 3vw, 56px)" in css
    assert "1080px" in css
    assert "clamp(300px, 24vw, 430px)" in css
    assert ".rich-response-paragraph" in css
    assert "max-inline-size: min(var(--padiem-chat-reading-measure), 100%)" in css


def test_visual_workflow_runs_post_certification_gate_and_uploads_report() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert ".github/scripts/b62_post_certification_browser_qa.py" in workflow
    assert "Post-certification long-answer and mobile hardening QA" in workflow
    assert "post-certification-hardening-report.json" in workflow
