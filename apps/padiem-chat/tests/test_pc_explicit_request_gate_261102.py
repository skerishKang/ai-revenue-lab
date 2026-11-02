"""#6686 — a general question never enters the PC lane, so it can never fail
on the PC boundary (Engine admission 503 entitlement_unavailable).

The PC lane's Engine turn requires trusted admission
(apps/padiem-ai-engine/app/execution_admission_service.py:470+). A deployment
whose admission authority is unavailable therefore refused EVERY turn of a
signed-in, PC-linked user with 503 — including "안녕". The cut: only a turn
that itself names PC work (a linked device, a chosen device, or PC-operation
words) attaches the PC lane; every other turn keeps the plain Engine stream
with no ``pc_tools`` and no PC admission.
"""

from __future__ import annotations

import asyncio

from app.chat_pc_drive import pc_explicit_request


def _explicit(text: str, *, named: bool = False, requested: bool = False) -> bool:
    return pc_explicit_request(text, named_device=named, requested_device=requested)


def test_a_general_question_is_never_a_pc_request():
    assert _explicit("안녕") is False
    assert _explicit("3과 5의 최소공배수를 한 문장으로 답해줘") is False
    assert _explicit("오늘 날씨 어때?") is False


def test_pc_operation_words_are_explicit():
    assert _explicit("PC의 드라이브 목록 보여줘") is True
    assert _explicit("파일 목록 확인해 줘") is True
    assert _explicit("바탕화면 좀 봐줘") is True
    assert _explicit("PC 브라우저로 뉴스 열어줘") is True
    assert _explicit("보고서 파일로 저장해 줘") is True


def test_a_named_or_chosen_device_is_explicit():
    assert _explicit("안녕", named=True) is True
    assert _explicit("안녕", requested=True) is True


def test_english_pc_words_are_explicit():
    assert _explicit("list the files on my desktop") is True
    assert _explicit("open the browser") is True
