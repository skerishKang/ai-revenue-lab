"""Browser workflow with synthetic PC, form, model and PDF responses."""
import json
from urllib.parse import urlsplit

import pytest

from test_4428_b66_pc_connect_browser import browser, server, ready_page  # noqa: F401

ROLES = ("item", "quantity", "unit_price", "amount", "subtotal", "tax", "total", "date", "recipient")
FORM_ID = "b66skill_" + "e" * 32
DISPATCH = "dsp_" + "d" * 32
FILLED = "file_" + "f" * 32


@pytest.mark.parametrize("layout,missing", [(1, False), (2, False), (3, False), (4, True)])
def test_select_confirm_save_reuse_and_download(browser, server, layout, missing):
    page, errors = ready_page(browser, server)
    page.evaluate("""id => window.PadiemPcFileExchange = {open: ({onSelect}) => onSelect(
        {fileId:id, name:'synthetic.xlsx', path:'sample/synthetic.xlsx'})}""", DISPATCH)
    stored = {"mapping": None}
    calls = []
    roles = {role: {"requires_confirmation": False, "candidates": [
        {"sheet": "Synthetic", "cell": chr(65 + n) + str(layout + 1)}
    ]} for n, role in enumerate(ROLES)}
    if missing:
        roles["unit_price"] = {"requires_confirmation": True, "candidates": []}

    def forms(route):
        body = route.request.post_data_json
        calls.append(("forms", body))
        if body.get("analyze_only"):
            route.fulfill(json={"ok": True, "analysis": roles, "structure": {
                "sheets": [{"name": "Synthetic", "cells": [{"cell": "A1", "text": "Sample", "formula": False}], "merged": []}],
                "truncated": False,
            }})
        else:
            stored["mapping"] = body["mapping"]
            route.fulfill(json={"ok": True, "form": {"saved_skill_id": FORM_ID}})

    def chat(route):
        calls.append(("chat", route.request.post_data_json))
        route.fulfill(json={"answer": json.dumps({"unit_price": {"sheet": "Synthetic", "cell": "D9"}})})

    def fill(route):
        calls.append(("fill", route.request.post_data_json))
        route.fulfill(json={"ok": True, "filled_file_id": FILLED, "filled_name": "sample.xlsx",
                            "client": "Synthetic", "mapping": {"Synthetic": {"B2": "Sample"}}, "extend": []})

    def skills(route):
        values = []
        if stored["mapping"] is not None:
            values = [{"saved_skill_id": FORM_ID, "skill_name": "Synthetic", "skill_kind": "pc_form",
                       "form_path": "sample/synthetic.xlsx", "form_filename": "synthetic.xlsx", "form_mapping_confirmed": True}]
        route.fulfill(json={"ok": True, "skills": values})

    page.route("**/api/b66/pc-quote/forms", forms)
    page.route("**/api/chat", chat)
    page.route("**/api/b66/pc-quote/fill", fill)
    page.route("**/api/b66/saved-skills?limit=20", skills)
    page.route("**/api/b66/pc-quote/pdf?**", lambda route: route.fulfill(
        status=200, content_type="application/pdf", body=b"%PDF-1.4\nsynthetic"))
    try:
        page.locator("#b66QuotePcPick").click()
        page.locator("#b66QuotePcMapping").wait_for(state="visible")
        if missing:
            row = page.locator(".b66-quote-map-row").nth(2)
            row.get_by_role("button", name="quote-map-yes").click()
            assert len([call for call in calls if call[0] == "chat"]) == 1
        page.get_by_role("button", name="quote-map-save").click()
        page.locator("#b66QuotePcMake").wait_for(state="visible")
        assert stored["mapping"] and len(stored["mapping"]) == 9
        page.locator("#b66QuoteRequest").fill("Synthetic quote")
        page.locator("#b66QuotePcMake").click()
        page.locator("#b66QuotePcPdf").wait_for(state="visible")
        assert [call for call in calls if call[0] == "fill"][-1][1]["form_id"] == FORM_ID
        with page.expect_download() as download:
            page.locator("#b66QuotePcPdf").click()
        assert download.value.suggested_filename.endswith(".pdf")
        # Refresh is async: wait for the stored skill, then reselect same PC path.
        page.wait_for_function("id => [...document.querySelectorAll('#b66QuoteSkillSelect option')].some(o => o.value === id)", arg=FORM_ID)
        before = len([call for call in calls if call[0] == "forms" and call[1].get("analyze_only")])
        page.locator("#b66QuotePcPick").click()
        page.locator("#b66QuotePcMake").wait_for(state="visible")
        assert page.locator("#b66QuotePcMapping").is_hidden()
        assert len([call for call in calls if call[0] == "forms" and call[1].get("analyze_only")]) == before
        assert not errors, errors
    finally:
        page.close()
