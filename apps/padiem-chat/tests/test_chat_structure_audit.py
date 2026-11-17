"""CSS 구조 감사 도구의 회귀 시험."""

from __future__ import annotations

import importlib.util
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parents[2]
TOOL_PATH = ROOT / "tools" / "chat_structure_audit.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "chat_structure_audit_under_test", TOOL_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_css_counts_first_rule_after_import_statement() -> None:
    tool = _load_tool()
    rules = tool.parse_css(
        "@import url('./base.css?variant=a;b');\n"
        ".first-rule { color: #fff; background-color: rgba(0, 0, 0, .5); }\n"
        ".second-rule { color: #000; }"
    )

    assert [rule.selector for rule in rules] == [".first-rule", ".second-rule"]
    first_rule_colors = [
        decl.value for decl in rules[0].decls if tool.COLOR_RX.search(decl.value)
    ]
    assert first_rule_colors == ["#fff", "rgba(0, 0, 0, .5)"]
