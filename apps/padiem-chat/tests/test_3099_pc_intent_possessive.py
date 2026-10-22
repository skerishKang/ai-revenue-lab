"""#3099: the possessive PC qualifier must reach the PC files lane.

The 2026-10-22 Chat submission named the PC as "PC의 ..." and was silently
routed to the general Engine lane: no PC run, no dispatch, no error. The gate
only accepted "내 PC" style qualifiers. These assertions pin the qualifier
behaviour and prove the lane does not widen to unqualified file requests.
"""
from __future__ import annotations

from app.chat_pc_drive import is_chat_pc_drive_query, is_chat_pc_files_query

DEEP = "C:\\Users\\limone\\AppData\\Local\\Padiem\\MeshCentralTrial\\5015-conditions-20261022"
LIST_ONLY = "\ud3f4\ub354\uc5d0 \uc788\ub294 \ud30c\uc77c \ubaa9\ub85d\ub9cc \ubcf4\uc5ec\uc918"
POSSESSIVE = "PC\uc758 "
INNER = "\ub0b4 PC\uc758 "


def test_possessive_pc_form_reaches_the_pc_files_lane():
    # The exact qualifier used in the failed submission.
    assert is_chat_pc_files_query(POSSESSIVE + DEEP + " " + LIST_ONLY) is True
    # It is a files request, not a drive-list request.
    assert is_chat_pc_drive_query(POSSESSIVE + DEEP + " " + LIST_ONLY) is False


def test_existing_pc_qualifiers_are_unchanged():
    assert is_chat_pc_files_query(INNER + DEEP + " " + LIST_ONLY) is True


def test_lane_does_not_widen_to_unqualified_requests():
    assert is_chat_pc_files_query(LIST_ONLY) is False
    assert is_chat_pc_files_query("\ub4dc\ub77c\uc774\ube0c \ubaa9\ub85d\ub9cc \ubcf4\uc5ec\uc918") is False



def test_list_only_detector_separates_listing_from_reading():
    from app.chat_pc_drive import is_chat_pc_list_only_query

    deep = "C:\\Users\\limone\\AppData\\Local\\Padiem\\MeshCentralTrial\\5015-conditions-20261022"
    listing = "PC\uc758 " + deep + " \ud3f4\ub354\uc5d0 \uc788\ub294 \ud30c\uc77c \ubaa9\ub85d\ub9cc \ubcf4\uc5ec\uc918"
    reading = "\ub0b4 PC\uc758 MeshCentralTrial \ud3f4\ub354\uc5d0\uc11c \ud30c\uc77c \ubaa9\ub85d\uc744 \ubcf4\uace0, x.txt \ud30c\uc77c \ub0b4\uc6a9\uc744 \uc124\uba85\ud574\uc918"
    assert is_chat_pc_list_only_query(listing) is True
    assert is_chat_pc_list_only_query(reading) is False
    assert is_chat_pc_list_only_query("\ud30c\uc77c \ubaa9\ub85d\ub9cc \ubcf4\uc5ec\uc918") is False


def test_list_only_request_states_scope_without_executing(monkeypatch):
    """No owner lookup and no Engine send happen; the answer states the scope."""
    import asyncio
    import inspect
    from types import SimpleNamespace

    from app import chat_pc_drive as module

    calls = {"resolve": 0, "save": 0}

    async def _resolve(*args, **kwargs):
        calls["resolve"] += 1
        raise AssertionError("authority must not be resolved for a list-only turn")

    async def _save(*args, **kwargs):
        calls["save"] += 1
        return "conv_3099"

    monkeypatch.setattr(module, "auth_ready", lambda request: True)
    monkeypatch.setattr(module, "current_user_id", lambda request: "usr_3099")
    monkeypatch.setattr(module, "_resolve_chat_owner", _resolve)
    monkeypatch.setattr(module, "_save_pair", _save)

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(history_store=object())),
    )
    text = (
        "\ub0b4 PC\uc758 C:\\Users\\limone\\AppData\\Local\\Padiem\\MeshCentralTrial"
        "\\5015-conditions-20261022 \ud3f4\ub354\uc5d0 \uc788\ub294 \ud30c\uc77c \ubaa9\ub85d\ub9cc \ubcf4\uc5ec\uc918"
    )
    allowed = {
        "user_text": text,
        "execution_user_text": None,
        "conversation_id": None,
        "device_id": None,
        "run_id": None,
        "skill": SimpleNamespace(id="auto"),
        "model_id": "unused",
        "tier": "balanced",
    }
    params = inspect.signature(module.execute_chat_pc_drive_lane).parameters
    kwargs = {key: value for key, value in allowed.items() if key in params}
    result = asyncio.run(module.execute_chat_pc_drive_lane(request, **kwargs))

    assert result is not None
    answer, saved = result
    assert saved == "conv_3099"
    assert "\uc9c0\uc6d0 \ubc94\uc704" in answer
    assert calls == {"resolve": 0, "save": 1}
