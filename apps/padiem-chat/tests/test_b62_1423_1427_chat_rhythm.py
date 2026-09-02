from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
ALIGNMENT_CSS = (ROOT / "static/padiem-glass-gutter-alignment.css").read_text(encoding="utf-8")
GUTTER_QA = (REPO_ROOT / ".github/scripts/b62_chat_gutter_visual_qa.py").read_text(encoding="utf-8")
VISUAL_WORKFLOW = (REPO_ROOT / ".github/workflows/b62-browser-visual-qa.yml").read_text(encoding="utf-8")


def test_1423_outer_surfaces_stay_wide_while_prose_has_readable_measure() -> None:
    assert "--padiem-chat-reading-measure: 76ch;" in ALIGNMENT_CSS
    assert ".assistant-content {\n  width: 100% !important;\n  max-width: none !important;" in ALIGNMENT_CSS
    assert ".error-box {\n  width: 100% !important;\n  max-width: none !important;" in ALIGNMENT_CSS
    assert ".rich-response-paragraph," in ALIGNMENT_CSS
    assert "max-inline-size: min(var(--padiem-chat-reading-measure), 100%);" in ALIGNMENT_CSS
    # Wide structured surfaces are intentionally not put behind the prose measure.
    assert ".rich-code-block," not in ALIGNMENT_CSS
    assert ".rich-table-block," not in ALIGNMENT_CSS


def test_1424_user_bubble_anchors_to_shared_right_edge_without_full_width() -> None:
    assert ".user-message {\n  width: calc(100% + var(--padiem-chat-inner-gutter)) !important;" in ALIGNMENT_CSS
    assert "padding-left: clamp(36px, 8vw, 96px) !important;" in ALIGNMENT_CSS
    assert ".user-message .message-bubble {\n  margin-left: auto !important;\n  max-width: min(660px, 88%) !important;" in ALIGNMENT_CSS
    assert "max-width: min(620px, 92%) !important;" in ALIGNMENT_CSS


def test_1425_avatar_meta_remains_internal_and_gap_is_tighter() -> None:
    assert "--padiem-chat-meta-gap: 12px;" in ALIGNMENT_CSS
    assert ".assistant-message {\n  gap: var(--padiem-chat-meta-gap) !important;" in ALIGNMENT_CSS
    assert ".assistant-meta {\n  margin-bottom: 6px !important;" in ALIGNMENT_CSS
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
    assert "user bubble right" in GUTTER_QA
    assert "assistant meta/content gap out of range" in GUTTER_QA
    assert "horizontal overflow" in GUTTER_QA
    assert ".github/scripts/b62_chat_gutter_visual_qa.py" in VISUAL_WORKFLOW
    assert "Shared gutter responsive browser QA" in VISUAL_WORKFLOW


def test_child_polish_remains_layout_only() -> None:
    for forbidden in (
        "fetch(",
        "Authorization",
        "localStorage",
        "sessionStorage",
        "overflow-x: hidden",
    ):
        assert forbidden not in ALIGNMENT_CSS
