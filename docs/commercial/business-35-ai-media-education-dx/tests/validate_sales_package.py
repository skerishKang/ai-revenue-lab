#!/usr/bin/env python3
"""Validate the Business 35 commercial sales kit draft package.

Checks that the required files exist, the artifacts follow the Issue #353
contract, pricing is consistent, forbidden claims are absent, customer-facing
numeric claims are backed by VERIFIED sources with deep-link URLs, and no
unverified market/procurement claims leak into customer-facing documents.
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

CUSTOMER_DOCS = [
    "01-one-page-offer.md",
    "02-ten-page-proposal.md",
    "03-diagnostic-questionnaire.md",
    "04-six-week-pilot-plan.md",
    "05-statement-of-work-draft.md",
    "06-risk-and-data-annex.md",
    "07-kpi-measurement-framework.md",
    "08-customer-qualification-scorecard.md",
]

PRICE_DOCS = [
    "01-one-page-offer.md",
    "02-ten-page-proposal.md",
    "README.md",
]

# Documents whose purpose does not display the full pricing ladder.
# They may display only the price(s) relevant to their scope.
PRICE_OPTIONAL_DOCS = [
    "04-six-week-pilot-plan.md",
    "05-statement-of-work-draft.md",
    "07-kpi-measurement-framework.md",
    "08-customer-qualification-scorecard.md",
]

# Standard price range tokens that any displayed price must be composed of.
PRICE_RANGE_TOKENS = [
    "300만–800만원",
    "1,000만–1,500만원",
    "1,500만–2,500만원",
    "월 300만–600만원",
]

SOW_REQUIRED_ITEMS = [
    "목적", "범위", "제외 범위", "고객 책임", "제공자 책임", "일정", "산출물",
    "검수 기준", "비용", "지급 조건", "중단 조건", "변경관리", "비밀유지",
    "개인정보", "저작권", "AI 도구 사용", "책임 제한",
]

LEGAL_REVIEW_ITEMS = [
    "검수기간 내 이의 없을 때 검수 완료 간주",
    "중단 시 수행분 정산",
    "비밀유지 기간",
    "지식재산권 귀속",
    "개인정보 역할과 책임",
    "책임 총액 제한",
    "간접손해 배제",
]

FORBIDDEN_PHRASE = "AI 도입 의무화"

# Standard price phrases that must be consistent wherever prices appear.
STANDARD_PRICE_PHRASES = [
    "300만–800만원",
    "1,000만–1,500만원",
    "1,500만–2,500만원",
    "월 300만–600만원",
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

# Known customer-facing numeric claims that must be VERIFIED in SOURCES.
# (source_id, claim_substring, customer_doc)
REQUIRED_NUMERIC_CLAIMS = [
    ("SRC-07", "60.8%", None),  # SPRI: VERIFIED in SOURCES
]

# Numeric claims removed from customer documents (must NOT appear).
REMOVED_NUMERIC_CLAIMS = [
    "48.8%",
    "28.7%",
]

# SOURCES entries that must carry a deep-link URL (not a bare homepage/list).
# A valid deep link contains a document/board-article identifier.
DEEP_LINK_REQUIRED_SOURCES = ["SRC-01", "SRC-04", "SRC-07"]

# Sources allowed to be NOT VERIFIED / INTERNAL HYPOTHESIS (never customer-facing).
UNVERIFIED_SOURCES = ["SRC-02", "SRC-03", "SRC-05", "SRC-06", "SRC-08", "SRC-09"]


def check(ok: bool, label: str, problems: list[str]) -> bool:
    if ok:
        print(f"PASS  {label}")
        return True
    problems.append(label)
    print(f"FAIL  {label}")
    return False


def read_md(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def parse_sources() -> dict[str, dict[str, str]]:
    """Parse SOURCES.md into {SRC-XX: {field: value}} blocks."""
    text = read_md("SOURCES.md")
    blocks: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = re.match(r"^###\s+(SRC-\d+)\.", line)
        if m:
            current = m.group(1)
            blocks[current] = {}
            continue
        if current:
            fm = re.match(r"^\s*(\S[^:]*):\s*(.*)$", line)
            if fm:
                key = fm.group(1).strip()
                val = fm.group(2).strip()
                blocks[current][key] = val
    return blocks


def extract_source_ids(text: str) -> list[str]:
    return re.findall(r"SRC-\d+", text)


def main() -> int:
    problems: list[str] = []

    for f in REQUIRED_FILES:
        check((ROOT / f).is_file(), f"required file exists: {f}", problems)

    for f in ARTIFACTS:
        check((ROOT / f).is_file(), f"commercial artifact exists: {f}", problems)

    # Proposal: exactly 10 page blocks "## Page N —"
    proposal = read_md("02-ten-page-proposal.md")
    pages = re.findall(r"^## Page (\d+) —", proposal, flags=re.MULTILINE)
    check(len(pages) == 10, f"proposal has exactly 10 pages (found {len(pages)})", problems)
    check(pages == [str(i) for i in range(1, 11)], "proposal pages numbered 1..10 in order", problems)

    # SOW required items
    sow = read_md("05-statement-of-work-draft.md")
    missing_sow = [item for item in SOW_REQUIRED_ITEMS if item not in sow]
    check(not missing_sow, f"SOW contains all required items (missing: {missing_sow or 'none'})", problems)

    # SOW professional legal review section items
    missing_legal = [item for item in LEGAL_REVIEW_ITEMS if item not in sow]
    check(not missing_legal,
          f"SOW legal review section covers all items (missing: {missing_legal or 'none'})", problems)

    # Legal review labels
    legal_docs = ["05-statement-of-work-draft.md", "06-risk-and-data-annex.md"]
    for f in legal_docs:
        text = read_md(f)
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

    # Price consistency across all docs that display prices.
    # Documents that display prices must carry all standard price phrases.
    for doc in PRICE_DOCS:
        text = read_md(doc)
        for phrase in STANDARD_PRICE_PHRASES:
            check(phrase in text, f"price phrase present in {doc}: {phrase}", problems)

    # Documents that do not display the full ladder may show only relevant
    # prices, but any displayed price must match a standard range token.
    for doc in PRICE_OPTIONAL_DOCS:
        text = read_md(doc)
        bad = [m for m in re.findall(r"\d{1,3}(?:,\d{3})?만–\d{1,3}(?:,\d{3})?만원", text)
               if m not in PRICE_RANGE_TOKENS]
        check(not bad, f"price-optional doc {doc} shows only standard ranges (off-range: {bad or 'none'})", problems)

    # Exclusion rules present
    scorecard = read_md("08-customer-qualification-scorecard.md")
    for rule in EXCLUSION_RULES:
        check(rule in scorecard, f"exclusion rule present: {rule[:20]}...", problems)

    # ---- Source register checks ----
    sources = parse_sources()
    check(len(sources) >= 5, f"SOURCES.md parsed {len(sources)} source blocks", problems)

    # Every customer-facing numeric claim has a VERIFIED source
    for sid, claim, _doc in REQUIRED_NUMERIC_CLAIMS:
        if sid not in sources:
            check(False, f"source {sid} exists in SOURCES.md", problems)
            continue
        status = sources[sid].get("검증 상태", "")
        check("VERIFIED" in status, f"source {sid} marked VERIFIED (got: {status})", problems)

    # Removed numeric claims must not appear in customer documents
    for claim in REMOVED_NUMERIC_CLAIMS:
        for doc in CUSTOMER_DOCS:
            check(claim not in read_md(doc),
                  f"removed numeric claim '{claim}' absent from customer doc {doc}", problems)

    # Deep-link requirement for verified sources
    for sid in DEEP_LINK_REQUIRED_SOURCES:
        if sid not in sources:
            check(False, f"source {sid} exists for deep-link check", problems)
            continue
        url = sources[sid].get("원문 상세 URL", "")
        # A deep link must contain a document/board-article identifier.
        has_id = bool(re.search(r"(nttSeqNo|bbsSeqNo|ac=|download/|/\d+|article_seq|nttId=|law.go.kr/법령/)", url))
        check(has_id, f"source {sid} deep-link URL has a document identifier", problems)
        check(bool(url), f"source {sid} has a non-empty deep-link URL", problems)

    # NOT VERIFIED / INTERNAL HYPOTHESIS sources must not leak numeric claims into customer docs
    for sid in UNVERIFIED_SOURCES:
        if sid in sources:
            status = sources[sid].get("검증 상태", "")
            is_unverified = "NOT VERIFIED" in status or "INTERNAL HYPOTHESIS" in status
            check(is_unverified, f"unverified source {sid} carries a non-VERIFIED status", problems)
            # If it references customer docs, ensure no numeric leakage is possible
            used_docs = sources[sid].get("사용 문서와 페이지", "")
            for doc in CUSTOMER_DOCS:
                if doc in used_docs and "제거" not in used_docs and "미사용" not in used_docs:
                    check(False, f"unverified source {sid} still references customer doc {doc}", problems)

    # ---- Customer-data safety checks ----
    for doc in CUSTOMER_DOCS:
        text = read_md(doc)
        check("실제 고객명" not in text or "기재 금지" in text,
              f"no real customer name usage in {doc}", problems)
        no_claim = (
            "실제 계약·매출 발생 주장 아님" in text
            or "실제 계약·매출 주장" in text
            or "매출 주장 금지" in text
            or ("실제 계약·매출" in text and "아니다" in text)
        )
        check(no_claim, f"no actual contract/revenue claim in {doc}", problems)
        # No verified-customer logo/testimonial/case claims
        check("고객사 로고" not in text, f"no verified-customer logo claim in {doc}", problems)
        check("후기" not in text or "사례" not in text,
              f"no unverified testimonial/case claim in {doc}", problems)
        # Performance goal vs guarantee separation
        check("성과 보장" not in text or "보장하라고 요구" in text or "보장하지 않는다" in text,
              f"performance guarantee separated from goal in {doc}", problems)

    # Placeholders present in SOW
    sow_text = read_md("05-statement-of-work-draft.md")
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
    governance_framing = "사용정책과 거버넌스 요구가 강화되고 있다"
    for f in ["01-one-page-offer.md", "02-ten-page-proposal.md"]:
        text = read_md(f)
        check(governance_framing in text, f"governance framing present in {f}", problems)

    # Public-sector overstatement absent
    for f in CUSTOMER_DOCS:
        text = read_md(f)
        check("공공기관은 실무 단계별 AI 도입 절차를 요구받고 있음" not in text,
              f"no public-sector obligation overstatement in {f}", problems)

    # Unverified market price comparison absent from customer docs
    for f in CUSTOMER_DOCS:
        text = read_md(f)
        check("1억–수억원" not in text, f"no unverified market price range in {f}", problems)
        check("수십만–수백만원" not in text, f"no unverified course price range in {f}", problems)

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
