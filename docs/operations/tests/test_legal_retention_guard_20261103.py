"""#6764: 보관 기간 확정(2026-11-03)과 CGI 판매자 정보 표시가 되돌아가지 않는지 본다.

법률 문서는 게시 전 초안이라 계속 손대는 파일이다. 확정된 기간을 다시 빈칸으로
되돌리거나, 확인하지 않은 판매자 정보를 새로 만드는 일을 여기서 막는다.
이 파일은 PR 게이트가 통째로 실행하는 docs/operations/tests에 둔다.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DRAFTS = ROOT / "docs" / "legal" / "drafts"

PLACEHOLDER = re.compile(
    r"\[대표 결정:[^\]]*(?:보관 기간|파기 시점|남는 데이터|거래 기록 보관 기간|삭제 기능·기간)[^\]]*\]"
)


def docs() -> list[Path]:
    return sorted(DRAFTS.rglob("*.md"))


class LegalRetentionGuardTest(unittest.TestCase):
    def test_drafts_exist(self) -> None:
        self.assertGreaterEqual(len(docs()), 7)

    def test_no_pending_retention_text(self) -> None:
        hits = [
            f"{path.relative_to(ROOT)}:{number}"
            for path in docs()
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if "결정 대기" in line
        ]
        self.assertEqual(hits, [])

    def test_no_retention_placeholder(self) -> None:
        hits = []
        for path in docs():
            text = path.read_text(encoding="utf-8")
            hits += [f"{path.relative_to(ROOT)}: {m.group(0)}" for m in PLACEHOLDER.finditer(text)]
        self.assertEqual(hits, [])

    def test_common_policy_states_each_period_and_its_law(self) -> None:
        text = (DRAFTS / "privacy_common_ko.md").read_text(encoding="utf-8")
        for period in ("6개월", "5년", "3년", "3개월", "90일", "1년", "28일"):
            with self.subTest(period=period):
                self.assertIn(period, text)
        for law in (
            "전자상거래 등에서의 소비자보호에 관한 법률",
            "통신비밀보호법",
            "국세기본법",
        ):
            with self.subTest(law=law):
                self.assertIn(law, text)

    def test_withdrawal_section_keeps_record_period(self) -> None:
        text = (DRAFTS / "terms_common_ko.md").read_text(encoding="utf-8")
        section = text.split("## 4. 계정 탈퇴", 1)[1].split("## 5.", 1)[0]
        self.assertIn("탈퇴 기록은", section)
        self.assertIn("1년", section)
        self.assertIn("5년", section)

    def test_operational_gap_table_stays(self) -> None:
        text = (DRAFTS / "README.md").read_text(encoding="utf-8")
        self.assertIn("## 운영 반영 필요", text)
        gaps = text.split("## 운영 반영 필요", 1)[1].split("\n## ", 1)[0]
        rows = [line for line in gaps.splitlines() if line.startswith("| ") and line.count("|") >= 5]
        self.assertGreaterEqual(len(rows) - 1, 8)

    def test_shop_seller_disclosure_matches_the_owner_decision(self) -> None:
        text = (DRAFTS / "services" / "cgi_shop_ko.md").read_text(encoding="utf-8")
        self.assertIn("- 상호: (주)시지아이", text)
        self.assertIn("- 대표자: 김범신·백정아(각자대표)", text)
        self.assertIn("- 사업자등록번호: 410-86-46283", text)
        # 대표가 판매자 정보에서 확인한 신고번호를 고정한다. 보호책임자 실명은 별도 확인 전이다.
        self.assertIn("- 통신판매업 신고번호: 2025-전남장성-94", text)
        self.assertNotIn("- 개인정보보호책임자:", text)
        self.assertNotIn("법령 이름과 시행일은 확인되지 않아", text)


if __name__ == "__main__":
    unittest.main()
