from __future__ import annotations
import json
import re
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "functions"
class GitHubLiveStaticContractTests(unittest.TestCase):
    def test_pages_function_route_and_libs_exist(self):
        for relative in ("api/github-status.js", "_lib/github-app-auth.js", "_lib/github-client.js", "_lib/github-status-service.js", "_lib/business-github-map.js", "_lib/cache.js", "_lib/response.js"):
            self.assertTrue((FUNCTIONS / relative).is_file(), relative)
    def test_routes_only_include_api(self):
        self.assertEqual(json.loads((ROOT / "_routes.json").read_text()), {"version": 1, "include": ["/api/*"], "exclude": []})
    def test_browser_live_script_is_deterministically_versioned(self):
        html = (ROOT / "index.html").read_text()
        self.assertIn('src="./github-live-status.js?v=auto-sync-v20260730-1"', html)
        self.assertNotIn("Date.now()", html)
    def test_csp_allows_only_same_origin_api(self):
        headers = (ROOT / "_headers").read_text()
        self.assertIn("connect-src 'self'", headers)
        self.assertNotRegex(headers, r"connect-src\s+(?:https:|\*|https://)")
    def test_browser_bundle_has_no_credential_binding_names_or_values(self):
        browser = (ROOT / "github-live-status.js").read_text()
        for name in ("GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID", "GITHUB_APP_PRIVATE_KEY_PKCS8", "GITHUB_STATUS_SNAPSHOT_KV", "Authorization", "Bearer "):
            self.assertNotIn(name, browser)
    def test_server_uses_fixed_graphql_origin_and_query(self):
        client = (FUNCTIONS / "_lib" / "github-client.js").read_text()
        query_builder = (FUNCTIONS / "_lib" / "business-github-query.js").read_text()
        self.assertIn('const API_BASE = "https://api.github.com"', client)
        self.assertIn('const GRAPHQL_URL = `${API_BASE}/graphql`', client)
        self.assertIn("statusCheckRollup", query_builder)
        self.assertIn("issue${n}: issue(number: ${n})", query_builder)
        self.assertIn("fallbackPr${m.fallbackPrNumber}: pullRequest(number: ${m.fallbackPrNumber})", query_builder)
        self.assertIn("issues(first: 1, states: OPEN)", query_builder)
        self.assertIn("pullRequests(first: 1, states: OPEN)", query_builder)
        self.assertIn("commits(last: 1)", query_builder)
        self.assertIn("contexts(first: 100)", query_builder)
        self.assertIn("draftPullRequests: search(query:", query_builder)
        self.assertNotIn("issues(states: OPEN)", query_builder + client)
        self.assertNotIn("pullRequests(states: OPEN)", query_builder + client)
        self.assertNotIn("repositoryPath", client)
    def test_kv_is_access_compatible_authoritative_cache(self):
        route = (FUNCTIONS / "api" / "github-status.js").read_text()
        cache = (FUNCTIONS / "_lib" / "cache.js").read_text()
        self.assertIn("GITHUB_STATUS_SNAPSHOT_KV", route)
        self.assertIn("cacheConfigurationMissingPayload", route)
        self.assertIn("CACHE_CONFIGURATION_MISSING", (FUNCTIONS / "_lib" / "response.js").read_text())
        self.assertIn("expirationTtl", cache)
        self.assertIn("setMemory(snapshot)", cache)
        self.assertLess(cache.index("this.memoryStore.set(SNAPSHOT_KEY, value)"), cache.index("await this.kv.put"))
        self.assertNotIn("caches.default", cache)
        self.assertNotIn("Cache API", cache)
    def test_token_and_refresh_single_flight_are_explicit(self):
        auth = (FUNCTIONS / "_lib" / "github-app-auth.js").read_text()
        service = (FUNCTIONS / "_lib" / "github-status-service.js").read_text()
        self.assertIn("this.inFlight", auth)
        self.assertIn("refreshFlights", service)
        self.assertIn("refreshSingleFlight", service)
    def test_rate_limit_is_normalized_without_general_retry(self):
        client = (FUNCTIONS / "_lib" / "github-client.js").read_text()
        self.assertIn("UPSTREAM_RATE_LIMITED", client)
        self.assertIn('response.status === 429', client)
        self.assertIn('response.status === 403', client)
        self.assertIn('response.status === 401 && retryAuth', client)
    def test_no_pat_or_write_github_methods(self):
        source = "\n".join(path.read_text() for path in FUNCTIONS.rglob("*.js")).lower()
        self.assertNotIn("personal access token", source)
        self.assertNotIn("gh auth", source)
        self.assertNotRegex(source, r"method:\s*[\"'](?:patch|put|delete)[\"']")
    def test_source_files_respect_500_line_policy(self):
        for path in list(FUNCTIONS.rglob("*.js")) + [ROOT / "github-live-status.js"]:
            self.assertLessEqual(len(path.read_text().splitlines()), 500, str(path))
    def test_api_rejects_query_parameters_and_non_get_methods(self):
        route = (FUNCTIONS / "api" / "github-status.js").read_text()
        self.assertIn("url.searchParams.keys()", route)
        self.assertIn("METHOD_NOT_ALLOWED", route)
        self.assertIn('Allow: "GET, HEAD"', route)
    def test_ui_does_not_assign_static_judgment_fields(self):
        browser = (ROOT / "github-live-status.js").read_text()
        self.assertNotRegex(browser, r"\.progress\s*=")
        self.assertNotRegex(browser, r"\.priority\s*=")
        self.assertNotRegex(browser, r"\.nextAction\s*=")
if __name__ == "__main__":
    unittest.main()
