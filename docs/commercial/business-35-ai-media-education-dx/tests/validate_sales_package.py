#!/usr/bin/env python3
"""Validate the Business 35 commercial sales kit draft package.

Checks that the required files exist, the artifacts follow the Issue #353
contract, pricing is consistent, and forbidden claims are absent.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # docs/commercial/business-35-ai-media-education-dx/

REQUIRED_FILES = [
    "README.md",
    "01-one-page-offer.md",
    "02-ten-page-proposal.md",
    "03-diagnostic-questionnaire.md",
    "04-six-week-pilot-plan.md",
    "05-statement-of-work-draft.md",
    "06-risk-and-data-annex.md",
    "07-kpi-measurement-framework.md",
    "08-customer-qualification-scorecard.md",
    "SOURCES.md",
    "tests/validate_sales_package.py",
]

ARTIFACTS = [
    "01-one-page-offer.md",
    "02-ten-page-proposal.md",
    "03-diagnostic-questionnaire.md",
    "04-six-week-pilot-plan.md",
    "05-statement-of-work-draft.md",
    "06-risk-and-data-annex.md",
    "07-kpi-measurement-framework.md",
    "08-customer-qualification-scorecard.md",
]

SOW_REQUIRED_ITEMS = [
    "목적", "범위", "제외 범위", "고객 책임", "제공자 책임", "일정", "산출물",
    "검수 기준", "비용", "지급 조건", "중단 조건", "변경관리", "비밀유지",
    "개인정보", "저작권", "AI 도구 사용", "책임 제한",
]

FORBIDDEN_PHRASE = "AI 도입 의무화"

PRICES = [
    ("A 300만–800만원", "01-one-page-offer.md"),
    ("B 디자인 파트너 파일럿 1,000만–1,500만원", "01-one-page-offer.md"),
    ("B 표준 6주 파일럿 1,500만–2,500만원", "01-one-page-offer.md"),
    ("C 월 300만–600만원", "01-one-page-offer.md"),
]

EXCLUSION_RULES = [
    "실제 개인정보를 무제한 외부 AI에 입력하려는 조직",
    "사람 검토 없이 자동 게시를 요구하는 조직",
    "법률·의료·채용 결정을 자동화하려는 조직",
    "6주간 담당자를 지정할 수 없는 조직",
    "기준선 데이터를 전혀 제공할 수 없는 조직",
    "성과를 보장하라고 요구하는 조직",
]

PLACEHOLDER_MARKERS = ["[고객 조직명]", "[제공자 법인 또는 사업자명]", "[최종 승인 금액]"]


def check(ok: bool, label: str, problems: list[str]) -> bool:
    if ok:
        print(f"PASS  {label}")
        return True
    problems.append(label)
    print(f"FAIL  {label}")
    return False


def main() -> int:
    problems: list[str] = []

    for f in REQUIRED_FILES:
        check((ROOT / f).is_file(), f"required file exists: {f}", problems)

    for f in ARTIFACTS:
        check((ROOT / f).is_file(), f"commercial artifact exists: {f}", problems)

    # Proposal: exactly 10 page blocks "## Page N —"
    proposal = (ROOT / "02-ten-page-proposal.md").read_text(encoding="utf-8")
    pages = re.findall(r"^## Page (\d+) —", proposal, flags=re.MULTILINE)
    check(len(pages) == 10, f"proposal has exactly 10 pages (found {len(pages)})", problems)
    check(pages == [str(i) for i in range(1, 11)], "proposal pages numbered 1..10 in order", problems)

    # SOW required items
    sow = (ROOT / "05-statement-of-work-draft.md").read_text(encoding="utf-8")
    missing_sow = [item for item in SOW_REQUIRED_ITEMS if item not in sow]
    check(not missing_sow, f"SOW contains all required items (missing: {missing_sow or 'none'})", problems)

    # Legal review labels
    legal_docs = ["05-statement-of-work-draft.md", "06-risk-and-data-annex.md"]
    for f in legal_docs:
        text = (ROOT / f).read_text(encoding="utf-8")
        check("DRAFT · PROFESSIONAL LEGAL REVIEW REQUIRED" in text,
              f"legal review label present in {f}", problems)

    # Forbidden phrase across all md files
    for f in sorted(ROOT.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        check(FORBIDDEN_PHRASE not in text, f"no forbidden phrase '{FORBIDDEN_PHRASE}' in {f.name}", problems)

    # No automatic <=100M negotiated-contract claim
    for f in sorted(ROOT.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        has_auto_claim = re.search(r"자동\s*로?\s*1억원\s*이하\s*수의계약", text)
        check(has_auto_claim is None, f"no automatic <=100M negotiated-contract claim in {f.name}", problems)

    # Price consistency
    for price, f in PRICES:
        text = (ROOT / f).read_text(encoding="utf-8")
        check(price in text, f"price present: {price} in {f}", problems)

    # Exclusion rules present
    scorecard = (ROOT / "08-customer-qualification-scorecard.md").read_text(encoding="utf-8")
    for rule in EXCLUSION_RULES:
        check(rule in scorecard, f"exclusion rule present: {rule[:20]}...", problems)

    # No real customer/contract/revenue claims
    for f in sorted(ROOT.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        check("실제 고객명" not in text or "기재 금지" in text,
              f"no real customer name usage in {f.name}", problems)
        no_claim = (
            "실제 계약·매출 발생 주장 아님" in text
            or "실제 계약·매출 주장" in text
            or "매출 주장 금지" in text
            or ("실제 계약·매출" in text and "아니다" in text)
        )
        check(no_claim,
              f"no actual contract/revenue claim in {f.name}", problems)

    # Placeholders present in SOW
    sow_text = (ROOT / "05-statement-of-work-draft.md").read_text(encoding="utf-8")
    for marker in PLACEHOLDER_MARKERS:
        check(marker in sow_text, f"SOW placeholder present: {marker}", problems)

    # Status header on every doc
    for f in sorted(ROOT.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        has_status = any(s in text for s in [
            "INTERNAL COMMERCIAL DRAFT",
            "OWNER APPROVAL REQUIRED",
            "NOT YET SENT TO A CUSTOMER",
            "DRAFT · PROFESSIONAL LEGAL REVIEW REQUIRED",
        ])
        check(has_status, f"status header present in {f.name}", problems)

    # Trust boundary framing present
    governance_framing = "거버넌스 요구가 강화되고 있다" if False else "사용정책과 거버넌스 요구가 강화되고 있다"
    for f in ["01-one-page-offer.md", "02-ten-page-proposal.md"]:
        text = (ROOT / f).read_text(encoding="utf-8")
        check(governance_framing in text, f"governance framing present in {f}", problems)

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
