from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
UI_SCRIPT = (ROOT / "github-live-status.js").read_text(encoding="utf-8")


def mock_payload(*, stale: bool = False) -> dict:
    states = {
        1: (111, "open", True, False, "pending"),
        2: (88, "closed", False, True, "pass"),
        9: (175, "open", True, False, "fail"),
    }
    issue_numbers = {1: 108, 2: 43, 6: 98, 9: 170}
    businesses = []
    for number in range(1, 16):
        if number == 15:
            businesses.append({
                "number": 15, "connectionState": "unmapped", "repository": None,
                "issue": None, "pullRequest": None,
                "checks": {"state": "unavailable", "source": "none", "total": 0, "completed": 0},
                "activityAt": None, "error": None,
            })
            continue
        issue_number = issue_numbers.get(number, 1000 + number)
        issue = {
            "number": issue_number, "title": f"Issue {issue_number}", "state": "open",
            "updatedAt": "2026-07-27T00:10:00Z",
            "url": f"https://github.com/skerishKang/ai-revenue-lab/issues/{issue_number}",
        }
        pull_request = None
        checks = {"state": "unavailable", "source": "none", "total": 0, "completed": 0}
        if number in states:
            pr_number, state, draft, merged, check_state = states[number]
            pull_request = {
                "number": pr_number, "title": f"PR {pr_number}", "state": state,
                "draft": draft, "merged": merged, "headSha": (str(number) * 40)[:40],
                "baseRef": "main", "updatedAt": "2026-07-27T00:20:00Z",
                "url": f"https://github.com/skerishKang/ai-revenue-lab/pull/{pr_number}",
            }
            checks = {"state": check_state, "source": "pr_head", "total": 2, "completed": 1 if check_state == "pending" else 2}
        businesses.append({
            "number": number, "connectionState": "connected", "repository": "skerishKang/ai-revenue-lab",
            "issue": issue, "pullRequest": pull_request, "checks": checks,
            "activityAt": "2026-07-27T00:20:00Z", "error": None,
        })
    return {
        "ok": True, "schemaVersion": 1, "syncedAt": "2026-07-27T00:30:00Z", "stale": stale,
        "repository": {
            "fullName": "skerishKang/ai-revenue-lab",
            "url": "https://github.com/skerishKang/ai-revenue-lab",
            "defaultBranch": "main", "latestSha": "a" * 40,
            "latestCommitTitle": "feat: deterministic mock", "latestCommitAt": "2026-07-27T00:25:00Z",
        },
        "summary": {"openIssues": 4, "openPullRequests": 2, "draftPullRequests": 2},
        "businesses": businesses, "errors": [],
    }


def fixture_html(payload: dict) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False)
    rows = "".join(
        f'<div class="biz-item" data-biz-number="{number}" tabindex="0"><span class="biz-number">{number:02d}</span>'
        f'<div class="biz-title-group"><span class="biz-title">Business {number}</span><span class="biz-korean">비즈니스 {number}</span></div>'
        f'<span class="static-progress">{25 if number == 9 else 10}%</span></div>'
        for number in range(1, 16)
    )
    project_cards = "".join(
        f'<article class="pd-card" data-project-id="p{number}"><div class="pd-card-github-state">GitHub 자동 동기화 미연결</div></article>'
        for number in (1, 2, 6, 9, 15)
    )
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>*{{box-sizing:border-box}} body{{margin:0;font:14px sans-serif;max-width:100%;overflow-x:hidden}} .controls{{display:flex;gap:8px;padding:8px}}
.biz-item{{display:grid;grid-template-columns:40px minmax(0,1fr) 60px;gap:8px;padding:8px;border-bottom:1px solid #ccc}} .biz-title-group{{display:flex;min-width:0;flex-direction:column}}
.biz-korean{{font-size:12px;overflow-wrap:anywhere}} .pd-card{{padding:8px;margin:8px;border:1px solid #ccc}} dialog{{max-width:min(680px,calc(100vw - 24px))}}
.dialog-section{{display:grid;grid-template-columns:140px 1fr;gap:8px;padding:5px}} code{{overflow-wrap:anywhere}} @media(max-width:500px){{.dialog-section{{grid-template-columns:1fr}}}}</style></head><body>
<div class="controls"><button id="lang-ko">한국어</button><button id="lang-en">EN</button><input id="search" type="search"><select id="filter"><option value="all">all</option><option value="odd">odd</option></select></div>
<div id="biz-list">{rows}</div><div id="pd-grid">{project_cards}</div><div id="static-b09">UI_APPROVED · Draft PR #175 · 25% · static nextAction preserved</div>
<dialog id="business-dialog"><div id="biz-dialog-body"></div><button id="close">close</button></dialog>
<script>window.ARL_PROJECTS=[1,2,6,9,15].map(n=>({{id:`p${{n}}`,businessNumber:n}})); const PAYLOAD={payload_json};
window.fetch=async()=>new Response(JSON.stringify(PAYLOAD),{{status:PAYLOAD.ok?200:503,headers:{{'Content-Type':'application/json'}}}});
const list=document.querySelector('#biz-list'),originalRows=list.innerHTML; function bindRows(){{document.querySelectorAll('.biz-item').forEach(row=>row.onclick=()=>{{const n=Number(row.dataset.bizNumber),body=document.querySelector('#biz-dialog-body');
body.innerHTML=`<div class="dialog-biznumber">B${{String(n).padStart(2,'0')}}</div><div class="dialog-section"><span class="dialog-section-label">정적 진행률</span><span class="dialog-section-value">${{n===9?'25%':'10%'}}</span></div><div class="dialog-section"><span class="dialog-section-label">정적 판단</span><span class="dialog-section-value">${{n===9?'UI_APPROVED · static nextAction preserved':'static'}}</span></div>`;document.querySelector('#business-dialog').showModal()}})}}
function applySearch(){{const q=document.querySelector('#search').value,f=document.querySelector('#filter').value;document.querySelectorAll('.biz-item').forEach(row=>{{const n=Number(row.dataset.bizNumber);row.hidden=(q&&!String(n).padStart(2,'0').includes(q))||(f==='odd'&&n%2===0)}})}}
document.querySelector('#search').addEventListener('input',applySearch);document.querySelector('#filter').addEventListener('change',applySearch);
document.querySelector('#lang-en').onclick=()=>{{document.documentElement.lang='en';list.innerHTML=originalRows;bindRows()}};document.querySelector('#lang-ko').onclick=()=>{{document.documentElement.lang='ko';list.innerHTML=originalRows;bindRows()}};
document.querySelector('#close').onclick=()=>document.querySelector('#business-dialog').close();bindRows();</script></body></html>"""


def run_case(page, payload: dict, *, expect_live: bool) -> dict:
    errors: list[str] = []
    page.on("console", lambda message: errors.append(f"console:{message.type}:{message.text}") if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(f"page:{error}"))
    page.set_content(fixture_html(payload), wait_until="domcontentloaded")
    page.add_script_tag(content=UI_SCRIPT)
    page.wait_for_timeout(250)
    assert page.locator(".biz-item").count() == 15
    if expect_live:
        page.wait_for_selector('[data-biz-number="1"] [data-github-live-row]')
    else:
        assert page.locator("[data-github-live-row]").count() == 0
        assert page.locator(".pd-card-github-state").first.text_content() == "GitHub 자동 동기화 미연결"
    return {"errors": errors, "overflow": page.evaluate("document.documentElement.scrollWidth - window.innerWidth")}


def main() -> None:
    results: dict[str, object] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        missing = {"ok": False, "schemaVersion": 1, "syncedAt": None, "stale": False, "error": {"code": "CONFIGURATION_MISSING", "message": "GitHub live synchronization is not configured."}, "businesses": []}
        results["configurationMissing"] = run_case(page, missing, expect_live=False)
        page.close()

        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        results["desktop"] = run_case(page, mock_payload(), expect_live=True)
        assert "PR 초안 #111" in page.locator('[data-biz-number="1"] [data-github-live-row]').text_content()
        assert "병합됨 #88" in page.locator('[data-biz-number="2"] [data-github-live-row]').text_content()
        assert "Issue 열림 #98" in page.locator('[data-biz-number="6"] [data-github-live-row]').text_content()
        assert "검사 실패" in page.locator('[data-biz-number="9"] [data-github-live-row]').text_content()
        assert "미연결" in page.locator('[data-biz-number="15"] [data-github-live-row]').text_content()
        assert "UI_APPROVED" in page.locator("#static-b09").text_content()
        page.locator('[data-biz-number="9"]').click()
        page.wait_for_selector('#biz-dialog-body [data-github-live-block]')
        dialog_text = page.locator("#biz-dialog-body").text_content()
        assert "a" * 40 in dialog_text and "9" * 40 in dialog_text and "UI_APPROVED" in dialog_text
        page.locator("#close").click()
        page.locator("#lang-en").click()
        page.wait_for_selector('[data-biz-number="9"] [data-github-live-row]')
        page.wait_for_timeout(100)
        assert "DRAFT PR #175" in page.locator('[data-biz-number="9"] [data-github-live-row]').text_content()
        assert "CHECKS FAIL" in page.locator('[data-biz-number="9"] [data-github-live-row]').text_content()
        page.locator("#search").fill("09")
        assert page.locator(".biz-item:not([hidden])").count() == 1
        page.locator("#search").fill("")
        page.locator("#filter").select_option("odd")
        assert page.locator(".biz-item:not([hidden])").count() == 8
        results["desktop"].update({"b01_b02_b06_b09_b15": "pass", "language": "ko/en pass", "searchFilter": "pass"})
        page.close()

        page = browser.new_page(viewport={"width": 390, "height": 844})
        results["mobile"] = run_case(page, mock_payload(), expect_live=True)
        page.close()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        results["stale"] = run_case(page, mock_payload(stale=True), expect_live=True)
        assert "오래된 정보" in page.locator('[data-biz-number="1"] [data-github-live-row]').text_content()
        page.close()
        browser.close()

    for result in results.values():
        assert result["errors"] == [] and result["overflow"] <= 0
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
