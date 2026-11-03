from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
DRAFTS_ROOT = REPO_ROOT / "docs" / "legal" / "drafts"
RETENTION_PLACEHOLDER = re.compile(
    r"\[대표 결정:[^\]]*(?:보관 기간|파기 시점|남는 데이터|거래 기록 보관 기간|삭제 기능·기간)[^\]]*\]"
)


def legal_draft_docs():
    return sorted(DRAFTS_ROOT.rglob("*.md"))


def test_legal_draft_docs_have_no_decision_pending_text():
    matches = [
        f"{path.relative_to(REPO_ROOT)}:{line_number}"
        for path in legal_draft_docs()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "결정 대기" in line
    ]
    assert not matches, "Unresolved retention decision text found: " + ", ".join(matches)


def test_legal_draft_docs_have_no_retention_placeholders():
    matches = []
    for path in legal_draft_docs():
        text = path.read_text(encoding="utf-8")
        for match in RETENTION_PLACEHOLDER.finditer(text):
            line_number = text.count("\n", 0, match.start()) + 1
            matches.append(f"{path.relative_to(REPO_ROOT)}:{line_number}: {match.group(0)}")
    assert not matches, "Unresolved retention placeholders found: " + "; ".join(matches)
