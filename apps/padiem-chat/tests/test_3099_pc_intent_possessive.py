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
