"""Issue #443 regression tests for the Personal Edition UI V2 shell.

These tests intentionally stay inside the static-preview boundary: they assert
visual-system contracts and deterministic rendered states without touching
backend, auth, database or production services.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.build_static_preview import main as build_main

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "dist-preview"
V2_CSS = BASE_DIR / "static" / "ui-v2-443.css"


@pytest.fixture(scope="module", autouse=True)
def _build_preview() -> None:
    build_main()


def _html(rel: str) -> str:
    return (OUTPUT_DIR / rel).read_text(encoding="utf-8")


def test_v2_stylesheet_is_local_linked_and_copied() -> None:
    base = (BASE_DIR / "templates" / "base.html").read_text(encoding="utf-8")
    assert '/static/ui-v2-443.css?v=b1-v2-443' in base
    assert 'data-ui-version="b1-personal-edition-v2-443"' in base
    assert (OUTPUT_DIR / "static" / "ui-v2-443.css").is_file()


def test_entry_is_full_viewport_publication_not_legacy_card_explainer() -> None:
    page = _html("preview/intro/index.html")
    assert "intro-hero-v2" in page
    assert "fragment-stage-v2" in page
    assert "bound-edition-v2" in page
    assert "intro-ledger-v2" in page
    assert 'class="hero-section"' not in page
    assert 'class="transformation-step"' not in page


def test_entry_keeps_preview_participant_route_contract() -> None:
    page = _html("preview/intro/index.html")
    assert "/preview/participant/access/" in page
    assert "에디션 시작하기" in page


def test_published_home_is_private_library_spread() -> None:
    page = _html("preview/participant/published/index.html")
    assert "published-home-v2" in page
    assert "published-spread-v2" in page
    assert "edition-object-v2" in page
    assert "속도에서 개인화로" in page
    assert "/preview/participant/editions/modal-preview-edition" in page


def test_edition_reader_has_opening_spread_and_reading_body() -> None:
    page = _html("preview/participant/editions/modal-preview-edition/index.html")
    assert "edition-opening-spread-v2" in page
    assert "edition-reading-body-v2" in page
    assert "section-copy-v2" in page
    assert "제1호" in page
    assert "/preview/participant/editions/modal-preview-edition/feedback" in page


def test_feedback_adaptation_is_concrete_before_after() -> None:
    page = _html("preview/participant/editions/modal-preview-edition/adaptation/index.html")
    assert "adaptation-delta-v2" in page
    assert "Before · 제1호" in page
    assert "After · next edition" in page
    assert "변경된 이유" in page
    assert "개인화가 구체적으로 어떻게 실천되는지 더 깊이 알고 싶습니다" in page
    assert "고객마다 원하는 속도와 방식이 다르다는 것을 깨달았습니다" in page


def test_operator_queue_uses_responsive_records_not_wide_table() -> None:
    page = _html("admin/index.html")
    assert "operator-shell-v2" in page
    assert "operator-queue-list-v2" in page
    assert "operator-queue-item-v2" in page
    assert 'class="data-table queue-table"' not in page
    assert "/admin/participants/modal-preview-user/" in page
    assert "/admin/review/modal-preview-edition" in page


def test_operator_content_review_has_manuscript_and_inspector() -> None:
    page = _html("admin/review/modal-preview-edition/content/index.html")
    assert "review-desk-v2" in page
    assert "review-manuscript-v2" in page
    assert "review-inspector-v2" in page
    assert "속도에서 개인화로" in page
    assert "more_reflective" in page
    assert "/admin/review/modal-preview-edition/publish/" in page


def test_publish_gate_keeps_preview_only_human_decision_semantics() -> None:
    page = _html("admin/review/modal-preview-edition/publish/index.html")
    assert "Final editorial gate" in page
    assert "Human decision required" in page
    assert "실제 발행은 수행되지 않습니다" in page
    assert "실제 반려는 수행되지 않습니다" in page
    assert "/admin/participants/modal-preview-user/feedback/" in page


def test_v2_css_breaks_out_of_legacy_680px_shell() -> None:
    css = V2_CSS.read_text(encoding="utf-8")
    assert ".participant-surface .container" in css
    assert "max-width: none" in css
    assert "min-height: calc(100svh - 64px)" in css
    assert "font-size: clamp(4.1rem" in css


def test_v2_css_has_three_scale_responsive_rules() -> None:
    css = V2_CSS.read_text(encoding="utf-8")
    assert "@media (max-width: 1100px)" in css
    assert "@media (max-width: 820px)" in css
    assert "@media (max-width: 600px)" in css
    assert ".operator-queue-item-v2 { grid-template-columns: 1fr;" in css


def test_v2_css_preserves_keyboard_focus_and_reduced_motion() -> None:
    css = V2_CSS.read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "outline: 3px solid var(--v2-accent)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "animation: none !important" in css


def test_v2_css_has_no_external_asset_dependency() -> None:
    css = V2_CSS.read_text(encoding="utf-8")
    assert "http://" not in css
    assert "https://" not in css
    assert "@import" not in css
    assert "url(" not in css


def test_ui_v2_does_not_claim_owner_approval() -> None:
    for path in [
        BASE_DIR / "templates" / "intro.html",
        BASE_DIR / "templates" / "participant_dashboard.html",
        BASE_DIR / "templates" / "edition_read.html",
        BASE_DIR / "templates" / "feedback_adaptation.html",
        BASE_DIR / "templates" / "admin_dashboard.html",
        BASE_DIR / "templates" / "admin_content_review.html",
        BASE_DIR / "templates" / "admin_publish_decision.html",
        V2_CSS,
    ]:
        content = path.read_text(encoding="utf-8")
        assert "UI_APPROVED" not in content
        assert "OWNER_UI_APPROVED=true" not in content
