from __future__ import annotations

import re
import unittest
from pathlib import Path


PORTFOLIO_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PORTFOLIO_DIR.parents[1]
MANIFEST = PORTFOLIO_DIR / "business-manifest.js"
APPS_README = REPO_ROOT / "apps" / "README.md"
BACKLOG = REPO_ROOT / "docs" / "portfolio" / "BUSINESS_CANDIDATE_BACKLOG.md"


class Business14And54IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = MANIFEST.read_text(encoding="utf-8")
        cls.apps_readme = APPS_README.read_text(encoding="utf-8")
        cls.backlog = BACKLOG.read_text(encoding="utf-8")

    def test_manifest_has_current_b14_and_b54_identity(self) -> None:
        self.assertRegex(
            self.manifest,
            re.compile(
                r'n:14,\s*s:"korean-ai-platform",\s*t:"Korean AI Platform",'
                r'\s*k:"한국형 AI 모델 플랫폼"'
            ),
        )
        self.assertRegex(
            self.manifest,
            re.compile(
                r'n:54,\s*s:"korean-ai-code-agent",\s*t:"Korean AI Code Agent",'
                r'\s*k:"한국형 AI 코드 에이전트"'
            ),
        )

    def test_manifest_keeps_b54_proposed_while_integrated_workspace_is_current(self) -> None:
        match = re.search(r'identity\(\{[^\n]*n:54,[^\n]*\}\)', self.manifest)
        self.assertIsNotNone(match)
        entry = match.group(0)
        self.assertIn('a:NA.PROPOSED', entry)
        self.assertIn('l:"mvp_vertical_slice"', entry)
        self.assertIn('st:"review"', entry)
        self.assertIn('w:"apps/korean-ai-code-agent/"', entry)

    def test_apps_readme_keeps_router_inside_b14_and_b54_as_client(self) -> None:
        self.assertIn("Business 14 is the public model-access platform.", self.apps_readme)
        self.assertIn("routing is an internal Business 14 capability", self.apps_readme)
        self.assertIn(
            "Proposed Business 54 is **Korean AI Code Agent / 한국형 AI 코드 에이전트**",
            self.apps_readme,
        )
        self.assertIn("consumes Business 14", self.apps_readme)
        self.assertIn("`apps/korean-ai-code-agent/` is not present on current `main`", self.apps_readme)
        self.assertIn("Draft implementation work does not make it a current workspace", self.apps_readme)

    def test_candidate_backlog_uses_current_b54_slug_and_preserves_old_alias_only_as_history(self) -> None:
        self.assertRegex(
            self.backlog,
            re.compile(
                r'\| 54 \| `korean-ai-code-agent` \| Korean AI Code Agent / '
                r'한국형 AI 코드 에이전트 \| proposed-number \|'
            ),
        )
        self.assertNotRegex(
            self.backlog,
            re.compile(r'\| 54 \| `ai-model-router` \|'),
        )
        self.assertIn(
            "The former B54 `ai-model-router / AI Model Router` identity is superseded historical terminology.",
            self.backlog,
        )
        self.assertIn("internal **Router Core** of Business 14", self.backlog)


if __name__ == "__main__":
    unittest.main()
