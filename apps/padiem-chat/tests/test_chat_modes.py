"""The chat-mode remnant is gone, and these tests keep it gone.

`app/chat_modes.py` published a four-item catalog — 자동/빠르게/균형/깊게 — while the
request contract accepted only `auto`, B14 automatic model selection had already been
abolished (#4844), and no server code imported the catalog at all. Three of the four
options were unreachable and the fourth named a choice nothing makes. The module, the
`mode` request key, and every client that sent it are removed; this file replaced the
catalog's own tests with checks that the remnant cannot come back.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from app.request_contract import BrowserRequestError, _validate_payload_parts

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]

MODE_CATALOG_COPY = (
    "질문에 맞는 처리 방식을 자동으로 선택합니다.",
    "빠른 응답을 우선하는 모드입니다.",
    "속도와 답변 품질의 균형을 우선합니다.",
    "더 깊은 검토가 필요한 작업을 위한 모드입니다.",
    "현재는 자동 추천 모드만 지원합니다.",
)


def _body(**extra) -> dict:
    payload = {"messages": [{"role": "user", "content": "안녕하세요"}]}
    payload.update(extra)
    return payload


def test_the_mode_catalog_module_is_gone():
    assert not (ROOT / "app" / "chat_modes.py").is_file()
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.chat_modes")


def _code_lines(path: Path) -> str:
    """Source without comment lines, so history may name what was removed."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("#", "//", "/*", "*")):
            continue
        lines.append(line)
    return "\n".join(lines)


def test_nothing_in_the_repo_imports_the_mode_catalog():
    import_names = ("chat_modes", "CHAT_MODE_CATALOG", "resolve_chat_mode",
                    "chat_modes_api_payload", "list_chat_modes", "get_chat_mode_descriptor",
                    "ChatModeDescriptor")
    sources = list((ROOT / "app").rglob("*.py")) + list((ROOT / "static").glob("*.js"))
    for path in sources:
        text = _code_lines(path)
        for name in import_names:
            assert name not in text, f"{path.relative_to(REPO)}: {name}"


def test_mode_is_refused_as_an_unknown_request_item():
    # Not "ignored": a key no client may meaningfully set is refused, the same way
    # every other unknown item is, so nothing mode-shaped can be smuggled back in.
    _validate_payload_parts(_body())
    with pytest.raises(BrowserRequestError) as info:
        _validate_payload_parts(_body(mode="auto"))
    assert info.value.code == "stale_chat_client"
    for value in ("fast", "balanced", "deep"):
        with pytest.raises(BrowserRequestError):
            _validate_payload_parts(_body(mode=value))


def test_the_accepted_request_keys_no_longer_name_a_mode():
    from app import request_contract

    source = (ROOT / "app" / "request_contract.py").read_text(encoding="utf-8")
    accepted = source.split("if set(raw) - {", 1)[1].split("}:", 1)[0]
    assert '"mode"' not in accepted
    assert '"messages"' in accepted and '"tier"' in accepted and '"skill"' in accepted


@pytest.mark.parametrize("copy", MODE_CATALOG_COPY)
def test_the_mode_promise_strings_are_not_reused_elsewhere(copy: str):
    """The catalog's labels were promises nothing keeps; none may survive in app code."""
    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "static").glob("*.js")):
        assert copy not in path.read_text(encoding="utf-8"), path.name


def test_no_client_or_canary_still_sends_mode():
    senders = [
        ROOT / "static" / "app.js",
        ROOT / "static" / "util-menu.js",
        REPO / "apps" / "padiem-council-apps" / "static" / "council-app.js",
        REPO / ".github" / "scripts" / "b62_live_long_context_canary.py",
        REPO / ".github" / "scripts" / "pc_connector_canary.py",
        REPO / ".github" / "scripts" / "b62_cloudflare_mock_smoke.py",
    ]
    for path in senders:
        text = path.read_text(encoding="utf-8")
        assert 'mode: "auto"' not in text, path.name
        assert '"mode": "auto"' not in text, path.name
