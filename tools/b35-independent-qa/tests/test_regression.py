#!/usr/bin/env python3
"""Regression fixtures for B35 Independent QA harness fail-closed behavior (C4).

Covers:
- CUSTOMER_SEND_READY=true => required verdict FAIL + overall FAIL
- forbidden customer claim => required verdict FAIL + overall FAIL
- missing/wrong product authority SHA => SOURCE_MAPPING_FAIL
- stale current claim + other file historical disclaimer => STALE_ARTIFACT_REJECTION_FAIL (per-file, not global)
- "성과를 보장하지 않는다" => allowed (no false positive)
- dependency/file/tool unavailable => never inferred PASS
- price hypothesis violation => STALE_FAIL + overall FAIL
"""

import json
import tempfile
import unittest
from pathlib import Path
import sys

# Ensure tools/b35-independent-qa is importable
TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))

import validate_b35_independent_qa as v

PRODUCT_COMMIT = v.PRODUCT_COMMIT
ACCEPTED_SOURCE_REVISION = v.ACCEPTED_SOURCE_REVISION


def make_exact_trace_fixture(tmp: Path, source_rev: str, generator_rev: str,
                             product_contract_exists: bool = True):
    """Minimal fail-closed fixture for check_exact_revision_trace.

    Builds a package with one real output file + matching manifest hashes so
    that only the field under test determines PASS/FAIL. Returns
    (commercial_root, package_root, product_contract_path, manifest_path).
    """
    import hashlib

    comm = tmp / "commercial_exact"
    comm.mkdir(parents=True, exist_ok=True)
    (comm / "CURRENT_PRODUCT_AUTHORITY.md").write_text(
        f"PRODUCT_COMMIT={PRODUCT_COMMIT}\n", encoding="utf-8")

    pkg = tmp / "exact_pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    out = pkg / "dummy_output.txt"
    out.write_text("hello exact trace", encoding="utf-8")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    manifest_data = {
        "SOURCE_REVISION": source_rev,
        "PRODUCT_AUTHORITY_REVISION": PRODUCT_COMMIT,
        "GENERATOR_REVISION": generator_rev,
        "OUTPUT_FILE_LIST": ["dummy_output.txt"],
        "OUTPUT_HASHES": {"dummy_output.txt": digest},
    }
    manifest_path = pkg / "MANIFEST_V3_1.json"
    manifest_path.write_text(
        json.dumps(manifest_data, ensure_ascii=False, indent=2),
        encoding="utf-8")

    if product_contract_exists:
        pc = tmp / "PRODUCT_CONTRACT.md"
        pc.write_text("# PRODUCT_CONTRACT\nauthority: frozen\n", encoding="utf-8")
    else:
        # Intentionally do NOT create this file: tests the actual authority
        # file dependency missing, not a SOURCE_MAPPING string edit.
        pc = tmp / "MISSING_PRODUCT_CONTRACT.md"
        if pc.exists():
            pc.unlink()
    return comm, pkg, pc, manifest_path

def make_commercial_with_sources(tmp: Path, correct_sha=True):
    comm = tmp / "commercial"
    comm.mkdir(parents=True, exist_ok=True)
    (comm / "tests").mkdir(exist_ok=True)
    # Minimal required commercial files
    for f in ["CURRENT_PRODUCT_AUTHORITY.md", "README.md", "SOURCES.md",
              "01-one-page-offer.md", "02-ten-page-proposal.md", "03-diagnostic-questionnaire.md",
              "04-six-week-pilot-plan.md", "05-statement-of-work-draft.md", "06-risk-and-data-annex.md",
              "07-kpi-measurement-framework.md", "08-customer-qualification-scorecard.md"]:
        (comm / f).write_text("placeholder", encoding="utf-8")
    # Make CURRENT_PRODUCT_AUTHORITY contain product commit if correct
    if correct_sha:
        (comm / "CURRENT_PRODUCT_AUTHORITY.md").write_text(f"PRODUCT_COMMIT={PRODUCT_COMMIT}\n파디엠\n", encoding="utf-8")
    else:
        (comm / "CURRENT_PRODUCT_AUTHORITY.md").write_text("WRONG_SHA=0000000000000000000000000000000000000000\n", encoding="utf-8")
    (comm / "SOURCES.md").write_text("### SRC-01\n검증 상태: VERIFIED\n원문 상세 URL: https://example.com/nttSeqNo=123\n", encoding="utf-8")
    (comm / "tests" / "validate_sales_package.py").write_text("# dummy", encoding="utf-8")
    # README with price hypothesis
    (comm / "README.md").write_text("가격은 시장 검증 전 가설\n300만–500만원", encoding="utf-8")
    return comm

def make_package_with_mapping(tmp: Path, package_content: dict = None, source_mapping_extra: str = ""):
    pkg = tmp / "package"
    pkg.mkdir(parents=True, exist_ok=True)
    # Create required families minimal
    for f in ["Business35_Master_Proposal_10p.pptx", "Business35_Master_Proposal_10p.pdf",
              "Business35_OnePage_Offer_Source.pptx", "Business35_OnePage_Offer.pdf",
              "Business35_Diagnostic_Questionnaire.docx", "Business35_Diagnostic_Questionnaire.pdf",
              "Business35_Pilot_Quote_Template.xlsx",
              "Business35_Customer_Meeting_Script.md", "Business35_Followup_Email_Templates.md",
              "CUSTOMIZATION_CHECKLIST.md", "README.md"]:
        # create dummy files
        p = pkg / f
        if f.endswith((".pptx", ".pdf", ".docx", ".xlsx")):
            p.write_bytes(b"dummy")
        else:
            p.write_text("dummy", encoding="utf-8")
    # SOURCE_MAPPING.md with correct markers
    sm_text = f"""# SOURCE_MAPPING
PRODUCT_COMMIT={PRODUCT_COMMIT}
PRODUCT_CONTRACT=reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md
CURRENT_PRODUCT_AUTHORITY=docs/commercial/business-35-ai-media-education-dx/CURRENT_PRODUCT_AUTHORITY.md
파디엠
PRE_V3_1 / STALE_FOR_SEND / HISTORICAL_ONLY
Slide 1 -> test
Slide 2 -> test
Slide 3 -> test
Slide 4 -> test
Slide 5 -> test
Slide 6 -> test
Slide 7 -> test
Slide 8 -> test
Slide 9 -> test
Slide 10 -> test
Proposal mapping
Questionnaire mapping
Quote mapping
Offer A
Offer B
{source_mapping_extra}
"""
    (pkg / "SOURCE_MAPPING.md").write_text(sm_text, encoding="utf-8")
    # Rendered evidence
    (pkg / "rendered").mkdir(exist_ok=True)
    for i in range(5):
        (pkg / "rendered" / f"proposal-{i}.png").write_bytes(b"png")
    # Apply package_content overrides (filename -> content)
    if package_content:
        for rel, content in package_content.items():
            p = pkg / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                p.write_bytes(content)
            else:
                p.write_text(content, encoding="utf-8")
    return pkg


class TestRegression(unittest.TestCase):

    def test_customer_send_ready_true_forces_fail(self):
        """CUSTOMER_SEND_READY=true => required verdict FAIL + overall FAIL (C1)"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm = make_commercial_with_sources(tmp)
            pkg = make_package_with_mapping(tmp, package_content={
                "Business35_Customer_Meeting_Script.md": "CUSTOMER_SEND_READY=true\n",
                "README.md": "HISTORICAL ONLY\n"
            })
            # Create minimal valid pptx/pdf/docx/xlsx via copying from real fixtures? For this test we only need stale/private checks
            # Create dummy pptx that will not be checked for overflow (we stub)
            # We test via check_stale_rejection and check_private_boundary directly
            r_stale = v.check_stale_rejection(comm, pkg, tmp / "dummy")
            r_private = v.check_private_boundary(pkg)
            # At least one should be FAIL
            self.assertFalse(r_stale.passed or r_private.passed, f"stale passed={r_stale.passed}, private passed={r_private.passed}")
            # Overall via main promotion: run full harness
            # Use validate functions to simulate overall
            results = [
                v.check_package_inventory(comm, pkg),
                v.check_source_mapping(comm, pkg),
                v.check_stale_rejection(comm, pkg, tmp / "dummy"),
                v.check_private_boundary(pkg),
            ]
            overall = all(r.passed for r in results)
            self.assertFalse(overall, "CUSTOMER_SEND_READY=true should cause overall FAIL")

    def test_forbidden_customer_claim_forces_fail(self):
        """forbidden customer claim => required verdict FAIL + overall FAIL"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm = make_commercial_with_sources(tmp)
            pkg = make_package_with_mapping(tmp, package_content={
                "Business35_Customer_Meeting_Script.md": "고객에게는 AI 도입 의무가 있습니다.\n",
            })
            r = v.check_stale_rejection(comm, pkg, tmp / "dummy")
            self.assertFalse(r.passed, f"forbidden claim should fail stale: {r.details}")
            # also check thatForbidden phrase in customer-facing md triggers stale fail
            self.assertIn("forbidden", " ".join(r.details).lower())

    def test_wrong_product_authority_sha_fails_source_mapping(self):
        """missing/wrong product authority SHA => SOURCE_MAPPING_FAIL (C2)"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm = make_commercial_with_sources(tmp, correct_sha=True)
            # Create mapping with wrong SHA
            pkg = make_package_with_mapping(tmp, source_mapping_extra="WRONG_SHA=0000000000000000000000000000000000000000")
            # Overwrite SOURCE_MAPPING to have wrong commit
            sm = pkg / "SOURCE_MAPPING.md"
            txt = sm.read_text(encoding="utf-8")
            txt = txt.replace(PRODUCT_COMMIT, "0000000000000000000000000000000000000000")
            sm.write_text(txt, encoding="utf-8")
            r = v.check_source_mapping(comm, pkg)
            self.assertFalse(r.passed, f"wrong SHA should fail source mapping: {r.details}")
            self.assertTrue(any("PRODUCT_COMMIT" in d or "05932da" in d for d in r.details))

    def test_stale_marker_with_other_file_historical_still_fails(self):
        """stale current claim + other file historical disclaimer => STALE_ARTIFACT_REJECTION_FAIL per-file (C3)"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm = make_commercial_with_sources(tmp)
            pkg = make_package_with_mapping(tmp, package_content={
                "A.md": "HISTORICAL ONLY\nPRE_V3_1\nSTALE_FOR_SEND\n",
                "Business35_Customer_Meeting_Script.md": "BUSINESS_35_FINAL_PACKAGE_QA_PASS\n",  # stale marker in current artifact
                "README.md": "HISTORICAL ONLY\nPRE_V3_1\n",  # README has historical, but B should still fail
            })
            r = v.check_stale_rejection(comm, pkg, tmp / "dummy")
            self.assertFalse(r.passed, f"per-file stale should fail even though A.md has historical: {r.details}")
            self.assertTrue(any("BUSINESS_35_FINAL_PACKAGE_QA_PASS" in d for d in r.details))

    def test_valid_negative_wording_allowed(self):
        """'성과를 보장하지 않는다' must not false-positive (C4)"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm = make_commercial_with_sources(tmp)
            pkg = make_package_with_mapping(tmp, package_content={
                "Business35_Customer_Meeting_Script.md": "성과를 보장하지 않는다. 파일럿에서는 KPI로 측정한다.\n가설\nPRICE_HYPOTHESIS_ONLY\n",
                "README.md": "가설\nPRICE_HYPOTHESIS_ONLY\n",
            })
            # Add price token to avoid price hypothesis fail
            for f in ["Business35_Customer_Meeting_Script.md", "README.md"]:
                p = pkg / f
                txt = p.read_text(encoding="utf-8")
                p.write_text(txt + "\n300만–500만원\n", encoding="utf-8")
            r = v.check_stale_rejection(comm, pkg, tmp / "dummy")
            # Should not contain forbidden '성과 보장' failure
            forb = [d for d in r.details if "성과 보장" in d and "without negation" in d]
            self.assertEqual(len(forb), 0, f"valid negation should not fail: {r.details}")

    def test_dependency_unavailable_never_pass(self):
        """missing/unavailable dependency remains FAIL, never inferred PASS (C4)"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm = tmp / "nonexistent_commercial"
            pkg = tmp / "nonexistent_package"
            # Do not create them
            r_inv = v.check_package_inventory(comm, pkg)
            r_map = v.check_source_mapping(comm, pkg)
            r_trace = v.check_exact_revision_trace(comm, pkg, tmp / "dummy", None)
            self.assertFalse(r_inv.passed)
            self.assertFalse(r_map.passed)
            self.assertFalse(r_trace.passed)
            # Ensure verdict strings are FAIL not PASS
            self.assertIn("FAIL", r_inv.verdict)
            self.assertIn("FAIL", r_map.verdict)
            self.assertIn("FAIL", r_trace.verdict)

    def test_price_hypothesis_violation_forces_fail(self):
        """price hypothesis boundary violation => STALE_FAIL + overall FAIL (C1)"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm = make_commercial_with_sources(tmp)
            pkg = make_package_with_mapping(tmp, package_content={
                "Business35_Customer_Meeting_Script.md": "견적: 300만–500만원\n1,000만–1,500만원\n",  # price without 가설
                "README.md": "가격 정보\n",  # no 가설
            })
            # Need to make a valid pptx dummy but price check is in stale
            r = v.check_stale_rejection(comm, pkg, tmp / "dummy")
            self.assertFalse(r.passed, f"price without hypothesis should fail: {r.details}")
            self.assertTrue(any("price hypothesis" in d.lower() for d in r.details))

    def test_missing_product_contract_in_mapping_fails(self):
        """missing PRODUCT_CONTRACT in SOURCE_MAPPING => FAIL (C2)"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm = make_commercial_with_sources(tmp)
            pkg = make_package_with_mapping(tmp)
            sm = pkg / "SOURCE_MAPPING.md"
            txt = sm.read_text(encoding="utf-8")
            txt = txt.replace("PRODUCT_CONTRACT", "MISSING")
            sm.write_text(txt, encoding="utf-8")
            r = v.check_source_mapping(comm, pkg)
            self.assertFalse(r.passed)
            self.assertTrue(any("PRODUCT_CONTRACT" in d for d in r.details))

    def test_wrong_source_revision_aaaa_fails_exact_trace(self):
        """A: arbitrary 40-hex SOURCE_REVISION != ACCEPTED => EXACT_REVISION_TRACE_FAIL"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm, pkg, pc, manifest = make_exact_trace_fixture(
                tmp,
                source_rev="a" * 40,
                generator_rev="b" * 40,
                product_contract_exists=True,
            )
            self.assertNotEqual("a" * 40, ACCEPTED_SOURCE_REVISION)
            r = v.check_exact_revision_trace(comm, pkg, pc, manifest)
            self.assertFalse(r.passed, f"wrong SOURCE_REVISION should fail: {r.details}")
            self.assertIn("FAIL", r.verdict)
            self.assertTrue(any("ACCEPTED_SOURCE_REVISION" in d for d in r.details))

    def test_short_generator_revision_fails_exact_trace(self):
        """B: 12-char GENERATOR_REVISION (Lane B rejected 899958e83bd7) => EXACT_REVISION_TRACE_FAIL"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm, pkg, pc, manifest = make_exact_trace_fixture(
                tmp,
                source_rev=ACCEPTED_SOURCE_REVISION,
                generator_rev="899958e83bd7",
                product_contract_exists=True,
            )
            r = v.check_exact_revision_trace(comm, pkg, pc, manifest)
            self.assertFalse(r.passed, f"12-char GENERATOR_REVISION should fail: {r.details}")
            self.assertIn("FAIL", r.verdict)
            self.assertTrue(any("GENERATOR_REVISION" in d for d in r.details))

    def test_actual_product_contract_missing_fails_required_verdict(self):
        """C: actual product_contract file missing => required verdict FAIL => overall FAIL.

        This tests the real authority file dependency (Path missing), not a
        SOURCE_MAPPING string edit (covered separately by
        test_missing_product_contract_in_mapping_fails).
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            comm, pkg, pc_valid, manifest = make_exact_trace_fixture(
                tmp,
                source_rev=ACCEPTED_SOURCE_REVISION,
                generator_rev="c" * 40,
                product_contract_exists=True,
            )
            r_ok = v.check_exact_revision_trace(comm, pkg, pc_valid, manifest)
            self.assertTrue(r_ok.passed, f"valid fixture should pass exact trace: {r_ok.details}")
            # Same manifest/package but the actual authority file is absent.
            pc_missing = tmp / "MISSING_PRODUCT_CONTRACT.md"
            self.assertFalse(pc_missing.exists())
            r = v.check_exact_revision_trace(comm, pkg, pc_missing, manifest)
            self.assertFalse(r.passed, f"missing product_contract file should fail: {r.details}")
            self.assertIn("FAIL", r.verdict)
            self.assertTrue(any("product_contract" in d for d in r.details))
            # Required verdict FAIL must force overall FAIL (no inference to PASS).
            overall = all([r.passed and not r.unavailable])
            self.assertFalse(overall, "missing product_contract must force overall FAIL")

if __name__ == "__main__":
    unittest.main(verbosity=2)
