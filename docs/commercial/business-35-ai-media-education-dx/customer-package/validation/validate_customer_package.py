#!/usr/bin/env python3
"""Validate the Business 35 customer-facing master package.

Checks file presence, PDF page counts, forbidden claims, source linkage,
price consistency, and absence of customer/performance claims. Text-based
checks are performed on PDFs via pdftotext; geometry checks are performed
on the PPTX via python-pptx.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # customer-package/

REQUIRED_FILES = [
    "README.md",
    "CUSTOMIZATION_CHECKLIST.md",
    "SOURCE_MAPPING.md",
    "Business35_Master_Proposal_10p.pptx",
    "Business35_Master_Proposal_10p.pdf",
    "Business35_OnePage_Offer.pdf",
    "Business35_OnePage_Offer_Source.pptx",
    "Business35_Diagnostic_Questionnaire.docx",
    "Business35_Diagnostic_Questionnaire.pdf",
    "Business35_Pilot_Quote_Template.xlsx",
    "Business35_Customer_Meeting_Script.md",
    "Business35_Followup_Email_Templates.md",
    "rendered/",
    "validation/",
]

FORBIDDEN_PHRASES = [
    "AI 도입 의무",
    "반드시 도입",
    "법적으로 안전",
    "저작권 문제 없음",
    "개인정보 문제 없음",
    "지원금 수령 가능",
    "자동 수의계약",
    "1억원 이하",
]

# "성과 보장" is only allowed in negation/context like "성과 보장을 의미하지 않습니다"
UNSOURCED_NUMBERS = ["48.8%", "28.7%", "60.8%"]

EXPECTED_PRICE_TOKENS = [
    "300 만 ~500 만원",
    "300 만– 800 만원",
    "1,000 만 ~1,500 만원",
    "1,000 만– 1,500 만원",
    "1,500 만– 2,500 만원",
    "월 300 만– 600 만원",
]


def check(ok: bool, label: str, problems: list[str]) -> bool:
    if ok:
        print(f"PASS  {label}")
        return True
    problems.append(label)
    print(f"FAIL  {label}")
    return False


def pdf_text(name: str) -> str:
    p = ROOT / name
    out = subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True)
    return out.stdout


def pdf_pages(name: str) -> int:
    p = ROOT / name
    out = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True)
    m = re.search(r"Pages:\s+(\d+)", out.stdout)
    return int(m.group(1)) if m else -1


def main() -> int:
    problems: list[str] = []

    for f in REQUIRED_FILES:
        check((ROOT / f).exists(), f"required file/dir exists: {f}", problems)

    # PDF page counts
    check(pdf_pages("Business35_Master_Proposal_10p.pdf") == 10,
          "proposal PDF has 10 pages", problems)
    check(pdf_pages("Business35_OnePage_Offer.pdf") == 1,
          "one-page offer PDF has 1 page", problems)
    qpages = pdf_pages("Business35_Diagnostic_Questionnaire.pdf")
    check(qpages >= 1, f"questionnaire PDF renders ({qpages} pages)", problems)

    # Rendered images present
    rendered = (ROOT / "rendered")
    proposal_imgs = sorted(rendered.glob("proposal-*.png"))
    check(len(proposal_imgs) >= 10, f"proposal rendered >= 10 images (found {len(proposal_imgs)})", problems)
    check(len(list(rendered.glob("onepage-*.png"))) >= 1, "one-page rendered image present", problems)

    # Text integrity: no broken glyph markers
    for f in ["Business35_Master_Proposal_10p.pdf", "Business35_OnePage_Offer.pdf",
              "Business35_Diagnostic_Questionnaire.pdf"]:
        txt = pdf_text(f)
        check("�" not in txt and "□" not in txt, f"no broken glyph markers in {f}", problems)

    # Forbidden phrases
    for f in ["Business35_Master_Proposal_10p.pdf", "Business35_OnePage_Offer.pdf",
              "Business35_Diagnostic_Questionnaire.pdf"]:
        txt = pdf_text(f)
        for bad in FORBIDDEN_PHRASES:
            check(bad not in txt, f"forbidden phrase absent in {f}: {bad}", problems)

    # "성과 보장" only in negation
    for f in ["Business35_Master_Proposal_10p.pdf", "Business35_OnePage_Offer.pdf"]:
        txt = pdf_text(f)
        for m in re.finditer(r"성과 보장", txt):
            ctx = txt[max(0, m.start() - 20): m.end() + 20]
            check("의미하지 않" in ctx or "보장하지" in ctx or "보장하라고" in ctx,
                  f"'성과 보장' used only in negation context in {f}: ...{ctx}...", problems)

    # Unsourced numbers absent
    for f in ["Business35_Master_Proposal_10p.pdf", "Business35_OnePage_Offer.pdf"]:
        txt = pdf_text(f)
        for num in UNSOURCED_NUMBERS:
            check(num not in txt, f"unsourced number absent in {f}: {num}", problems)

    # Price consistency (PDF text tokens)
    for f in ["Business35_Master_Proposal_10p.pdf", "Business35_OnePage_Offer.pdf"]:
        txt = pdf_text(f)
        found = [t for t in EXPECTED_PRICE_TOKENS if t in txt]
        check(len(found) >= 2, f"price tokens found in {f}: {len(found)}", problems)

    # No real customer names / performance claims
    for f in ["Business35_Master_Proposal_10p.pdf", "Business35_OnePage_Offer.pdf",
              "Business35_Diagnostic_Questionnaire.pdf"]:
        txt = pdf_text(f)
        check("실제 고객" not in txt or "합성 예시" in txt or "주장이 아닙니다" in txt,
              f"no real-customer framing misuse in {f}", problems)
        check("매출" not in txt or "주장이 아닙니다" in txt,
              f"no revenue claim in {f}", problems)

    # PPTX geometry: no shape extends beyond slide bounds
    try:
        from pptx import Presentation
        for f in ["Business35_Master_Proposal_10p.pptx", "Business35_OnePage_Offer_Source.pptx"]:
            prs = Presentation(str(ROOT / f))
            w = prs.slide_width
            h = prs.slide_height
            overflow = 0
            for slide in prs.slides:
                for shp in slide.shapes:
                    if shp.left is None or shp.top is None:
                        continue
                    right = shp.left + (shp.width or 0)
                    bottom = shp.top + (shp.height or 0)
                    if right > w + 10000 or bottom > h + 10000 or shp.left < -10000 or shp.top < -10000:
                        overflow += 1
            check(overflow == 0, f"no shape overflow in {f} (overflows: {overflow})", problems)
    except Exception as e:
        check(False, f"pptx geometry check ran ({e})", problems)

    # Source mapping covers every slide
    sm = (ROOT / "SOURCE_MAPPING.md").read_text(encoding="utf-8")
    for n in range(1, 11):
        check(f"Slide {n} " in sm or f"Slide {n}→" in sm, f"SOURCE_MAPPING covers Slide {n}", problems)

    print()
    if problems:
        print(f"FAILED: {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
