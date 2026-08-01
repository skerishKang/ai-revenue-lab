#!/usr/bin/env python3
"""Validate the Business 32 customer-facing pilot package.

Checks required files, page counts (proposal 10, one-page 1, worksheet <=3,
skill card 2-3), rendered PNG parity, external runtime 0, no real customer/org
data, no backend/SaaS/auto-approval claims, price-hypothesis presence, human
review wording, and that only the customer-package scope changed.
"""
import glob
import os
import re
import subprocess
import sys

from pptx import Presentation
from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

VALIDATED_UX_HEAD = "73ec4718d0835248ab20d56bc68f3956536112b4"
VALIDATED_HANDOFF_HEAD = "29068281998b7f1a59d76a95174807ffbf20cb38"
COMMERCIAL_HEAD = "30565f4ddcf99296751109df3a0973d7ba79eaa8"

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # customer-package/
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PACKAGE))))
PRODUCT_WORKSPACE = os.path.join(REPO_ROOT, "reference", "business-32-ai-skill-studio-ux")

REQUIRED_FILES = [
    "README.md",
    "SOURCE_MAPPING.md",
    "CUSTOMIZATION_CHECKLIST.md",
    "VISUAL_QA.md",
    "Business32_Master_Proposal_10p.pptx",
    "Business32_Master_Proposal_10p.pdf",
    "Business32_OnePage_Offer_Source.pptx",
    "Business32_OnePage_Offer.pdf",
    "Business32_Skill_Discovery_Worksheet.docx",
    "Business32_Skill_Discovery_Worksheet.pdf",
    "Business32_Verified_Skill_Card_Sample.pptx",
    "Business32_Verified_Skill_Card_Sample.pdf",
    "Business32_Pilot_Quote_Template.xlsx",
    "Business32_Customer_Meeting_Script.md",
    "Business32_Followup_Email_Templates.md",
    "rendered/manifest.md",
    "validation/_b32theme.py",
    "validation/build_proposal_pptx.py",
    "validation/build_one_page_pptx.py",
    "validation/build_discovery_worksheet.py",
    "validation/build_skill_card_pptx.py",
    "validation/build_quote_xlsx.py",
    "validation/validate_customer_package.py",
]

PDFS = {
    "Business32_Master_Proposal_10p.pdf": 10,
    "Business32_OnePage_Offer.pdf": 1,
    "Business32_Skill_Discovery_Worksheet.pdf": 3,
    "Business32_Verified_Skill_Card_Sample.pdf": 3,
}

PPTX_SLIDES = {
    "Business32_Master_Proposal_10p.pptx": 10,
    "Business32_OnePage_Offer_Source.pptx": 1,
    "Business32_Verified_Skill_Card_Sample.pptx": 3,
}

XLSX_SHEETS = [
    "안내", "고객·업무", "Offer 선택", "작업 범위", "산출물", "일정", "견적", "가정·제외사항",
]

PRICES = ["300만~500만원", "500만~800만원", "1,200만~2,000만원"]

failures = []


def path(rel):
    return os.path.join(PACKAGE, rel)


def read_md(rel):
    with open(path(rel), "r", encoding="utf-8") as fh:
        return fh.read()


def check(name, fn):
    try:
        fn()
        print("PASS " + name)
    except AssertionError as error:
        failures.append(name)
        print("FAIL " + name + ": " + str(error))


def pdf_text(rel):
    reader = PdfReader(path(rel))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def normalize(text):
    return re.sub(r"\s+", "", text)


def main():
    for rel in REQUIRED_FILES:
        check("required file exists: " + rel, lambda r=rel: assert_exists(r))

    for rel, max_pages in PDFS.items():
        check("pdf page count within bound: " + rel, lambda r=rel, m=max_pages: assert_pdf_pages(r, m))

    check("proposal pdf is exactly 10 pages", lambda: assert_pdf_exact("Business32_Master_Proposal_10p.pdf", 10))
    check("one-page pdf is exactly 1 page", lambda: assert_pdf_exact("Business32_OnePage_Offer.pdf", 1))
    check("worksheet pdf is 3 pages or fewer", lambda: assert_pdf_exact("Business32_Skill_Discovery_Worksheet.pdf", None, max_pages=3))
    check("skill card pdf is 2-3 pages", lambda: assert_pdf_exact("Business32_Verified_Skill_Card_Sample.pdf", None, min_pages=2, max_pages=3))

    check("proposal pptx is exactly 10 slides", lambda: assert_slides("Business32_Master_Proposal_10p.pptx", 10))
    check("one-page pptx is exactly 1 slide", lambda: assert_slides("Business32_OnePage_Offer_Source.pptx", 1))
    check("skill card pptx is 2-3 slides", lambda: assert_slides("Business32_Verified_Skill_Card_Sample.pptx", None, min_pages=2, max_pages=3))

    check("discovery worksheet has 13 questions", lambda: assert_worksheet_questions())

    check("quote workbook has all 8 sheets", lambda: assert_xlsx_sheets())

    check("rendered PNGs match every pdf page", lambda: assert_png_parity())

    check("external runtime dependency 0 in docs", lambda: assert_no_external_runtime())

    md_all = "\n".join(read_md(rel) for rel in REQUIRED_FILES if rel.endswith(".md"))
    check("no real customer/org data in docs", lambda: (
        assert_no_email(md_all),
        assert_no_phone(md_all),
        assert_no_business_number(md_all),
    ))

    for rel, _max in PDFS.items():
        text = pdf_text(rel)
        check("no PII in pdf: " + rel, lambda t=text: (
            assert_no_email(t),
            assert_no_phone(t),
            assert_no_business_number(t),
        ))
        check("no backend/SaaS/auto-approval claims in pdf: " + rel, lambda t=text: (
            assert_not_contain(t, "정확성을 보장"),
            assert_not_contain(t, "보장합니다"),
            assert_not_contain(t, "직원을 대체"),
            assert_not_contain(t, "대체합니다"),
            assert_not_contain(t, "자동 승인합니다"),
        ))
        check("human review wording present in pdf: " + rel, lambda t=text: (
            assert_contain(t, "사람 검토"),
            assert_contain(t, "합성"),
        ))

    proposal = pdf_text("Business32_Master_Proposal_10p.pdf")
    check("all offer prices shown as hypotheses in proposal", lambda: (
        tuple(assert_contain(normalize(proposal), normalize(price)) for price in PRICES),
        assert_contain(proposal, "가격 가설"),
        assert_contain(proposal, "가설"),
    ))

    one = pdf_text("Business32_OnePage_Offer.pdf")
    check("one-page shows price hypothesis and human review", lambda: (
        assert_contain(one, "가설"),
        assert_contain(one, "사람 검토"),
    ))

    check("validated heads referenced", lambda: (
        assert_contain(read_md("README.md"), VALIDATED_UX_HEAD),
        assert_contain(read_md("README.md"), VALIDATED_HANDOFF_HEAD),
        assert_contain(read_md("README.md"), COMMERCIAL_HEAD),
    ))

    check("pixel visual QA not declared", lambda: (
        assert_contain(read_md("VISUAL_QA.md"), "PIXEL_VISUAL_QA_PASS: NOT DECLARED"),
        assert_contain(read_md("VISUAL_QA.md"), "CUSTOMER_SEND_READY:  NOT DECLARED"),
    ))

    check("no backend implementation files in workspace", lambda: assert_no_backend_files())

    check("validated product workspace unchanged", lambda: assert_product_unchanged())

    check("only customer-package scope changed", lambda: assert_scope())

    print()
    if failures:
        print("%d validation failure(s)" % len(failures))
        return 1
    print("customer package validation ok")
    return 0


def assert_pdf_pages(rel, max_pages):
    n = len(PdfReader(path(rel)).pages)
    assert n <= max_pages, "pdf pages %d > %d: %s" % (n, max_pages, rel)


def assert_exists(rel):
    assert os.path.isfile(path(rel)), "missing file: " + rel


def assert_pdf_exact(rel, exact=None, min_pages=None, max_pages=None):
    n = len(PdfReader(path(rel)).pages)
    if exact is not None:
        assert n == exact, "pdf pages %d != %d: %s" % (n, exact, rel)
    if min_pages is not None:
        assert n >= min_pages, "pdf pages %d < %d: %s" % (n, min_pages, rel)
    if max_pages is not None:
        assert n <= max_pages, "pdf pages %d > %d: %s" % (n, max_pages, rel)


def assert_slides(rel, exact=None, min_pages=None, max_pages=None):
    n = len(Presentation(path(rel)).slides._sldIdLst)
    if exact is not None:
        assert n == exact, "slides %d != %d: %s" % (n, exact, rel)
    if min_pages is not None:
        assert n >= min_pages, "slides %d < %d: %s" % (n, min_pages, rel)
    if max_pages is not None:
        assert n <= max_pages, "slides %d > %d: %s" % (n, max_pages, rel)


def assert_worksheet_questions():
    doc = Document(path("Business32_Skill_Discovery_Worksheet.docx"))
    count = 0
    for p in doc.paragraphs:
        if re.match(r"^☐ Q\d+\.", p.text):
            count += 1
    assert count == 13, "expected 13 questions, got %d" % count


def assert_xlsx_sheets():
    wb = load_workbook(path("Business32_Pilot_Quote_Template.xlsx"), data_only=False)
    assert wb.sheetnames == XLSX_SHEETS, "unexpected sheets: %s" % wb.sheetnames


def assert_png_parity():
    for rel, _max in PDFS.items():
        base = rel[:-4]
        n = len(PdfReader(path(rel)).pages)
        pngs = glob.glob(os.path.join(PACKAGE, "rendered", base + "_p-*.png"))
        assert len(pngs) == n, "png count %d != pdf pages %d for %s" % (len(pngs), n, base)


def assert_no_external_runtime():
    for rel in REQUIRED_FILES:
        if not rel.endswith(".md"):
            continue
        content = read_md(rel)
        stripped = content.replace('xmlns="http://www.w3.org/2000/svg"', "")
        assert "http://" not in stripped and "https://" not in stripped, "external URL in " + rel


def assert_no_email(text):
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text), "email-like pattern found"


def assert_no_phone(text):
    assert not re.search(r"010[- ]?\d{3,4}[- ]?\d{4}", text), "phone pattern found"


def assert_no_business_number(text):
    assert not re.search(r"\d{3}-\d{2}-\d{5}", text), "business registration pattern found"


def assert_contain(text, needle):
    assert needle in text, "missing: " + needle


def assert_not_contain(text, needle):
    assert needle not in text, "forbidden claim present: " + needle


def assert_no_backend_files():
    backend_markers = [".sql", "schema.py", "drizzle", "migration", "api/", "worker.py", "server.py"]
    for root, _dirs, files in os.walk(PACKAGE):
        for name in files:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, PACKAGE)
            if rel.startswith("validation") and name in ("validate_customer_package.py", "build_proposal_pptx.py"):
                continue
            for marker in backend_markers:
                assert marker not in rel.lower(), "backend file marker in package: " + rel


def assert_product_unchanged():
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", PRODUCT_WORKSPACE],
        capture_output=True, text=True, cwd=REPO_ROOT,
    ).stdout.strip()
    assert not out, "validated product workspace has changes:\n" + out


def assert_scope():
    base = "origin/docs/business-32-commercial-package"
    out = subprocess.run(
        ["git", "diff", "--name-only", base + "...HEAD"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    ).stdout.strip()
    allowed = "docs/commercial/business-32-ai-skill-studio/customer-package/"
    if not out:
        return
    for line in out.splitlines():
        assert line.startswith(allowed), "out-of-scope path: " + line


if __name__ == "__main__":
    sys.exit(main())
