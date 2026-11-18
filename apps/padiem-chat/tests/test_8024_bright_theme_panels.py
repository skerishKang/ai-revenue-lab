"""#8024(+#8023) 대표 결정(11-18 08:38) 묶음-① — 판 표면은 테마를 따른다.

프로젝트 창·정보 패널·첨부 칸·유틸 하위 메뉴의 어두운 스킨은 dark·cinematic에서만
칠하고, 밝은 테마(light·padiem-home·glass)는 같은 판의 토큰 바탕(--panel·--card-bg)
을 쓴다. 유틸 PDF→Markdown 내부 패널은 토큰을 따라 dark·cinematic에서도 어둡다
(#8023 — 점검 이후 CSS 정리로 이미 토큰화됐다: 이 계약이 그것을 고정한다).
유틸 하위 메뉴 호버는 판의 한 단계(--control-wash-hover) 하나다.
"""

from __future__ import annotations

from pathlib import Path

from css_rules import (declaration, parse_rules,
                       rule_selector_list_contains)

STATIC = Path(__file__).resolve().parents[1] / "static"
WORKSPACE_CSS = (STATIC / "padiem-cinematic-workspace.css").read_text(encoding="utf-8")
SURFACES_CSS = (STATIC / "padiem-surfaces.css").read_text(encoding="utf-8")
PROJECTS_CSS = (STATIC / "projects.css").read_text(encoding="utf-8")
ATTACHMENTS_CSS = (STATIC / "attachments.css").read_text(encoding="utf-8")
UTIL_MENU_CSS = (STATIC / "util-menu.css").read_text(encoding="utf-8")
UTIL_APP_CSS = (STATIC / "util-app.css").read_text(encoding="utf-8")
GLASS_PORTRAIT_CSS = (STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")

DARK_SCOPES = ('html[data-theme="dark"]', 'html[data-theme="cinematic"]')


def _rules(css: str):
    return parse_rules(css)


def _one(rules: list, selector: str, label: str):
    matched = [rule for rule in rules
               if rule.media is None and rule_selector_list_contains(rule, selector)]
    assert len(matched) == 1, f"{label}: 기대한 규칙 1개, 실제 {len(matched)}개"
    return matched[0]


def _value(rule, prop: str) -> str:
    raw = declaration(rule, prop)
    assert raw is not None, f"{prop} 선언이 없다"
    return raw.replace("!important", "").strip()


def _has_skin(rule) -> bool:
    return any(declaration(rule, prop) is not None
               for prop in ("background", "color", "border-color", "border"))


def _dark_scoped(rules: list, suffix: str, label: str):
    """어두운 스킨 규칙이 dark·cinematic 스코프로만 존재하는지 확인한다."""
    scoped = []
    unscoped = []
    for rule in rules:
        if not _has_skin(rule):
            continue
        if not any(selector.endswith(suffix) for selector in rule.selectors):
            continue
        if any(selector.startswith(scope + " ") for scope in DARK_SCOPES
               for selector in rule.selectors if selector.endswith(suffix)):
            scoped.append(rule)
        else:
            unscoped.append(rule)
    assert scoped, f"{label}: dark 스코프 규칙이 없다"
    assert not unscoped, f"{label}: 스코프 없는 어두운 스킨이 남아 있다 {unscoped[0].selectors}"


def test_workspace_dark_skins_are_scoped_to_dark_and_cinematic() -> None:
    rules = _rules(WORKSPACE_CSS)
    for suffix, label in [
        (".project-banner", "정보 패널"),
        (".project-form", "프로젝트 창 바탕"),
        (".project-form input", "창 입력칸"),
        (".project-secondary", "창 보조 단추"),
        (".attachment-preview", "첨부 미리보기"),
        (".document-attachment-icon", "문서 첨부 아이콘"),
    ]:
        _dark_scoped(rules, suffix, label)


def test_surfaces_dark_skins_are_scoped_to_dark_and_cinematic() -> None:
    rules = _rules(SURFACES_CSS)
    for suffix, label in [
        (".attachment-chip", "첨부 칩"),
        (".attachment-preview", "첨부 미리보기"),
        (".project-banner", "정보 패널"),
        (".project-form", "프로젝트 창 바탕"),
        (".project-form input", "창 입력칸"),
    ]:
        _dark_scoped(rules, suffix, label)
    # 소글자 바닥값도 프로젝트·첨부 문구는 dark 스코프 안으로 들어갔다.
    for rule in rules:
        if any(selector.startswith(".project-banner-copy small")
               for selector in rule.selectors):
            assert any(selector.startswith("html[data-theme=")
                       for selector in rule.selectors), (
                "프로젝트 소글자 흰 바닥값이 스코프 없이 남아 있다"
            )


def test_project_dialog_uses_the_panel_token_in_bright_themes() -> None:
    rules = _rules(PROJECTS_CSS)
    dialog = _one(rules, ".project-dialog", "프로젝트 창")
    assert _value(dialog, "background") == "var(--panel)"
    assert _value(dialog, "color") == "var(--text)"
    entry = _one(rules, ".project-form input", "창 입력칸")
    assert _value(entry, "background") == "var(--card-bg)"
    secondary = _one(rules, ".project-secondary", "보조 단추")
    assert _value(secondary, "background") == "var(--card-bg)"
    danger = _one(rules, ".project-form-actions .project-danger", "위험 단추")
    assert _value(danger, "background") == "var(--card-bg)"
    # 소글자 대비 4.5:1 — 밝은 판 위 muted 토큰.
    for selector, label in [
        (".project-dialog-header p", "창 머리 글자"),
        (".project-form label span", "입력 라벨 작은 글자"),
        (".project-form-note", "창 안내 문구"),
    ]:
        rule = _one(rules, selector, label)
        assert _value(rule, "color") == "var(--muted)", label


def test_attachment_cells_use_one_card_token() -> None:
    rules = _rules(ATTACHMENTS_CSS)
    for selector, label in [
        (".attachment-chip", "첨부 칩"),
        (".attachment-preview", "첨부 미리보기"),
    ]:
        rule = _one(rules, selector, label)
        assert _value(rule, "background") == "var(--card-bg)", label
        assert "var(--card-border)" in _value(rule, "border"), label
    icon = _one(rules, ".attachment-chip-icon", "칩 아이콘")
    assert _value(icon, "background") == "var(--control-wash-strong)"
    assert _value(icon, "color") == "var(--muted)"
    # 같은 선택자를 공유하는 자름(ellipsis) 규칙이 있으므로 color 선언이 있는
    # 규칙으로 가린다.
    copy_strong = [rule for rule in rules
                   if rule.media is None
                   and rule_selector_list_contains(rule, ".attachment-chip-copy strong")
                   and declaration(rule, "color") is not None]
    assert len(copy_strong) == 1, f"칩 이름: {len(copy_strong)}개"
    assert _value(copy_strong[0], "color") == "var(--text)"
    copy_small = [rule for rule in rules
                  if rule.media is None
                  and rule_selector_list_contains(rule, ".attachment-chip-copy small")
                  and declaration(rule, "color") is not None]
    assert len(copy_small) == 1, f"칩 크기: {len(copy_small)}개"
    assert _value(copy_small[0], "color") == "var(--muted)"
    remove = _one(rules, ".attachment-chip .attachment-remove", "칩 삭제 단추")
    assert _value(remove, "color") == "var(--muted)"
    remove_hover = _one(rules, ".attachment-chip .attachment-remove:hover:not(:disabled)",
                        "칩 삭제 호버")
    assert _value(remove_hover, "background") == "var(--control-wash-soft)"


def test_util_submenu_hover_is_one_step_not_a_white_veil() -> None:
    rules = _rules(UTIL_MENU_CSS)
    hover = _one(rules, ".util-submenu-item:hover", "유틸 하위 메뉴 호버")
    assert _value(hover, "background") == "var(--control-wash-hover)"
    # 기존 흰 베일(--surface-veil-strong)은 어떤 하위 메뉴 호버에도 돌아오지 않는다.
    for rule in rules:
        if any(".util-submenu-item" in selector and ":hover" in selector
               and not selector.startswith("html[data-theme=")
               for selector in rule.selectors):
            for value in rule.declarations.values():
                assert "surface-veil-strong" not in value, rule.selectors


def test_pdfmd_inner_panels_follow_the_theme_tokens() -> None:
    """#8023: 유틸 PDF→Markdown 내부 패널은 토큰을 따른다(어두운 테마 흰 판 금지)."""
    rules = _rules(UTIL_MENU_CSS)
    shell = _one(rules, ".pdfmd-shell", "PDF→MD 껍데기")
    assert _value(shell, "background").startswith("var(--card-bg")
    app_rules = _rules(UTIL_APP_CSS)
    cols = _one(app_rules, ".pdfmd-input-col", "PDF→MD 안쪽 판")
    assert _value(cols, "background").startswith("var(--glass-card-surface")
    # 어두운 테마에서 이 토큰이 흰 값을 내지 않는다: --glass-card-surface는
    # glass 전용 정의(padiem-glass-portrait.css)라 dark·cinematic은 --panel
    # 대체값을 쓴다. glass 정의가 스코프를 벗어나면 이 계약이 막는다.
    glass_rules = _rules(GLASS_PORTRAIT_CSS)
    for rule in glass_rules:
        if declaration(rule, "--glass-card-surface") is not None:
            assert any('data-theme="padiem-glass"' in s for s in rule.selectors), (
                f"--glass-card-surface 정의가 glass 스코프를 벗어났다: {rule.selectors}"
            )
