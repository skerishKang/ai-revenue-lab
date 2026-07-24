from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PortfolioConsoleStaticTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for relative in ("index.html", "styles.css", "businesses.js", "quick-launch.js", "app.js", "_headers", "README.md"):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_html_has_private_and_noindex_contracts(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('name="robots" content="noindex,nofollow,noarchive"', html)
        self.assertIn("PRIVATE ADMIN", html)
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

    def test_quick_launch_file_has_data_and_render(self) -> None:
        script = (ROOT / "quick-launch.js").read_text(encoding="utf-8")
        self.assertIn("window.ARL_QUICK_LAUNCH", script)
        self.assertIn("renderQuickLaunch", script)
        self.assertIn("verified", script)
        self.assertIn("planned", script)

    def test_quick_launch_html_section_exists(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="quick-launch-list"', html)
        self.assertIn('class="ql-heading"', html)
        self.assertIn('src="./quick-launch.js"', html)

    def test_quick_launch_indicators(self) -> None:
        script = (ROOT / "quick-launch.js").read_text(encoding="utf-8")
        self.assertIn("열기", script)
        self.assertIn("준비 중", script)

    def test_quick_launch_active_links_have_correct_attributes(self) -> None:
        script = (ROOT / "quick-launch.js").read_text(encoding="utf-8")
        self.assertIn('target="_blank"', script)
        self.assertIn('rel="noopener noreferrer"', script)

    def test_quick_launch_planned_items_inert(self) -> None:
        script = (ROOT / "quick-launch.js").read_text(encoding="utf-8")
        self.assertIn('aria-disabled="true"', script)
        self.assertIn('tabindex="-1"', script)

    def test_quick_launch_verified_urls_use_https(self) -> None:
        script = (ROOT / "quick-launch.js").read_text(encoding="utf-8")
        urls = re.findall(r'url:\s*"(https?[^"]+)"', script)
        self.assertEqual(len(urls), 8)
        for url in urls:
            self.assertTrue(url.startswith("https://"), url)

    def test_quick_launch_item_counts(self) -> None:
        script = (ROOT / "quick-launch.js").read_text(encoding="utf-8")
        self.assertEqual(script.count('state: "verified"'), 8)
        self.assertEqual(script.count('state: "planned"'), 5)

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


if __name__ == "__main__":
    unittest.main()
