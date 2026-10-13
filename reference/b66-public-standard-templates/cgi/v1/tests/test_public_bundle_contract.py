"""Public-source privacy regression for private CGI customer templates.

This intentionally runs at the legacy test path so the existing mandatory CI
workflow tests the *new* nonpublication contract instead of accidentally
recreating the revoked public bundle.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {".pdf", ".xlsx", ".xls", ".docx", ".png", ".jpeg", ".jpg", ".emf", ".zlib", ".zip"}

class PublicBundleTest(unittest.TestCase):
    def test_original_and_compiled_assets_are_not_public(self):
        forbidden = [
            p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
            if p.is_file() and p.suffix.lower() in FORBIDDEN_SUFFIXES
        ]
        self.assertEqual(forbidden, [])

    def test_revoked_release_manifest_is_not_public(self):
        self.assertFalse((ROOT / "PUBLIC_RELEASE_MANIFEST.json").exists())
        self.assertTrue((ROOT / "README.md").exists())
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("SOURCE_PUBLICATION_AUTHORITY=REVOKED_BY_OWNER_2026-10-14", text)
        self.assertIn("PUBLIC_REPOSITORY_SOURCE_ARTIFACTS=NONE", text)

    def test_cgi_specific_source_directories_are_empty(self):
        for relative in ("source", "sol61", "glm53"):
            path = ROOT / relative
            if path.exists():
                self.assertFalse([item for item in path.rglob("*") if item.is_file()])

if __name__ == "__main__":
    unittest.main()
