from pathlib import Path

from css_rules import parse_rules

_TESTS = Path(__file__).resolve().parents[1]
_SHEET_DIR = _TESTS.parent / "static"

TOKEN_RULES = parse_rules((_SHEET_DIR / "padiem-tokens.css").read_text(encoding="utf-8"))
SHEET_TEXT = (_SHEET_DIR / "styles.css").read_text(encoding="utf-8")
