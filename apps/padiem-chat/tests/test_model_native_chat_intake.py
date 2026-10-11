"""B62 browser native model intake, distinct from bounded saved previews (#4379)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.history import MAX_HISTORY_MESSAGE_CHARS, _bounded_text
from app.request_contract import BrowserRequestError, MAX_BROWSER_BODY_BYTES, _validate_payload


ROOT = Path(__file__).resolve().parents[1]


def test_browser_contract_forwards_messages_past_old_count_and_character_caps():
    long_text = "긴 입력 " * 10_000 + "끝"
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i}"} for i in range(40)]
    messages.append({"role": "user", "content": long_text})
    validated, *_ = _validate_payload({"messages": messages, "mode": "auto"})
    assert validated == messages
    assert len(validated) == 41
    assert validated[-1]["content"] == long_text
    assert MAX_BROWSER_BODY_BYTES == 6_000_000


def test_browser_contract_retains_role_field_and_empty_message_guards():
    for messages in ([], [{"role": "tool", "content": "unsafe"}], [{"role": "user", "content": ""}], [{"role": "user", "content": "x", "extra": "unsafe"}]):
        with pytest.raises(BrowserRequestError):
            _validate_payload({"messages": messages})


def test_persisted_history_is_transparently_marked_as_preview():
    original = "전사 " * 10_000 + "끝"
    preview = _bounded_text(original, "user_text")
    assert len(preview) <= MAX_HISTORY_MESSAGE_CHARS
    assert preview.startswith(original[:100])
    assert "\n[저장 미리보기:" in preview
    assert _bounded_text("short", "user_text") == "short"


def test_chat_ui_has_no_textarea_maxlength_but_claw_retains_its_guard():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    composer = html.split('id="messageInput"', 1)[1].split("</textarea>", 1)[0]
    assert "maxlength=" not in composer
    assert 'if (isClaw) input.setAttribute("maxlength", "8000");' in app_js
    assert 'else input.removeAttribute("maxlength");' in app_js
    assert 'input.setAttribute("maxlength", "4000");' in app_js
