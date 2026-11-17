"""T4 conversation_turn 300줄 아래로 — 공개 진입점 골든 (#7814).

리팩터 전 origin/main(b7764abcf)에서 뽑는다. 기존 B66 대역을 그대로 재사용해
오류 3개와 정상 2개의 최종 응답·모델 호출·저장 행을 고정한다.

재생성은 리팩터 전 main에서만 실행한다:
  PADIEM_REGEN_7814_CONV_TURN=1 pytest apps/padiem-chat/tests/test_7814_b66_conversation_turn_table.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from test_b66_ai_conversation_routes_4412 import (
    MODEL,
    act,
    ctx,
    model_reply,
    send,
    sign_in,
)

GOLDEN_PATH = (
    Path(__file__).resolve().parent / "test_7814_b66_conversation_turn_table_golden.json"
)


def _unauthenticated(c):
    return c.client.post(
        "/api/b66/ai/conversation",
        json={"model_id": MODEL, "action": "message", "message": "안녕", "revision": 0},
    )


def _unsupported_field(c):
    sign_in(c)
    return send(c, "안녕", revision=0, intent="quote_create")


def _owner_field(c):
    sign_in(c)
    return send(c, "안녕", revision=0, owner="usr_" + "b" * 32)


def _general_message(c):
    sign_in(c)
    return send(
        c, "안녕, 반가워", revision=0,
        answer=model_reply("안녕하세요! 무엇을 도와드릴까요?", "general"),
    )


def _choose_method(c):
    sign_in(c)
    first = send(
        c, "견적서를 만들어 주세요.", revision=0,
        answer=model_reply("견적서를 만들어 드릴게요.", "quote_create"),
    )
    assert first.status_code == 200, first.text
    return act(c, "choose_method", revision=first.json()["revision"], method="flexible")


CASES = [
    ("비로그인", "error", _unauthenticated),
    ("미지원_필드", "error", _unsupported_field),
    ("소유자_필드", "error", _owner_field),
    ("일반_메시지", "success", _general_message),
    ("작성방식_선택", "success", _choose_method),
]


def _row(c):
    rows = c.db.execute(
        "SELECT user_id, workspace_id, state_json, revision FROM b66_ai_conversation"
    ).fetchall()
    return [
        {
            "user_id": row["user_id"],
            "workspace_id": row["workspace_id"],
            "state": json.loads(row["state_json"]),
            "revision": row["revision"],
        }
        for row in rows
    ]


def _run_case(name, kind, runner, c):
    response = runner(c)
    return {
        "case": name,
        "kind": kind,
        "response": {
            "status": response.status_code,
            "body": response.json(),
            "content_type": response.headers.get("content-type"),
        },
        "resolver_calls": [
            {
                "selected_model_id": req.selected_model_id,
                "task_id": req.task_id,
                "output_contract": req.output_contract,
            }
            for req in c.resolver.calls
        ],
        "model_calls": c.model.calls,
        "stored": _row(c),
    }


@pytest.mark.parametrize("name,kind,runner", CASES, ids=[c[0] for c in CASES])
def test_conversation_turn_table_is_identical_to_golden(name, kind, runner, ctx):
    row = json.loads(json.dumps(_run_case(name, kind, runner, ctx), ensure_ascii=False))
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if os.environ.get("PADIEM_REGEN_7814_CONV_TURN") == "1":
        found = False
        for index, item in enumerate(data):
            if item["case"] == name:
                data[index] = row
                found = True
        if not found:
            data.append(row)
        GOLDEN_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    expected = next(item for item in data if item["case"] == name)
    assert row == expected
