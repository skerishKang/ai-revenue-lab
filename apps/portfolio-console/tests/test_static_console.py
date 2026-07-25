from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PortfolioConsoleStaticTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for relative in ("index.html", "styles.css", "businesses.js", "app.js", "projects.js", "_headers", "README.md"):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_quick_launch_file_deleted(self) -> None:
        self.assertFalse((ROOT / "quick-launch.js").is_file(), "quick-launch.js should be deleted")

    def test_quick_launch_removed_from_html(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("quick-launch", html)
        self.assertNotIn("ql-heading", html)
        self.assertNotIn("ql-list", html)
        self.assertNotIn("ql-item", html)
        self.assertNotIn("ql-active", html)
        self.assertNotIn("ql-planned", html)
        self.assertNotIn("quick-launch.js", html)
        self.assertNotIn("빠른 실행", html)

    def test_quick_launch_removed_from_app_js(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("quickLaunch", script)
        self.assertNotIn("ql-heading", script)
        self.assertNotIn("renderQuickLaunch", script)

    def test_quick_launch_removed_from_styles(self) -> None:
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn("quick-launch", css)
        self.assertNotIn(".ql-", css)

    def test_html_has_private_and_noindex_contracts(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('name="robots" content="noindex,nofollow,noarchive"', html)
        self.assertIn('id="private-admin-label"', html)
        self.assertIn('id="business-table-body"', html)
        self.assertIn('id="detail-panel"', html)
        self.assertIn('id="priority-list"', html)

    def test_registry_covers_one_through_fifteen(self) -> None:
        script = (ROOT / "businesses.js").read_text(encoding="utf-8")
        explicit_numbers = {int(value) for value in re.findall(r"number:\s*(\d+)", script)}
        self.assertTrue({1, 2, 3, 4, 5, 6, 13, 14, 15}.issubset(explicit_numbers))
        self.assertIn("Array.from({ length: 6 }", script)
        self.assertIn("index + 7", script)

    def test_registry_has_no_secret_like_literals(self) -> None:
        text = (ROOT / "businesses.js").read_text(encoding="utf-8").lower()
        forbidden = ("api_key", "private_key", "password", "database_url", "firebase_service_account")
        for token in forbidden:
            self.assertNotIn(token, text)

    def test_confirmed_surfaces_use_https(self) -> None:
        script = (ROOT / "businesses.js").read_text(encoding="utf-8")
        urls = re.findall(r'surfaceUrl:\s*"([^"]+)"', script)
        self.assertGreaterEqual(len(urls), 5)
        for url in urls:
            self.assertTrue(url.startswith("https://"), url)

    def test_csp_blocks_external_connections_and_forms(self) -> None:
        headers = (ROOT / "_headers").read_text(encoding="utf-8")
        self.assertIn("connect-src 'none'", headers)
        self.assertIn("form-action 'none'", headers)
        self.assertIn("frame-ancestors 'none'", headers)

    def test_javascript_references_expected_registry(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("window.ARL_BUSINESSES", script)
        self.assertIn("renderPriorityActions", script)
        self.assertIn("selectBusiness", script)
        self.assertNotIn("fetch(", script)
        self.assertNotIn("localStorage", script)

    def test_projects_file_exists(self) -> None:
        self.assertTrue((ROOT / "projects.js").is_file(), "projects.js")

    def test_projects_has_13_items(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        ids = re.findall(r'id:\s*"([^"]+)"', script)
        self.assertEqual(len(ids), 13)

    def test_projects_all_have_required_fields(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        required = ("purpose", "repositoryLabel", "workspace", "stage", "progressNote", "currentWork", "nextAction", "lastVerified")
        for field in required:
            count = len(re.findall(rf'{field}:\s*"', script))
            self.assertGreaterEqual(count, 13, f"{field} count")

    def test_projects_stage_vocabulary(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        stages = set(re.findall(r'stage:\s*"([^"]+)"', script))
        allowed = {"live", "demo", "build", "review", "planned"}
        self.assertTrue(stages.issubset(allowed), f"Unexpected stages: {stages - allowed}")

    def test_projects_no_windows_paths(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        forbidden = ("G:\\", "C:\\", "D:\\", "Users\\")
        for token in forbidden:
            self.assertNotIn(token, script)

    def test_projects_pageurl_accurate(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        page_urls = re.findall(r'pageUrl:\s*("[^"]*"|null)', script)
        self.assertEqual(len(page_urls), 13)
        with_url = sum(1 for u in page_urls if u != "null")
        without_url = sum(1 for u in page_urls if u == "null")
        self.assertEqual(with_url, 9)
        self.assertEqual(without_url, 4)

    def test_projects_pageurl_uses_https(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        urls = re.findall(r'pageUrl:\s*"(https?://[^"]+)"', script)
        self.assertEqual(len(urls), 9)
        for url in urls:
            self.assertTrue(url.startswith("https://"), url)

    def test_projects_no_secret_like_literals(self) -> None:
        text = (ROOT / "projects.js").read_text(encoding="utf-8").lower()
        forbidden = ("api_key", "private_key", "password", "database_url", "firebase_service_account")
        for token in forbidden:
            self.assertNotIn(token, text)

    def test_projects_html_section_exists(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="pd-grid"', html)
        self.assertIn('id="pd-detail"', html)
        self.assertIn('id="pd-search-input"', html)
        self.assertIn('src="./projects.js"', html)

    def test_projects_links_have_security_attributes(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="pd-page-link"', html)
        self.assertIn('id="pd-repo-link"', html)
        self.assertIn('aria-disabled="true"', html)
        self.assertIn('tabindex="-1"', html)

    def test_projects_detail_button_present(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('pd-card-detail-btn', script)

    def test_projects_undeployed_indicator_present(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('pd-card-undeployed', script)


if __name__ == "__main__":
    unittest.main()
