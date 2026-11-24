"""Library subtitle contrast regression (#8686 follow-up)."""
from _support import contrast_repair_source as source
from test_261124_project_form_standalone_header_contrast import (
    FETCH_STUB, THEMES, VIEWPORTS, _painted_contrast, site, sync_playwright,
)


def test_library_subtitle_contrast(site):
    rule = source.rule_declarations("library.css", ".library-subtitle")
    assert rule.get("color") == "var(--standalone-tagline-text)"
    assert rule.get("opacity", "1") == "1"
    if sync_playwright is None:
        return
    observations = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for theme in THEMES:
                for width, height in VIEWPORTS:
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        reduced_motion="reduce",
                    )
                    page.route("**/*", lambda route: route.continue_()
                               if "127.0.0.1" in route.request.url else route.abort())
                    page.add_init_script(FETCH_STUB)
                    page.goto(site + "?theme=" + theme, wait_until="load")
                    page.wait_for_timeout(1600)
                    assert page.evaluate("document.documentElement.dataset.theme") == theme
                    page.evaluate("document.getElementById('filesNavButton').click()")
                    page.wait_for_timeout(900)
                    ratios = _painted_contrast(page, ("#librarySubtitle",))["#librarySubtitle"]
                    assert ratios, (theme, width, "not painted")
                    observations.append((theme, width, min(ratios)))
                    page.close()
        finally:
            browser.close()
    assert len(observations) == 10
    assert all(ratio >= 4.5 for _, _, ratio in observations), observations

