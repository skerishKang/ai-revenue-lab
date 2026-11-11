"""#7459: 내부 pc_scope 마커가 대화 불러오기 응답 본문에 노출되지 않는다."""
import importlib.util
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "app" / "history.py"


def _fn():
    text = SRC.read_text(encoding="utf-8")
    start = text.index("def strip_pc_scope_marker(")
    end = text.index("def pc_scope_notice(", start)
    ns: dict = {}
    exec(text[start:end], ns)
    return ns["strip_pc_scope_marker"]


def test_marker_removed_notice_kept():
    strip = _fn()
    stored = "PC 범위 안내\n<!--pc_scope:{\"admitted\":\"x\"}-->"
    assert strip(stored) == "PC 범위 안내"


def test_plain_text_untouched():
    strip = _fn()
    assert strip("일반 답변") == "일반 답변"


def test_loader_uses_strip():
    text = SRC.read_text(encoding="utf-8")
    assert "strip_pc_scope_marker(str(row.get(\"content\", \"\")))" in text
