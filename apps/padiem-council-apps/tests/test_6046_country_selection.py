"""#6046: content-country selection in the council app.

The contract is: Korea is a no-op (prompt text and request body stay exactly as
they are today), the other three countries append a language/expression
instruction. The chat request itself no longer carries a `country` key (B3).
"""
from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
JS = (APP_ROOT / "static" / "council-app.js").read_text(encoding="utf-8")
HTML = (APP_ROOT / "static" / "index.html").read_text(encoding="utf-8")


def test_the_selector_offers_the_four_contract_countries():
    assert 'id="councilCountry"' in HTML
    for value in ("kr", "us", "uk", "fr"):
        assert re.search(rf'<option value="{value}">', HTML), value


def test_korea_is_a_no_op_and_the_other_three_add_an_instruction():
    assert 'kr: "",' in JS, "Korea must append nothing"
    for code in ("us", "uk", "fr"):
        assert re.search(rf"\n    {code}: \"", JS), code
    # 요청 본문도 kr 에서는 지금과 같아야 한다
    # B3: chat 요청은 country 키를 받지 않는다 — 화면도 더 이상 보내지 않는다.
    assert "payload.country" not in JS


def test_the_country_is_read_from_local_storage_with_a_korean_default():
    assert 'padiem-council-country' in JS
    assert 'return Object.prototype.hasOwnProperty.call(COUNTRY_INSTRUCTIONS, value) ? value : "kr";' in JS


def test_the_instruction_forbids_inventing_people_and_events():
    for probe in ("Do not invent a named member", "N'inventez ni élu nommé"):
        assert probe in JS, probe


def test_saving_a_document_carries_the_country_only_outside_korea():
    # kr 은 지금과 같은 본문(국가 필드 없음)을 보낸다 — 기존 사용자 요청 불변.
    assert "currentCountry() === \"kr\" ? {} : { country: currentCountry() }" in JS


def test_saved_lists_show_only_the_selected_country():
    assert "function sameCountry(file)" in JS
    assert 'String((file && file.country) || "kr") === currentCountry()' in JS
    assert JS.count(".filter(sameCountry)") >= 2


def test_a_plain_page_load_syncs_and_binds_the_selector():
    """init() 은 enterSignedIn() 을 거치지 않는다.

    실서비스 390/1440 E2E 에서 새로고침 후 선택값이 복원되지 않고 변경이 저장되지
    않았다(리스너 미부착). 평소 로드 경로도 동기화·바인딩을 걸어야 한다."""
    import re as _re

    init = _re.search(r"async function init\(\) \{(.*?)\n  \}", JS, _re.S)
    assert init, "init() must exist"
    assert "syncCountrySelect();" in init.group(1)
    # 두 경로가 같은 함수를 부르므로 리스너는 한 번만 건다
    assert "if (session.countryBound) return;" in JS
