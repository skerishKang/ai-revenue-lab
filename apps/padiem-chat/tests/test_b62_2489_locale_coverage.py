from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "apps" / "padiem-chat" / "static"
KOREAN = re.compile(r"[\uac00-\ud7a3]")


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def locale_keys(source: str, start: str, end: str) -> set[str]:
    left = source.index(start)
    right = source.index(end, left + len(start))
    block = source[left:right]
    return set(re.findall(r'"([^"]+)":', block))


def test_locale_dictionary_has_exact_ko_en_key_parity():
    source = read("locale.js")
    ko = locale_keys(source, "ko: {", "en: {")
    en = locale_keys(source, "en: {", "\n    }")

    assert ko == en
    assert len(ko) >= 295


def test_static_locale_bindings_reference_declared_keys():
    locale_source = read("locale.js")
    keys = locale_keys(locale_source, "ko: {", "en: {")
    html = read("index.html")

    attributes = (
        "data-locale-key",
        "data-locale-aria-label",
        "data-locale-placeholder",
        "data-locale-title",
        "data-locale-alt",
        "data-locale-content",
    )
    referenced: set[str] = set()
    for attribute in attributes:
        referenced.update(re.findall(rf'{re.escape(attribute)}="([^"]+)"', html))

    assert referenced
    assert referenced <= keys


def test_app_runtime_copy_does_not_hardcode_korean_user_text():
    app = read("app.js")
    offending = [
        (line_no, line.strip())
        for line_no, line in enumerate(app.splitlines(), start=1)
        if KOREAN.search(line)
    ]
    assert offending == []


def test_static_korean_copy_uses_declared_or_selector_locale_contract():
    html = read("index.html")
    locale = read("locale.js")

    selector_contracts = (
        '["#attachmentButton span:last-child", "file"]',
        '["#webSearchButton span:last-child", "web"]',
        '["#deepResearchButton span:last-child", "research"]',
        '[".starter:nth-child(3) strong", "document-title"]',
        '[".starter-grid", "aria-label", "starter-grid"]',
        '[".claw-chips", "aria-label", "claw-actions-aria"]',
    )
    for contract in selector_contracts:
        assert contract in locale

    assert '<span>파일</span>' in html
    assert '<span>웹 검색</span>' in html
    assert '<span>심층 리서치</span>' in html
    assert '<div class="starter-grid" aria-label="추천 질문">' in html
    assert 'role="group" aria-label="Claw 작업 선택"' in html
    assert 'id="runtimeNote">파일 첨부 형식을 확인하는 중입니다.' in html

def test_runtime_translation_calls_reference_declared_keys():
    locale_source = read("locale.js")
    keys = locale_keys(locale_source, "ko: {", "en: {")
    app = read("app.js")

    runtime_keys = set(re.findall(r'\b(?:uiT|clawT)\("([^"]+)"', app))
    assert runtime_keys
    assert runtime_keys <= keys


def test_explicit_locale_preference_uses_url_without_browser_storage():
    locale = read("locale.js")

    assert 'url.searchParams.set("lang", lang)' in locale
    assert 'apply(getUrlLocale() || "ko", false);' in locale
    assert "localStorage" not in locale
    assert "sessionStorage" not in locale
