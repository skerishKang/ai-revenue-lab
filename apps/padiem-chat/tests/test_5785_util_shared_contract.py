"""#5785 — the three 의원3종 tools reuse PADIEM, they do not clone it.

Group: ``shared``. This is the B requirement of the issue: every tool keeps
using the existing login/session, the existing model lane and the existing
project-file store, and adds no endpoint, store or second authority.

The check is behavioural, not a source-text claim: the harness records every
request the shipped ``util-menu.js`` makes while each tool generates once.

Run alone::

    .venv/Scripts/python.exe -m pytest tests/test_5785_util_shared_contract.py -q
    python scripts/util3_test_groups.py shared
"""

from __future__ import annotations

import pytest

from _5785_util_runner import run

ALLOWED = {
    "POST /api/chat",
    "GET /api/projects",
    "POST /api/projects",
    "GET /api/projects/p1/files",
    "POST /api/projects/p1/files",
    # #5895: the authoring screens read whether a PC is linked, and the shared
    # file part fetches one file's words through the PC file-exchange routes that
    # already exist (same owner session, no new store or authority).
    "GET /api/pc/pairings",
    "POST /api/pc/reference",
}


@pytest.fixture(scope="module")
def shared() -> dict:
    return run("shared")


def test_every_tool_generates_through_the_one_model_lane(shared: dict) -> None:
    for tool, calls in shared["perTool"].items():
        assert "POST /api/chat" in calls, f"{tool} must use the existing model lane"


def test_no_tool_invents_its_own_endpoint(shared: dict) -> None:
    unexpected = sorted(set(shared["endpoints"]) - ALLOWED)
    assert not unexpected, unexpected


def test_every_request_keeps_the_session_cookie_contract(shared: dict) -> None:
    assert shared["credentials"] == ["include"]


def test_every_tool_sends_the_same_chat_payload_shape(shared: dict) -> None:
    payloads = shared["chatPayloads"]
    assert len(payloads) == len(shared["perTool"])
    for payload in payloads:
        assert payload["mode"] == "auto"
        assert [m["role"] for m in payload["messages"]] == ["user"]
        assert payload["messages"][0]["content"].strip()


def test_generation_alone_writes_nothing_to_storage(shared: dict) -> None:
    # Saving is a separate, explicit user action in every tool.
    assert shared["projectWrites"] == 0
    assert not shared["alerts"]


def test_each_tool_declares_which_utility_it_is(shared: dict) -> None:
    """The util scope is what keeps a utility out of the calendar branch.

    Offsets come from the recorded per-tool request lists rather than a
    hard-coded order, so a tool that starts making two model calls cannot
    silently shift the assertion onto another tool.
    """
    offset = 0
    seen = {}
    for tool, calls in shared["perTool"].items():
        count = sum(1 for call in calls if call == "POST /api/chat")
        for payload in shared["chatPayloads"][offset:offset + count]:
            seen[tool] = payload.get("util")
        offset += count
    assert offset == len(shared["chatPayloads"])
    assert seen == {"speech": "speech", "sns": "sns", "meeting": "meeting"}


def test_util_api_chat_sends_selected_tier_or_free_and_preserves_server_errors() -> None:
    observed = run("tier")
    assert not observed["pageErrors"]
    expected = {
        "free": "free", "plus": "plus", "pro": "pro", "max": "max", "admin": "admin",
        "absent": "free", "missing_getter": "free", "unknown": "free",
        "uppercase": "free", "null": "free", "number": "free", "undefined": "free",
    }
    assert {row["name"]: row["payload"]["tier"] for row in observed["tiers"]} == expected
    for row in observed["tiers"]:
        assert row["calls"] == 1
        assert row["payload"]["mode"] == "auto"
        assert [message["role"] for message in row["payload"]["messages"]] == ["user"]
        assert row["output"] == "생성된 초안 본문입니다.\n\n두 번째 문단입니다."
    assert {row["name"]: row["output"] for row in observed["errors"]} == {
        "server_message": "생성 실패: 관리자 인증을 확인해 주세요.",
        # A bare "HTTP nnn" never reaches the screen: GEN_ERROR_COPY in
        # util-menu.js resolves unnamed statuses, once, for every util tool.
        "no_message": "생성 실패: 서버 연결이 잠시 끊겼습니다. 잠시 후 다시 시도해 주세요.",
        "non_string": "생성 실패: 이 계정에서는 할 수 없는 요청입니다. 로그인 상태를 확인해 주세요.",
        "not_json": "생성 실패: 서버가 잠시 과부하 상태입니다. 잠시 후 다시 시도해 주세요.",
    }
    assert all(row["calls"] == 1 for row in observed["errors"])
