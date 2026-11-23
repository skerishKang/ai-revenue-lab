# #8060: shipped reads live in _support; the CSS and QA-script checks stay.
from _support import chat_rhythm_source as sheets

ALIGNMENT_CSS = sheets.sheet("padiem-glass-gutter-alignment.css")
GUTTER_QA = sheets.repo_source(".github/scripts/b62_chat_gutter_visual_qa.py")
VISUAL_WORKFLOW = sheets.repo_source(".github/workflows/b62-browser-qa-unified.yml")
VISUAL_TAIL = sheets.repo_source(".github/scripts/b62_browser_qa_tail_parallel.py")


def test_1423_assistant_response_and_error_have_bounded_widths() -> None:
    assert "--padiem-chat-reading-measure: 76ch;" in ALIGNMENT_CSS
    # #8008 8차: 값만 단정한다. 중요도 캡은 계산값을 바꾸지 않는 구현 detail.
    assert ".assistant-content {\n  width: 100%;\n  max-width: none;" in ALIGNMENT_CSS
    assert '.assistant-content > .rich-response {' in ALIGNMENT_CSS
    assert '.assistant-content > .error-box {' in ALIGNMENT_CSS
    assert "width: calc(100% - 32px - var(--padiem-chat-meta-gap));" in ALIGNMENT_CSS
    assert ".rich-response-paragraph," in ALIGNMENT_CSS
    assert "max-inline-size: min(var(--padiem-chat-reading-measure), 100%);" in ALIGNMENT_CSS
    assert ".rich-code-block," not in ALIGNMENT_CSS
    assert ".rich-table-block," not in ALIGNMENT_CSS


def test_1424_user_bubble_anchors_to_shared_right_edge_without_full_width() -> None:
    # #8008: the importance caps are gone from the user-turn rules; the values
    # are unchanged and the winners are decided by specificity.
    assert ".user-message {\n  width: calc(100% + var(--padiem-chat-inner-gutter));" in ALIGNMENT_CSS
    assert "padding-left: clamp(36px, 8vw, 96px);" in ALIGNMENT_CSS
    assert ".user-message .message-bubble {\n  margin-left: auto;\n  max-width: min(660px, 88%);" in ALIGNMENT_CSS
    assert "max-width: min(620px, 92%);" in ALIGNMENT_CSS


def test_1425_avatar_meta_remains_internal_and_gap_is_tighter() -> None:
    assert "--padiem-chat-meta-gap: 12px;" in ALIGNMENT_CSS
    assert "grid-template-columns: 32px minmax(0, 1fr);" in ALIGNMENT_CSS
    assert "gap: var(--padiem-chat-meta-gap);" in ALIGNMENT_CSS
    assert ".assistant-meta {\n  margin-bottom: 6px;" in ALIGNMENT_CSS
    assert "--padiem-chat-meta-gap: 10px;" in ALIGNMENT_CSS
    assert "display: none" not in ALIGNMENT_CSS


def test_1427_responsive_qa_covers_desktop_tablet_and_mobile() -> None:
    for viewport in (
        '("desktop-1920", 1920, 1080)',
        '("compact-1280", 1280, 720)',
        '("tablet-landscape-960", 960, 768)',
        '("tablet-portrait-768", 768, 1024)',
        '("mobile-390", 390, 844)',
    ):
        assert viewport in GUTTER_QA
    # #4783 (edbbe75811e) + #4726 (b9ade4b9ed9): the user row and the wide
    # rich-answer surface share one right boundary, which is the contract this
    # marker guards. The older "user bubble right" wording no longer exists in
    # the corrected probe.
    assert "user row and wide answer share one right boundary" in GUTTER_QA
    assert "assistant meta/content gap out of range" in GUTTER_QA
    assert "horizontal overflow" in GUTTER_QA
    # The #3989 unified workflow invokes the bounded visual-tail runner;
    # gutter QA remains mandatory inside its fail-closed SCRIPTS contract.
    assert ".github/scripts/b62_browser_qa_tail_parallel.py" in VISUAL_WORKFLOW
    assert '"b62_chat_gutter_visual_qa.py"' in VISUAL_TAIL
    assert "B62_VISUAL_TAIL_FAIL_COUNT" in VISUAL_TAIL
    assert "shared-gutter-report.json" in VISUAL_WORKFLOW


def test_child_polish_remains_layout_only() -> None:
    for forbidden in (
        "fetch(",
        "Authorization",
        "localStorage",
        "sessionStorage",
        "overflow-x: hidden",
    ):
        assert forbidden not in ALIGNMENT_CSS
