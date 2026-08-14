from __future__ import annotations

import re
import unittest
from pathlib import Path


PORTFOLIO_DIR = Path(__file__).resolve().parents[1]
MANIFEST = PORTFOLIO_DIR / "business-manifest.js"
TRUTH_AUDIT = PORTFOLIO_DIR / "portfolio-truth-audit.js"


KNOWN_REPOSITORIES = {
    5: ("expanded-successor", "DanjiOn", "단지온", "skerishKang/02-danji-on", "https://github.com/skerishKang/02-danji-on"),
    23: ("external-implementation", "LoveBud", "LoveBud", "skerishKang/LoveBud", "https://github.com/skerishKang/LoveBud"),
    24: ("external-implementation", "LoveTree 3.0", "LoveTree 3.0", "skerishKang/lovetree3.0", "https://github.com/skerishKang/lovetree3.0"),
    25: ("external-implementation", "Love Matchmaking", "러브 매치메이킹", "skerishKang/401-love-match-making", "https://github.com/skerishKang/401-love-match-making"),
    30: ("expanded-successor", "400 AI Finder", "400-ai-finder", "skerishKang/400-ai-finder", "https://github.com/skerishKang/400-ai-finder"),
}

UNRESOLVED = {
    3: ("external-parallel", "External / Parallel Track", "외부·병렬 작업"),
    26: ("integrated-successor", "Ieeon", "이어온"),
    27: ("integrated-successor", "Sasillo", "사실로"),
    28: ("integrated-successor", "Ieeon", "이어온"),
    31: ("integrated-successor", "Sasillo", "사실로"),
    50: ("integrated-successor", "Ieeon", "이어온"),
}

OBSOLETE_INTERNAL_WORKSPACES = {
    26: "reference/business-26-company-memory-v1/",
    27: "reference/business-27-evidence-studio-v1/",
    28: "reference/business-28-decision-archive-v1/",
    30: "reference/business-30-civic-ai-navigator-v1/",
    31: "reference/business-31-public-procedure-data-v1/",
}


class ExternalSuccessorManifestTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = MANIFEST.read_text(encoding="utf-8")
        cls.truth_audit = TRUTH_AUDIT.read_text(encoding="utf-8")

    def entry(self, number: int) -> str:
        match = re.search(rf'identity\(\{{[^\n]*n:{number},[^\n]*\}}\)', self.manifest)
        self.assertIsNotNone(match, f"missing manifest entry B{number}")
        return match.group(0)

    def test_known_external_repositories_are_static_manifest_truth(self) -> None:
        for number, (kind, title, korean, workspace, repository) in KNOWN_REPOSITORIES.items():
            entry = self.entry(number)
            self.assertIn('st:"external"', entry)
            self.assertIn('pc:"expanded-successor"', entry)
            self.assertIn(f'bk:"{kind}"', entry)
            self.assertIn(f'sn:"{title}"', entry)
            self.assertIn(f'sk:"{korean}"', entry)
            self.assertIn(f'w:"{workspace}"', entry)
            self.assertIn(f'sr:"{repository}"', entry)

    def test_unresolved_successors_do_not_invent_repository_or_workspace(self) -> None:
        for number, (kind, title, korean) in UNRESOLVED.items():
            entry = self.entry(number)
            self.assertIn('st:"external"', entry)
            self.assertIn('pc:"expanded-successor"', entry)
            self.assertIn(f'bk:"{kind}"', entry)
            self.assertIn(f'sn:"{title}"', entry)
            self.assertIn(f'sk:"{korean}"', entry)
            self.assertNotIn(' sr:', entry)
            self.assertNotRegex(entry, re.compile(r'\sw:"'))

    def test_obsolete_internal_reference_workspaces_are_not_current_authority(self) -> None:
        for number, workspace in OBSOLETE_INTERNAL_WORKSPACES.items():
            self.assertNotIn(workspace, self.entry(number))
        self.assertNotIn('reference/business-50', self.entry(50))

    def test_b3_is_conservative_external_parallel_without_invented_successor(self) -> None:
        entry = self.entry(3)
        self.assertIn('a:NA.CANONICAL', entry)
        self.assertIn('bk:"external-parallel"', entry)
        self.assertNotIn(' sr:', entry)
        self.assertNotRegex(entry, re.compile(r'\sw:"'))

    def test_b5_keeps_canonical_number_while_external_implementation_moves_to_danjion(self) -> None:
        entry = self.entry(5)
        self.assertIn('a:NA.CANONICAL', entry)
        self.assertIn('w:"skerishKang/02-danji-on"', entry)

    def test_runtime_truth_layer_no_longer_repairs_stable_identity(self) -> None:
        self.assertNotIn("var BOUNDARIES", self.truth_audit)
        self.assertIn("business.boundaryKind", self.truth_audit)
        self.assertIn("business.successorRepository", self.truth_audit)
        self.assertNotIn("business.workspace =", self.truth_audit)
        self.assertNotIn("business.lifecycle =", self.truth_audit)
        self.assertNotIn("business.state =", self.truth_audit)
        self.assertIn('business.uiStatus = "NOT_APPLICABLE"', self.truth_audit)
        self.assertIn('business.uxStatus = "NOT_APPLICABLE"', self.truth_audit)
        self.assertIn('business.backendStatus = "NOT_APPLICABLE"', self.truth_audit)


if __name__ == "__main__":
    unittest.main()
