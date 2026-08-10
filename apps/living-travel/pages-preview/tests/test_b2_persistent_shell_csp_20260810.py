from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
HEADERS = SITE / "_headers"
SHELL_JS = SITE / "assets" / "b2-shell-20260810.js"


def _policies() -> dict[str, str]:
    lines = HEADERS.read_text(encoding="utf-8").splitlines()
    current = ""
    result: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if line in {"/*", "/demo/*", "/operator/*", "/staging/*"}:
            current = line
            continue
        if line.startswith("Content-Security-Policy:") and current:
            result[current] = line.split(":", 1)[1].strip()
    return result


def _directive(policy: str, name: str) -> str:
    match = re.search(rf"(?:^|;\s*){re.escape(name)}\s+([^;]+)", policy)
    if not match:
        raise AssertionError(f"missing {name}: {policy}")
    return match.group(1)


class TestPersistentShellCsp(unittest.TestCase):
    def test_expected_policy_blocks_exist(self) -> None:
        policies = _policies()
        self.assertEqual(set(policies), {"/*", "/demo/*", "/operator/*", "/staging/*"})

    def test_global_preview_allows_only_same_origin_script(self) -> None:
        script = _directive(_policies()["/*"], "script-src")
        self.assertEqual(script, "'self'")
        self.assertNotIn("'unsafe-inline'", script)
        self.assertNotIn("'unsafe-eval'", script)

    def test_demo_and_operator_allow_local_shell_plus_existing_inline_flow(self) -> None:
        policies = _policies()
        for scope in ("/demo/*", "/operator/*"):
            script = _directive(policies[scope], "script-src")
            self.assertIn("'self'", script, scope)
            self.assertIn("'unsafe-inline'", script, scope)
            self.assertNotIn("'unsafe-eval'", script, scope)
            self.assertNotRegex(script, r"https?://", scope)

    def test_staging_policy_is_not_broadened(self) -> None:
        script = _directive(_policies()["/staging/*"], "script-src")
        self.assertIn("'self'", script)
        self.assertIn("https://www.gstatic.com", script)
        self.assertNotIn("'unsafe-inline'", script)
        self.assertNotIn("'unsafe-eval'", script)

    def test_shell_script_is_local_navigation_only(self) -> None:
        js = SHELL_JS.read_text(encoding="utf-8")
        self.assertIn("lt-nav--persistent", js)
        self.assertIn("30초 사용법", js)
        for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon"):
            self.assertNotIn(forbidden, js)
        self.assertNotRegex(js, r"https?://")

    def test_every_page_that_loads_shell_is_covered_by_compatible_policy(self) -> None:
        shell_pages: list[Path] = []
        for page in SITE.rglob("*.html"):
            text = page.read_text(encoding="utf-8")
            if "b2-shell-20260810.js" in text:
                shell_pages.append(page)
        self.assertGreaterEqual(len(shell_pages), 10)
        policies = _policies()
        for page in shell_pages:
            rel = page.relative_to(SITE).as_posix()
            if rel.startswith("staging/"):
                scope = "/staging/*"
            elif rel.startswith("demo/"):
                scope = "/demo/*"
            elif rel.startswith("operator/"):
                scope = "/operator/*"
            else:
                scope = "/*"
            script = _directive(policies[scope], "script-src")
            self.assertIn("'self'", script, f"{rel} is not allowed to load the local shell")


if __name__ == "__main__":
    unittest.main()
