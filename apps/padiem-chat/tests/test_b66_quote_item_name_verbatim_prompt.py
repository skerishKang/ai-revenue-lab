"""B66 item-name extraction prompt preserves exact customer source spelling."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
def test_runtime_prompt_does_not_rewrite_customer_item_names():
    source=(ROOT/"apps/padiem-chat/app/b66_quote_conversation.py").read_text(encoding="utf-8")
    assert "품목명이 원문에 명확히 나타나면 내부 공백·숫자·단위 접미사까지 원문 그대로 복사하십시오." in source
    assert "원문 품목명이 불명확하면 임의로 공백을 붙이거나 지우지 말고 이름만 null로 두십시오." in source

def test_fixed_synthetic_benchmark_prompt_checks_item_name_lexical_fidelity():
    source=(ROOT/".github/scripts/b66_quote_model_benchmark.py").read_text(encoding="utf-8")
    assert "원문에서 내부 공백과 숫자·접미사를 바꾸지 말고 정확히 복사하세요." in source
    assert "원문 '부품 01호'는 '부품 01 호'가 아닙니다." in source
    assert "불명확한 품목명은 null" in source
