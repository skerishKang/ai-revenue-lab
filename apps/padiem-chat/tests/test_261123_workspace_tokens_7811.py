"""#7811 C2 — cinematic workspace 바탕·컨트롤 색을 쓰임새 토큰으로.

padiem-cinematic-workspace.css의 색 리터럴 51개 선언을 padiem-tokens.css의
쓰임새 토큰으로 옮긴다. 값은 치환 전 리터럴 그대로이고 다섯 테마에서 같은
값을 쓰므로 :root 하나에만 두며 테마 블록에서는 덮지 않는다.
"""
from __future__ import annotations

import re

from css_rules import declaration
from _support.workspace_tokens_source import SHEET_RULES, SHEET_TEXT, TOKEN_RULES

COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

ROOT_TOKENS = {
    "--ws-item-text": "rgba(244, 247, 251, .66)",
    "--ws-current-wash": "rgba(255, 255, 255, .075)",
    "--ws-current-glow": "rgba(136, 201, 255, .32)",
    "--ws-soft-wash": "rgba(255, 255, 255, .055)",
    "--ws-control-hover-edge": "rgba(255, 255, 255, .16)",
    "--ws-control-hover-wash": "rgba(255, 255, 255, .07)",
    "--ws-control-hover-text": "#fff",
    "--ws-control-muted-text": "rgba(255, 255, 255, .52)",
    "--ws-control-hover-edge-strong": "rgba(255, 255, 255, .20)",
    "--ws-divider": "rgba(255, 255, 255, .07)",
    "--ws-banner-edge": "rgba(255, 255, 255, .12)",
    "--ws-banner-accent": "rgba(255, 255, 255, .42)",
    "--ws-banner-wash-end": "rgba(255, 255, 255, .02)",
    "--ws-banner-shadow": "rgba(0, 0, 0, .12)",
    "--ws-form-wash": "rgba(255, 255, 255, .018)",
    "--ws-dialog-edge": "rgba(255, 255, 255, .08)",
    "--ws-dialog-kicker-text": "rgba(255, 255, 255, .62)",
    "--ws-input-edge": "rgba(255, 255, 255, .11)",
    "--ws-input-wash": "rgba(255, 255, 255, .045)",
    "--ws-input-text": "rgba(255, 255, 255, .9)",
    "--ws-input-focus-edge": "rgba(255, 255, 255, .28)",
    "--ws-input-focus-glow": "rgba(136, 201, 255, .045)",
    "--ws-danger-text": "#ffabab",
    "--ws-secondary-text": "rgba(255, 255, 255, .64)",
    "--ws-primary-hover-wash": "rgba(255, 255, 255, .14)",
    "--ws-file-add-text": "rgba(255, 255, 255, .58)",
    "--ws-file-row-edge": "rgba(255, 255, 255, .065)",
    "--ws-card-wash": "rgba(255, 255, 255, .03)",
    "--ws-danger-hover-text": "#ffb5b5",
    "--ws-attachment-edge": "rgba(255, 255, 255, .10)",
    "--ws-attachment-text": "rgba(255, 255, 255, .74)",
    "--ws-answer-hover-edge": "rgba(255, 255, 255, .18)",
    "--ws-output-text": "rgba(247, 249, 252, .84)",
    "--ws-label-text": "rgba(255, 255, 255, .50)",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_root_tokens_hold_the_pre_change_literals() -> None:
    roots = [r for r in TOKEN_RULES if r.selectors == [":root"] and r.media is None]
    assert len(roots) == 1
    for name, literal in ROOT_TOKENS.items():
        assert _norm(declaration(roots[0], name)) == _norm(literal), name


def test_tokens_are_theme_invariant() -> None:
    """같은 값을 다섯 테마가 쓰므로 테마 블록에서 덮지 않는다."""
    for rule in TOKEN_RULES:
        if rule.media is not None or not rule.selectors:
            continue
        if not rule.selectors[0].startswith("html[data-theme="):
            continue
        for name in ROOT_TOKENS:
            assert declaration(rule, name) is None, (rule.selectors[0], name)


#: 7811 C5: 이 시트에서 이 토큰을 읽던 선언(배너 바깥 그림자·테두리, hover·focus
#: 색)은 기본 규칙의 우선 표시에 늘 져서 칠해진 적이 없어 지웠다. 토큰 정의는
#: 다른 토큰(outputs 쪽)이 읽거나 값 기록으로 남긴다.
NO_LONGER_READ_HERE = {
    "--ws-control-hover-text",
    "--ws-banner-edge",
    "--ws-banner-shadow",
    "--ws-input-focus-edge",
    "--ws-primary-hover-wash",
}


def test_sheet_consumes_tokens_without_raw_colors() -> None:
    assert COLOR.search(SHEET_TEXT) is None
    for name in ROOT_TOKENS:
        if name in NO_LONGER_READ_HERE:
            assert f"var({name})" not in SHEET_TEXT, name
            continue
        assert f"var({name})" in SHEET_TEXT, name
    assert SHEET_TEXT.count("var(--text-veil-strong)") == 1
    assert len(SHEET_RULES) > 0


def test_tokens_are_defined_only_in_the_token_file() -> None:
    for name in ROOT_TOKENS:
        assert f"{name}:" not in SHEET_TEXT, name
