from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PortfolioConsoleStaticTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for relative in ("index.html", "styles.css", "businesses.js", "app.js", "projects.js", "_headers", "README.md", "playwright.config.js"):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_quick_launch_file_deleted(self) -> None:
        self.assertFalse((ROOT / "quick-launch.js").is_file(), "quick-launch.js should be deleted")

    def test_quick_launch_removed_from_html(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("quick-launch", html)
        self.assertNotIn("ql-heading", html)
        self.assertNotIn("ql-list", html)
        self.assertNotIn("ql-item", html)
        self.assertNotIn("quick-launch.js", html)

    def test_quick_launch_removed_from_app_js(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("quickLaunch", script)
        self.assertNotIn("renderQuickLaunch", script)

    def test_quick_launch_removed_from_styles(self) -> None:
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn("quick-launch", css)

    def test_html_has_private_and_noindex_contracts(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('name="robots" content="noindex,nofollow,noarchive"', html)
        self.assertIn('id="sidebar-range"', html)
        self.assertIn('id="header-count"', html)
        self.assertIn('id="theme-toggle"', html)

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
        self.assertIn("openBusinessDialog", script)
        self.assertIn("filteredBusinesses", script)
        self.assertIn("renderBusinessIndex", script)
        self.assertNotIn("fetch(", script)

    def test_projects_file_exists(self) -> None:
        self.assertTrue((ROOT / "projects.js").is_file(), "projects.js")

    def test_projects_has_13_items(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        ids = re.findall(r'^\s{4}id:\s*"([^"]+)"', script, re.MULTILINE)
        self.assertEqual(len(ids), 13)

    def test_projects_all_have_required_fields(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        required = ("purpose", "repositoryLabel", "workspace", "stage", "progressNote", "currentWork", "nextAction", "lastVerified")
        for field in required:
            count = len(re.findall(rf'{field}:\s*"', script))
            self.assertGreaterEqual(count, 13, f"{field} count")

    def test_projects_all_have_data_contract_fields(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        fields = ("developmentMode", "progressBasis", "milestoneStatus", "milestoneTasks", "currentMilestone", "blockers", "futureRoadmap")
        for field in fields:
            count = len(re.findall(rf'{field}', script))
            self.assertGreaterEqual(count, 13, f"{field} count")

    def test_projects_development_mode_vocabulary(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        modes = set(re.findall(r'developmentMode:\s*"([^"]+)"', script))
        allowed = {"not-started", "active-development", "needs-improvement", "maintenance", "complete", "paused"}
        self.assertTrue(modes.issubset(allowed), f"Unexpected modes: {modes - allowed}")

    def test_projects_milestone_status_vocabulary(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        statuses = set(re.findall(r'milestoneStatus:\s*"([^"]+)"', script))
        allowed = {"defined", "undefined"}
        self.assertTrue(statuses.issubset(allowed), f"Unexpected milestoneStatus: {statuses - allowed}")

    def test_projects_stage_vocabulary(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        stages = set(re.findall(r'stage:\s*"([^"]+)"', script))
        allowed = {"planned", "building", "review", "live", "paused"}
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

    def test_projects_living_fiction_pageurl_null(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        self.assertIn('pageUrl: null', script)
        self.assertNotIn('padiemipu--ai-revenue-living-fiction-web.modal.run', script)

    def test_projects_no_secret_like_literals(self) -> None:
        text = (ROOT / "projects.js").read_text(encoding="utf-8").lower()
        forbidden = ("api_key", "private_key", "password", "database_url", "firebase_service_account")
        for token in forbidden:
            self.assertNotIn(token, text)

    def test_projects_html_section_exists(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="pd-grid"', html)
        self.assertIn('id="project-dialog"', html)
        self.assertIn('id="sf-search-input"', html)
        self.assertIn('src="./projects.js"', html)

    def test_projects_detail_button_present(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('pd-card-detail-btn', script)

    def test_projects_no_role_button_on_card(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('role="button"', script)
        self.assertNotIn('role="link"', script)

    def test_projects_no_window_open(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('window.open', script)

    def test_projects_use_real_anchor_links(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('pd-card-service-link', script)
        self.assertIn('href=', script)
        self.assertIn('target="_blank"', script)
        self.assertIn('rel="noopener noreferrer"', script)

    def test_projects_lovebud_evidence_correct(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        self.assertIn("#3451 CLOSED", script)
        self.assertIn("#3481 CLOSED", script)
        self.assertIn("PR #3531 merged", script)
        self.assertIn("e0ff1b2a4089c31fe4adb3e9c082ef9a4499a1cf", script)
        self.assertIn("#3425 OPEN", script)
        self.assertIn("#3458 OPEN", script)

    def test_projects_korean_ai_platform_relflects_pr142(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        self.assertIn("PR #142", script)
        self.assertIn("Provider registry", script)
        self.assertIn("ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace", script)

    def test_projects_businesses_korean_ai_platform_updated(self) -> None:
        script = (ROOT / "businesses.js").read_text(encoding="utf-8")
        self.assertIn("PR #142 merged", script)
        self.assertIn("dedicated Worker", script)

    def test_projects_living_fiction_no_issue139(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        self.assertNotIn("Issue #139", script)
        self.assertNotIn("#139", script)

    def test_projects_ai_finder_1181_deferred(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        self.assertIn("1181", script)
        self.assertIn("deferred", script)

    def test_playwright_config_platform_specific(self) -> None:
        cfg = (ROOT / "playwright.config.js").read_text(encoding="utf-8")
        self.assertIn("process.platform", cfg)
        self.assertIn("python -m http.server 4173", cfg)
        self.assertIn("python3 -m http.server 4173", cfg)

    def test_validate_projects_file_exists(self) -> None:
        self.assertTrue((ROOT / "tests" / "validate_projects.js").is_file())

    def test_validate_projects_uses_vm(self) -> None:
        content = (ROOT / "tests" / "validate_projects.js").read_text(encoding="utf-8")
        self.assertIn("vm", content)
        self.assertIn("new vm.Script", content)
        self.assertIn("window.ARL_PROJECTS", content)

    def test_korean_ai_platform_business_14_github_label(self) -> None:
        script = (ROOT / "businesses.js").read_text(encoding="utf-8")
        self.assertNotIn("Draft PR #79", script)
        self.assertIn('githubLabel: "PR #142 merged"', script)

    def test_lovebud_done_tasks_3_open_3(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        done_count = script.count('done: true')
        self.assertGreaterEqual(done_count, 7)

    def test_sidebar_has_four_view_buttons(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-view="projects"', html)
        self.assertIn('data-view="search"', html)
        self.assertIn('data-view="work"', html)
        self.assertIn('data-view="business"', html)
        self.assertIn('class="view-nav-item', html)

    def test_menu_button_is_actual_button(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('<button', html)
        self.assertIn('data-view="work"', html)

    def test_work_view_container_exists(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="view-work"', html)

    def test_work_view_hidden_by_default(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        idx = html.index('id="view-work"')
        self.assertIn('hidden', html[idx:idx+50])

    def test_work_queue_container_exists(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="work-queue"', html)

    def test_work_summary_exists(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="work-summary"', html)

    def test_is_work_in_progress_functions_exist(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("function isWIP", script)
        self.assertIn("function isReviewGroup", script)
        self.assertIn("function isActiveGroup", script)

    def test_projects_js_unchanged(self) -> None:
        script = (ROOT / "projects.js").read_text(encoding="utf-8")
        self.assertIn("pc-wip-screen", script)
        self.assertEqual(script.count("done: true"), 11)

    def test_businesses_js_unchanged(self) -> None:
        script = (ROOT / "businesses.js").read_text(encoding="utf-8")
        self.assertIn("window.ARL_BUSINESSES", script)

    def test_search_controls_exist(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="sf-search-input"', html)
        self.assertIn('id="sf-stage-filter"', html)
        self.assertIn('id="sf-devmode-filter"', html)
        self.assertIn('id="sf-sort-filter"', html)
        self.assertIn('id="sf-reset-filter"', html)

    def test_project_status_has_aria_current(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('aria-current="page"', html)

    def test_theme_localstorage_in_app_js(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("localStorage", script)
        self.assertIn("arl-portfolio-theme", script)

    def test_no_cookie_in_app_js(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("cookie", script.lower())

    def test_no_fetch_in_app_js(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("fetch(", script)

    def test_view_sections_exist(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="view-projects"', html)
        self.assertIn('id="view-search"', html)
        self.assertIn('id="view-work"', html)
        self.assertIn('id="view-business"', html)

    def test_dialog_elements_exist(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('<dialog id="project-dialog"', html)
        self.assertIn('<dialog id="business-dialog"', html)

    def test_theme_inline_script_exists(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("arl-portfolio-theme", html)
        self.assertIn("data-theme", html)

    def test_no_decorative_side_nav_in_html(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('class="side-nav"', html)
        self.assertNotIn('data-view="deployments"', html)
        self.assertNotIn('data-view="github"', html)
        self.assertNotIn('data-view="models"', html)
        self.assertNotIn('data-view="registry"', html)

    def test_no_metric_grid_in_html(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('class="metric-grid"', html)
        self.assertNotIn('class="metric-card"', html)

    def test_no_priority_actions_in_html(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('class="priority-item"', html)
        self.assertNotIn('id="priority-list"', html)

    def test_no_business_table_in_html(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="business-table-body"', html)

    def test_no_detail_panel_in_html(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="detail-panel"', html)
        self.assertNotIn('id="pd-detail"', html)

    def test_no_sync_state_in_html(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('class="sync-state"', html)
        self.assertNotIn('id="refresh-button"', html)

    def test_header_count_exists_and_dynamic(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("updateHeaderCount", script)
        self.assertIn("#header-count", script)

    def test_format_functions_exist(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("function formatProjectUnitCount", script)
        self.assertIn("function formatResultCount", script)

    def test_business_index_functions_exist(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("filteredBusinesses", script)
        self.assertIn("renderBusinessIndex", script)
        self.assertIn("openBusinessDialog", script)

    def test_open_project_dialog_exists(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("openProjectDialog", script)
        self.assertIn("dialog.showModal", script)
        self.assertIn("project-dialog", script)

    def test_card_biz_number_exists(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("cardBizNumber", script)
        self.assertIn("pd-card-biznumber", script)

    def test_switch_view_function_exists(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("function switchView", script)
        self.assertIn('viewMap = { projects', script)
        self.assertIn('aria-current', script)

    def test_theme_toggle_function_exists(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("function toggleTheme", script)
        self.assertIn('localStorage.setItem("arl-portfolio-theme"', script)

    def test_no_github_api_or_issue_data(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("GitHub Issue", script)
        self.assertNotIn("github.com", script)

    def test_no_progress_bar_hardcoded(self) -> None:
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("progressPercentFixed", script)
        self.assertNotIn("hardcodedProgress", script)


if __name__ == "__main__":
    unittest.main()
