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
