"""#6046: content-country selection in the council app.

The contract is: Korea is a no-op (prompt text and request body stay exactly as
they are today), the other three countries append a language/expression
instruction and send `country` on the request.
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
    assert 'if (country !== "kr") payload.country = country;' in JS


def test_the_country_is_read_from_local_storage_with_a_korean_default():
    assert 'padiem-council-country' in JS
    assert 'return Object.prototype.hasOwnProperty.call(COUNTRY_INSTRUCTIONS, value) ? value : "kr";' in JS


def test_the_instruction_forbids_inventing_people_and_events():
    for probe in ("Do not invent a named member", "N'inventez ni élu nommé"):
        assert probe in JS, probe
