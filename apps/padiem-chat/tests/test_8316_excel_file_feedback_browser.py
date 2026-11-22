"""Excel file feedback must reflect the current selection, not a prior missing file."""
from __future__ import annotations

from io import BytesIO

from test_8211_pc_connect_entry_browser import _page, site, sync_playwright


def test_valid_excel_selection_clears_missing_file_feedback(site, tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(["Item", "Amount"])
    workbook.active.append(["Sample", 42])
    stream = BytesIO()
    workbook.save(stream)
    with sync_playwright() as playwright:
        browser, page = _page(playwright, site)
        try:
            page.evaluate("location.hash = '#util/excel'")
            form = page.locator("#utilToolForm-excel")
            form.wait_for(state="visible")
            file_input = form.locator('input[type="file"]')
            form.locator('button[type="submit"]').click()
            assert file_input.get_attribute("aria-invalid") == "true"
            assert page.locator(".util-excel-status").is_visible()
            file_input.set_input_files({
                "name": "sample.xlsx",
                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "buffer": stream.getvalue(),
            })
            page.screenshot(path=tmp_path / "excel-selected.png", full_page=True)
            assert file_input.get_attribute("aria-invalid") != "true"
            assert not page.locator(".util-excel-status").is_visible()
            assert not form.locator(".util-excel-note").first.is_visible()
            file_input.set_input_files([])
            assert form.locator(".util-excel-note").first.is_visible()
        finally:
            browser.close()
