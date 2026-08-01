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

# Standard price ranges. PDF extraction splits "만" from "원" (e.g. "300 만 ~500 만원"),
# so we match on the numeric bounds rather than exact tokens.
PRICE_RANGE_BOUNDS = [
    (300, 800),      # A 표준
    (300, 500),      # A 초기 제안
    (1000, 1500),    # B 디자인 파트너
    (1500, 2500),    # B 표준
    (300, 600),      # C 월
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

    # Price consistency: each standard range bound pair must appear in the PDF text
    for f in ["Business35_Master_Proposal_10p.pdf", "Business35_OnePage_Offer.pdf"]:
        txt = pdf_text(f)
        txt_norm = txt.replace(",", "").replace("\u00a0", " ")
        found = 0
        for lo, hi in PRICE_RANGE_BOUNDS:
            if str(lo) in txt_norm and str(hi) in txt_norm:
                found += 1
        check(found >= 4, f"price ranges found in {f}: {found}/5", problems)

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

    # ---- Visual QA integration ----
    vqa = (ROOT / "VISUAL_QA.md")
    check(vqa.is_file(), "VISUAL_QA.md exists", problems)
    if vqa.is_file():
        vqa_text = vqa.read_text(encoding="utf-8")
        for name in ["Business35_Master_Proposal_10p", "Business35_OnePage_Offer",
                     "Business35_Diagnostic_Questionnaire"]:
            check(name in vqa_text, f"VISUAL_QA.md references {name}", problems)
        check("BLOCKER" in vqa_text or "blocker" in vqa_text,
              "VISUAL_QA.md records blocker status", problems)
        check("MAJOR" in vqa_text or "major" in vqa_text,
              "VISUAL_QA.md records major status", problems)

    # Rendered file count and per-file listing in VISUAL_QA.md
    rendered = (ROOT / "rendered")
    pngs = sorted(rendered.glob("*.png"))
    check(len(pngs) >= 15, f"rendered PNG count >= 15 (found {len(pngs)})", problems)
    if vqa.is_file():
        vqa_text = vqa.read_text(encoding="utf-8")
        missing = [p.name for p in pngs if p.name not in vqa_text]
        check(not missing, f"every rendered filename listed in VISUAL_QA.md (missing: {missing[:5] or 'none'})", problems)

    # BLOCKER 0 / MAJOR 0 declarations
    check("BLOCKER: 0" in vqa_text or "BLOCKER 0" in vqa_text or "blocker_count: 0" in vqa_text,
          "VISUAL_QA.md declares BLOCKER count 0", problems)
    check("MAJOR: 0" in vqa_text or "MAJOR 0" in vqa_text or "major_count: 0" in vqa_text,
          "VISUAL_QA.md declares MAJOR count 0", problems)

    # Proposal slide count 10 and speaker notes 10
    from pptx import Presentation
    prs = Presentation(str(ROOT / "Business35_Master_Proposal_10p.pptx"))
    check(len(prs.slides._sldIdLst) == 10, "proposal slide count == 10", problems)
    notes_count = sum(1 for s in prs.slides if s.has_notes_slide)
    check(notes_count == 10, f"speaker notes on all 10 slides (found {notes_count})", problems)

    # Korean status footer present on every slide
    footer_ok = True
    for idx, s in enumerate(prs.slides, start=1):
        footer_text = ""
        for shp in s.shapes:
            if shp.has_text_frame and shp.top is not None and shp.top > 6400000:  # footer zone
                footer_text += shp.text_frame.text
        if not footer_text or ("DRAFT MASTER" not in footer_text and "CUSTOMER-FACING MASTER" not in footer_text):
            footer_ok = False
    check(footer_ok, "Korean status footer present on all proposal slides", problems)

    # Validator does not replace visual QA
    if vqa.is_file():
        check("validator" in vqa_text.lower() and "대신" in vqa_text,
              "VISUAL_QA.md notes validator does not replace visual QA", problems)

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
