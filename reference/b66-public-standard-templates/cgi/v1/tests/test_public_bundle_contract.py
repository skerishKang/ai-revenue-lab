"""Offline SHA-256 and public-bundle boundaries for CGI standard templates."""
import hashlib
import json
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "PUBLIC_RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
DENY = {".ttf",".ttc",".otf",".woff",".woff2",".pem",".p12",".key",".env"}

class PublicBundleTest(unittest.TestCase):
    def test_authority(self):
        self.assertTrue(MANIFEST["owner_publication_authorized"])
        self.assertFalse(MANIFEST["runtime_activation"])
        self.assertFalse(MANIFEST["unrelated_customer_uploaded_templates_in_public_git"])
        self.assertTrue(MANIFEST["standard_reference_includes_owner_authorized_source_values"])
        self.assertEqual(MANIFEST["preferred_template"], "sol61")
        self.assertIn("not_customer_safe", MANIFEST["glm53_scope"])
        self.assertTrue(MANIFEST["sanitized_source_workbook_is_not_byte_identical_to_original"])
        self.assertTrue(MANIFEST["historical_sol_certificate_refers_to_original_private_bundle"])

    def test_hashes_and_exact_allowlist(self):
        entries=MANIFEST["artifacts"]
        self.assertEqual(len(entries),18)
        control={"README.md","PUBLIC_RELEASE_MANIFEST.json","tests/test_public_bundle_contract.py"}
        found={p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
        self.assertEqual(found-control,set(entries))
        for name,meta in entries.items():
            with self.subTest(name=name):
                p=ROOT/name
                self.assertEqual(p.stat().st_size,meta["bytes"])
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),meta["sha256"])
                self.assertNotIn(p.suffix.lower(),DENY)
                self.assertNotIn("/output/","/"+name)

    def test_owner_approved_reference_pdf_original(self):
        raw=(ROOT/"source/original.pdf").read_bytes()
        self.assertTrue(raw.startswith(b"%PDF"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST["source_original_pdf_sha256"])

    def test_public_workbook_has_no_external_local_links(self):
        with zipfile.ZipFile(ROOT/"source/original-public.xlsx") as z:
            self.assertIsNone(z.testzip())
            self.assertIn("xl/workbook.xml",z.namelist())
            self.assertFalse(any("externalLinks" in n for n in z.namelist()))
            for name in z.namelist():
                if name.endswith(".rels"):
                    self.assertNotIn(b'TargetMode="External"',z.read(name))

    def test_no_private_machine_paths_in_template(self):
        for rel in ("sol61/template/template.json","glm53/template/quote_template.json"):
            s=json.dumps(json.loads((ROOT/rel).read_text(encoding="utf-8")),ensure_ascii=False)
            self.assertNotRegex(s,r"(?i)[CDEG]:[/\\]")
        engine=(ROOT/"sol61/engine/quote_template.py").read_text(encoding="utf-8")
        self.assertIn("DEFAULT_NODE = Path('node')",engine)
        self.assertNotIn("C:/Users/",engine)
        self.assertFalse(any(p.suffix.lower() in DENY for p in ROOT.rglob("*") if p.is_file()))

    def test_glm_is_comparator_and_fonts_are_not_redistributed(self):
        self.assertTrue((ROOT/"glm53/template/base_document.pdf").is_file())
        self.assertTrue((ROOT/"sol61/template/program.zlib").is_file())
        self.assertFalse(list(ROOT.rglob("*.ttf"))+list(ROOT.rglob("*.ttc")))
        self.assertFalse(list(ROOT.rglob("*output*/*.pdf")))

if __name__=="__main__":
    unittest.main(verbosity=2)
