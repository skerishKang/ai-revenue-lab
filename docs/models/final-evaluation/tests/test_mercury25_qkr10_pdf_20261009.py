"""B14 Mercury QKR 10 and local QuoteCore PDF scope guard, evidence truth only."""
from pathlib import Path
DOC=Path(__file__).resolve().parents[1]
def test_mercury_qkr10_is_strict_eight_not_ten():
    report=(DOC/"B14_FINAL_MERCURY_2_5_2026-10-09.md").read_text(encoding="utf-8")
    ledger=(DOC/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md").read_text(encoding="utf-8")
    assert "HTTP200 10/10" in report
    assert "엄격 정확도 PASS 8/10" in report
    assert "QKR-008" in report and "12개 전부 공백 차이" in report
    assert "QKR-009" in report and "Normalizer `ValueError`" in report
    assert "재시도·fallback 없음" in ledger
def test_mercury_qkr008_local_pdf_not_customer_f6():
    report=(DOC/"B14_FINAL_MERCURY_2_5_2026-10-09.md").read_text(encoding="utf-8")
    ledger=(DOC/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md").read_text(encoding="utf-8")
    for flag in ("12 items","6,500,000원","650,000원","7,150,000원","133,473 bytes","2페이지"):
        assert flag in report
    assert "CUSTOMER_F6_NOT_TESTED" in ledger
    assert "품목명 공백" in ledger
    assert "FINAL_APPROVAL_IN_PROGRESS" in report
