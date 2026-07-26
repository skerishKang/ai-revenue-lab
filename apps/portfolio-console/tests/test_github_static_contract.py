from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "functions"


class GitHubLiveStaticContractTests(unittest.TestCase):
    def test_pages_function_route_and_libs_exist(self) -> None:
        required = (
            "api/github-status.js",
            "_lib/github-app-auth.js",
            "_lib/github-client.js",
            "_lib/github-status-service.js",
            "_lib/business-github-map.js",
            "_lib/cache.js",
            "_lib/response.js",
        )
        for relative in required:
            self.assertTrue((FUNCTIONS / relative).is_file(), relative)

    def test_routes_only_include_api(self) -> None:
        routes = json.loads((ROOT / "_routes.json").read_text(encoding="utf-8"))
        self.assertEqual(routes, {"version": 1, "include": ["/api/*"], "exclude": []})

    def test_browser_live_script_is_deterministically_versioned(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="./github-live-status.js?v=portfolio-github-live-20260727-2"', html)
        self.assertNotIn("Date.now()", html)

    def test_csp_allows_same_origin_api_but_not_external_connect(self) -> None:
        headers = (ROOT / "_headers").read_text(encoding="utf-8")
        self.assertIn("connect-src 'self'", headers)
        self.assertNotRegex(headers, r"connect-src\s+(?:https:|\*|https://)")

    def test_browser_bundle_has_no_credential_binding_names_or_values(self) -> None:
        browser = (ROOT / "github-live-status.js").read_text(encoding="utf-8")
        for name in (
            "GITHUB_APP_ID",
            "GITHUB_APP_INSTALLATION_ID",
            "GITHUB_APP_PRIVATE_KEY_PKCS8",
            "Authorization",
            "Bearer ",
        ):
            self.assertNotIn(name, browser)

    def test_server_host_is_fixed_to_api_github_com(self) -> None:
        client = (FUNCTIONS / "_lib" / "github-client.js").read_text(encoding="utf-8")
        self.assertIn('const API_BASE = "https://api.github.com"', client)
        self.assertIn("url.origin !== API_BASE", client)

    def test_no_pat_or_write_github_methods(self) -> None:
        source = "\n".join(path.read_text(encoding="utf-8") for path in FUNCTIONS.rglob("*.js")).lower()
        self.assertNotIn("personal access token", source)
        self.assertNotIn("gh auth", source)
        self.assertNotRegex(source, r"method:\s*[\"'](?:patch|put|delete)[\"']")

    def test_source_files_respect_500_line_policy(self) -> None:
        paths = list(FUNCTIONS.rglob("*.js")) + [ROOT / "github-live-status.js"]
        for path in paths:
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(line_count, 500, f"{path.relative_to(ROOT)}: {line_count}")

    def test_api_rejects_query_parameters_and_non_get_methods(self) -> None:
        route = (FUNCTIONS / "api" / "github-status.js").read_text(encoding="utf-8")
        self.assertIn("url.searchParams.keys()", route)
        self.assertIn("METHOD_NOT_ALLOWED", route)
        self.assertIn('Allow: "GET, HEAD"', route)

    def test_ui_does_not_assign_progress_or_priority(self) -> None:
        browser = (ROOT / "github-live-status.js").read_text(encoding="utf-8")
        self.assertNotRegex(browser, r"\.progress\s*=")
        self.assertNotRegex(browser, r"\.priority\s*=")
        self.assertNotRegex(browser, r"\.nextAction\s*=")


if __name__ == "__main__":
    unittest.main()
