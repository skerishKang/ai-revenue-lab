"""#5824 — '내 API 키' 등록 화면 단순화 계약.

복잡해진 등록 화면을 단순 형태로 되돌린다:

- 처음 열면 안내 한 줄 + 키 입력 한 칸 + '등록' 버튼만 보인다. 오류 문구도
  '미검증' 표시도, 접히지 않은 고급 영역도 없다;
- '자동 확인' 버튼은 없다. 등록이 자동 확인을 포함하며, 실패했을 때에만
  고급 영역이 열린다(다른 경로로는 열리지 않는다);
- 등록에 성공하면 '등록됨 · 사용 가능' 한 줄과 '삭제' 버튼만 남는다. 키 원문은
  다시 렌더링되지 않는다;
- 공급사·모델 칸은 빈 칸 + 일반 설명으로 시작한다. 공급사 선택의 기본값은
  '선택하세요'(빈 값)이고 어떤 공급사·모델 이름도 기본값이 아니다;
- 화면 문자열 어디에도 공급사 ID·모델 ID가 나타나지 않는다.

헤드리스 화면 확인: 1440×900과 390×844에서 가로 넘침 0, 콘솔 오류 0.

locale.js 문구 키(ko·en)는 별도 문자열 시험으로 단정한다. 브라우저 시험은
test_5121_byok_ui_browser.py의 하네스(실제 product-capabilities.js 실행, 모든
API 호출은 Playwright로 가로챔 — 실제 백엔드·공급사 호출 없음)을 재사용한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

from test_5121_byok_ui_browser import (  # noqa: E402
    FAKE_KEY,
    MANUAL_MODELS,
    MANUAL_PROVIDER,
    MODEL,
    PROVIDER,
    REGISTERED_STATUS,
    _open_custom,
    _open_harness,
    _open_picker,
    browser,  # noqa: F401 — pytest fixture re-export
    static_server,  # noqa: F401 — pytest fixture re-export
)

STATIC = Path(__file__).resolve().parents[1] / "static"

BYOK_LOCALE_KEYS = (
    "byok-register",
    "byok-registering",
    "byok-registered",
    "byok-select-placeholder",
    "byok-advanced-summary",
    "byok-detect-failed",
)


def test_locale_declares_the_byok_keys_in_ko_and_en() -> None:
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    _, after = locale.split("ko: {", 1)
    ko = after.split("en: {", 1)[0]
    en = after.split("en: {", 1)[1]
    for block in (ko, en):
        for key in BYOK_LOCALE_KEYS:
            assert f'"{key}"' in block, key


def test_module_has_no_second_key_form_and_no_autodetect_button() -> None:
    """The old duplicates are gone from the module source, not just hidden."""
    source = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
    assert "modeCustomApiKey" not in source
    assert "modeAutoByokResult" not in source
    assert "autoDetectButton" not in source
    assert "autoCard" not in source
    # The advanced section owns no key field of its own: the single key input
    # and the single 등록 button live above the <details>.
    advanced_children = source.split("customAdvanced.append(", 1)[1].split(");", 1)[0]
    for forbidden in ("autoKeyInput", "autoRegisterButton", "customKeyHintEl"):
        assert forbidden not in advanced_children, forbidden


def test_screen_strings_never_invent_provider_or_model_names() -> None:
    """Copy lines rendered by the module itself carry no supplier/model id."""
    source = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
    copy_block = source.split("const CUSTOM_COPY = Object.freeze({", 1)[1].split(
        "const CUSTOM_LOCALE_KEYS", 1
    )[0]
    assert PROVIDER not in copy_block
    assert MODEL not in copy_block
    assert "beam-free" not in copy_block
    # No default endpoint is ever rendered into the address field.
    assert "default_endpoint" not in copy_block


@pytest.mark.parametrize("viewport", [
    {"width": 1440, "height": 900},
    {"width": 390, "height": 844},
])
def test_headless_first_open_no_overflow_no_console_errors(browser, static_server, viewport) -> None:
    page, state, context = _open_harness(browser, static_server, viewport=viewport)
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error" else None,
    )
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    try:
        _open_picker(page)
        _open_custom(page)

        # First open: one key input, one 등록 button, no status/error line,
        # advanced collapsed, no supplier/model name anywhere on the screen.
        credential = page.locator(".mode-custom-credential")
        inputs = credential.locator("input:visible")
        assert inputs.count() == 1
        assert inputs.first.get_attribute("id") == "modeAutoByokKey"
        buttons = credential.locator("button:visible")
        assert buttons.count() == 1
        assert buttons.first.inner_text().strip() == "등록"
        expect(page.locator(".mode-custom-status")).to_be_hidden()
        expect(page.locator(".mode-custom-message")).to_be_hidden()
        assert page.locator("#modeCustomAdvanced").evaluate("el => el.open") is False
        screen_text = page.locator("body").inner_text()
        assert PROVIDER not in screen_text
        assert MODEL not in screen_text

        # 가로 넘침 0: the document never scrolls sideways and no visible
        # element pokes out of the viewport.
        metrics = page.evaluate(
            """() => ({
              scrollWidth: document.documentElement.scrollWidth,
              clientWidth: document.documentElement.clientWidth,
            })"""
        )
        assert metrics["scrollWidth"] <= metrics["clientWidth"]
        offenders = page.evaluate(
            """() => {
              const limit = window.innerWidth;
              const out = [];
              document.querySelectorAll('body *').forEach((el) => {
                if (!(el instanceof HTMLElement) && !(el instanceof SVGElement)) return;
                const style = getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) return;
                if (rect.right > limit + 0.5 || rect.left < -0.5) {
                  out.push(el.tagName + '.' + String(el.className).slice(0, 40));
                }
              });
              return out;
            }"""
        )
        assert offenders == [], offenders

        assert console_errors == [], console_errors
        assert state["credential_gets"] >= 1
        assert all(url.startswith(static_server) for url in state["request_urls"])
    finally:
        context.close()


def test_advanced_opens_only_when_detection_fails(browser, static_server) -> None:
    page, state, context = _open_harness(
        browser, static_server, viewport={"width": 1440, "height": 900}
    )
    try:
        _open_picker(page)
        _open_custom(page)

        # Success path: the advanced section never opens by itself.
        page.locator("#modeAutoByokKey").fill(FAKE_KEY)
        page.locator("#modeAutoByokRegister").click()
        expect(page.locator(".mode-custom-status")).to_have_text(REGISTERED_STATUS)
        assert page.locator("#modeCustomAdvanced").evaluate("el => el.open") is False
        assert state["byok_counts"] == {"detect": 1, "register": 1}
        # Screen still carries no supplier/model id after the registration.
        screen_text = page.locator("body").inner_text()
        assert PROVIDER not in screen_text
        assert MODEL not in screen_text
        expect(page.locator(".mode-custom-message")).to_be_hidden()

        # Failure path: the provider could not be recognised — only now the
        # advanced section opens, with a red guide line and no registration.
        page.locator(".mode-custom-delete").click()
        expect(page.locator(".mode-custom-message")).to_have_text("API 키를 삭제했습니다.")
        expect(page.locator("#modeAutoByokKey")).to_be_visible()
        state["byok_detect_result"] = {
            "ok": True,
            "verified": False,
            "reason": "키 형식을 확인했지만 공급사를 찾지 못했습니다.",
        }
        state["byok_counts"] = {"detect": 0, "register": 0}
        page.locator("#modeAutoByokKey").fill(FAKE_KEY)
        page.locator("#modeAutoByokRegister").click()
        expect(page.locator(".mode-custom-message")).to_contain_text(
            "공급사를 찾지 못했습니다"
        )
        expect(page.locator(".mode-custom-message")).to_have_attribute(
            "data-state", "error"
        )
        assert page.locator("#modeCustomAdvanced").evaluate("el => el.open") is True
        assert state["byok_counts"] == {"detect": 1, "register": 0}
        # The key stays in the field so the user can retry after choosing the
        # provider by hand; the provider select still starts from 선택하세요.
        assert page.locator("#modeAutoByokKey").input_value() == FAKE_KEY
        assert page.locator("#modeCustomProvider").input_value() == ""
        screen_text = page.locator("body").inner_text()
        assert PROVIDER not in screen_text
        assert MODEL not in screen_text
        assert MANUAL_MODELS[0] not in screen_text
    finally:
        context.close()


def test_success_state_is_one_status_line_plus_delete(browser, static_server) -> None:
    page, state, context = _open_harness(
        browser, static_server, viewport={"width": 390, "height": 844}
    )
    try:
        _open_picker(page)
        _open_custom(page)
        page.locator("#modeAutoByokKey").fill(FAKE_KEY)
        page.locator("#modeAutoByokRegister").click()
        expect(page.locator(".mode-custom-status")).to_have_text(REGISTERED_STATUS)
        # One status line, one delete button, no key input, no register
        # button, no second message repeating the status.
        credential = page.locator(".mode-custom-credential")
        expect(credential.locator("#modeAutoByokKey")).to_be_hidden()
        expect(credential.locator("#modeAutoByokRegister")).to_be_hidden()
        expect(credential.locator(".mode-custom-delete")).to_be_visible()
        expect(page.locator(".mode-custom-message")).to_be_hidden()
        visible_texts = page.locator(".mode-custom-credential :visible").all_inner_texts()
        assert sum(REGISTERED_STATUS in line for line in visible_texts) == 1
        assert not any(FAKE_KEY in line for line in visible_texts)
        # The detection-failure copy never appears on the success path.
        assert not any("고급 영역에서 직접 선택" in line for line in visible_texts)
        assert MANUAL_PROVIDER not in " ".join(visible_texts)
        assert state["credential_gets"] >= 1
    finally:
        context.close()
