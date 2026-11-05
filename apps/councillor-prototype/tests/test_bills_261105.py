# -*- coding: utf-8 -*-
"""제8·9대 광주광역시의회 대표발의 조례안 — 2026-11-05 추가.

옛 의회 의안정보시스템은 제안자명 조건을 서버에서 걸러 주지 않는다. 대수·조례안·
의원 조건으로 받은 뒤 제안자 칸이 "임미란의원"으로 시작하는 행만 남겼고, 공동발의는
searchChkProcess2=F로 제외했다. 원안가결·수정가결만 싣고 계류·철회는 뺀다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))
BILLS = DATA["policy"]["bills"]


def test_only_accepted_representative_bills_are_published() -> None:
    assert len(BILLS) == 61
    assert sum(item["assembly"] == 9 for item in BILLS) == 29
    assert sum(item["assembly"] == 8 for item in BILLS) == 32
    for item in BILLS:
        assert re.fullmatch(r"(8|9)-\d+", item["number"]), item["number"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["date"]), item["date"]
        assert item["result"] in ("원안가결", "수정가결"), item["result"]
        assert item["url"].startswith(
            "https://council.gwangju.go.kr:5142/bills/viewer.do?searchBlUid="
        ), item["url"]
    numbers = [item["number"] for item in BILLS]
    urls = [item["url"] for item in BILLS]
    assert len(numbers) == len(set(numbers)), "a bill number is listed twice"
    assert len(urls) == len(set(urls)), "two bills share one viewer link"


def test_bills_are_grouped_by_assembly_newest_first() -> None:
    assert [item["assembly"] for item in BILLS] == [9] * 29 + [8] * 32
    for assembly in (9, 8):
        dates = [item["date"] for item in BILLS if item["assembly"] == assembly]
        assert dates == sorted(dates, reverse=True), f"{assembly}대 bills are out of order"
        numbers = [item["number"] for item in BILLS if item["assembly"] == assembly]
        assert len(numbers) == len(set(numbers)), "duplicate rows"


def test_pending_and_withdrawn_bills_are_not_published() -> None:
    numbers = {item["number"] for item in BILLS}
    for number in ("9-773", "9-366", "9-50", "9-25"):
        assert number not in numbers, f"{number} is pending or withdrawn"
    for item in BILLS:
        assert item["result"] not in ("계류", "철회", "부결", "폐기", "보류"), item


def test_policy_page_explains_the_scope_and_groups_the_list() -> None:
    html = (ROOT / "policy.html").read_text(encoding="utf-8")
    assert "제8대·제9대 광주광역시의회 대표발의" in html
    assert 'id="policyBills"' in html
    assert 'class="card-grid" id="policyBills"' not in html, "the bills need their own grouped list"
    assert "원안가결·수정가결" in html
    assert "의안정보시스템" in DATA["policy"]["source"]
    data_js = json.dumps(BILLS, ensure_ascii=False)
    assert "계류" not in data_js and "철회" not in data_js


def test_renderer_groups_and_links_every_bill() -> None:
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for token in (
        "renderBills", "policy.bills", "bill-group", "bill-list", "bill-row",
        "bill-number", "bill-title", "bill-date", "bill-result",
    ):
        assert token in app_js, token
    assert "renderBills(policy)" in app_js
    assert "policyBills" in app_js


def test_the_home_shortcut_reaches_the_policy_page() -> None:
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    assert index.count('href="./policy.html"') >= 2
    home_js = (ROOT / "static" / "home.js").read_text(encoding="utf-8")
    assert 'label: "정책자료"' in home_js
    assert 'href: "./policy.html"' in home_js
