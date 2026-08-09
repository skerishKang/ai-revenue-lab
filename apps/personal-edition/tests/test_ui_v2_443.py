"""Issue #454 regression contracts for the Personal Edition V3 art-direction reset.

The filename is retained to avoid breaking historical CI references, but V2 visual
assertions are deliberately removed: #454 explicitly rejects the V2 art direction.
"""
from __future__ import annotations

from pathlib import Path
import pytest
from scripts.build_static_preview import main as build_main

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "dist-preview"
V3_CSS = BASE_DIR / "static" / "ui-v3-454.css"

@pytest.fixture(scope="module", autouse=True)
def _build_preview() -> None:
    build_main()

def _html(rel: str) -> str:
    return (OUTPUT_DIR / rel).read_text(encoding="utf-8")

def test_v3_stylesheet_replaces_v2_shell() -> None:
    base = (BASE_DIR / "templates" / "base.html").read_text(encoding="utf-8")
    assert '/static/ui-v3-454.css?v=b1-v3-454' in base
    assert 'data-ui-version="b1-personal-edition-v3-454"' in base
    assert '/static/ui-v2-443.css' not in base
    assert (OUTPUT_DIR / "static" / "ui-v3-454.css").is_file()

def test_entry_is_a_new_assembly_art_direction_not_v2_split_shell() -> None:
    page = _html("preview/intro/index.html")
    assert "v3-assembly-stage" in page
    assert "v3-binding-axis" in page
    assert "v3-edition-object" in page
    assert "gather → sort → bind → reveal" in page
    assert "intro-page-v2" not in page
    assert "fragment-stage-v2" not in page
    assert "bound-edition-v2" not in page

def test_canonical_root_is_product_first_not_preview_index() -> None:
    template = (BASE_DIR / "templates" / "preview_index.html").read_text(encoding="utf-8")
    assert "data-owner-review-root" in template
    assert "Personal Edition UI Preview" not in template
    assert "프리뷰 목록" not in template
    assert ".preview-banner { display:none !important; }" in template
    root = _html("index.html")
    assert "v3-assembly-stage" in root
    assert "data-owner-review-root" in root

def test_participant_core_routes_share_one_v3_system() -> None:
    expected = {
        "preview/participant/published/index.html": "v3-library",
        "preview/participant/input/index.html": "v3-write",
        "preview/participant/editions/modal-preview-edition/index.html": "v3-read",
        "preview/participant/editions/modal-preview-edition/feedback/index.html": "v3-feedback",
        "preview/participant/editions/modal-preview-edition/adaptation/index.html": "v3-adaptation",
        "preview/participant/history/index.html": "v3-history",
    }
    for path, marker in expected.items():
        assert marker in _html(path), (path, marker)

def test_writing_surface_makes_textarea_the_primary_interaction() -> None:
    page = _html("preview/participant/input/index.html")
    assert "v3-write-desk" in page
    assert "v3-write-form" in page
    assert 'id="raw_text"' in page
    assert "editorial-process-layers.webp" not in page
    assert "편집 시스템에 맡기기" in page

def test_library_uses_collectible_sequence_not_crud_grid_or_stepper_centerpiece() -> None:
    page = _html("preview/participant/published/index.html")
    assert "v3-library-stage" in page
    assert "v3-library-cover" in page
    assert "v3-spines" in page
    assert "latest-edition" in page
    assert "progress-track" not in page
    assert "published-spread-v2" not in page

def test_edition_read_has_collectible_cover_and_long_form_rhythm() -> None:
    page = _html("preview/participant/editions/modal-preview-edition/index.html")
    assert "v3-read-opening" in page
    assert "v3-reading-shell" in page
    assert "v3-reading-main" in page
    assert 'class="edition-cover v3-read-cover"' in page
    assert "제1호" in page
    assert "/preview/participant/editions/modal-preview-edition/feedback" in page

def test_feedback_and_adaptation_are_editorial_direction_and_recut() -> None:
    feedback = _html("preview/participant/editions/modal-preview-edition/feedback/index.html")
    assert "v3-directions" in feedback
    assert "편집자에게 남길 문장" in feedback
    adaptation = _html("preview/participant/editions/modal-preview-edition/adaptation/index.html")
    assert "v3-recut-stage" in adaptation
    assert "Reader direction" in adaptation
    assert "Before · Edition 01" in adaptation
    assert "After · next edition" in adaptation
    assert "변경된 이유" in adaptation
    assert "고객마다 원하는 속도와 방식이 다르다는 것을 깨달았습니다" in adaptation

def test_participant_art_direction_uses_no_decorative_raster_photos() -> None:
    for name in ["intro.html", "participant_dashboard.html", "input_form.html", "edition_read.html", "participant_history.html"]:
        source = (BASE_DIR / "templates" / name).read_text(encoding="utf-8")
        assert ".webp" not in source, name
        assert "<img" not in source, name

def test_operator_queue_remains_responsive_and_human_reviewed() -> None:
    page = _html("admin/index.html")
    assert "operator-queue-list-v2" in page
    assert "operator-queue-item-v2" in page
    assert "Private workspace" in page
    assert "Human review required" in page
    assert 'class="data-table queue-table"' not in page

def test_v3_css_has_spatial_motion_and_three_scale_responsiveness() -> None:
    css = V3_CSS.read_text(encoding="utf-8")
    assert "@keyframes v3-bind" in css
    assert "@keyframes v3-gather-1" in css
    assert ".v3-binding-axis" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 600px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css

def test_v3_css_keeps_focus_and_no_external_dependency() -> None:
    css = V3_CSS.read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "outline: 3px solid var(--v3-signal)" in css
    assert "http://" not in css
    assert "https://" not in css
    assert "@import" not in css
    assert "url(" not in css

def test_v3_does_not_claim_owner_approval() -> None:
    paths = [
        BASE_DIR / "templates" / "base.html",
        BASE_DIR / "templates" / "intro.html",
        BASE_DIR / "templates" / "participant_dashboard.html",
        BASE_DIR / "templates" / "input_form.html",
        BASE_DIR / "templates" / "edition_read.html",
        BASE_DIR / "templates" / "feedback_form.html",
        BASE_DIR / "templates" / "feedback_adaptation.html",
        V3_CSS,
    ]
    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert "OWNER_UI_APPROVED=true" not in content
