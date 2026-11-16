"""#7841: 모델 우선 턴이 PC 도구를 몇 개 줬고, 모델이 하나를 골랐는지 한 줄에 남긴다.

계측만 한다. 판정도 실행도 바뀌지 않으며, 줄에는 개수만 실린다 — 도구 이름·기기 id·
계정 값은 절대 들어가지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from app.orchestration_timing import OrchestrationTiming

ROUTES = Path(__file__).resolve().parents[1] / "app" / "orchestration_routes.py"


def test_both_counts_default_to_none_when_the_question_was_never_asked():
    line = OrchestrationTiming().line()

    assert " pc_tools_offered=none tool_called=none " in line, line


def test_a_count_and_a_choice_are_recorded():
    timing = OrchestrationTiming()
    timing.set_pc_tools_offered(4)
    timing.set_tool_called(1)

    line = timing.line()

    assert " pc_tools_offered=4 tool_called=1 " in line, line


def test_zero_is_a_measurement_not_an_absence():
    # The lane carried no tool: that is a measured 0, different from "none".
    timing = OrchestrationTiming()
    timing.set_pc_tools_offered(0)
    timing.set_tool_called(0)

    line = timing.line()

    assert " pc_tools_offered=0 tool_called=0 " in line, line


def test_only_numbers_and_none_can_ride_these_two_fields():
    timing = OrchestrationTiming()
    # Anything that is not a small count, and any choice that is not 0/1, is
    # refused outright: a string could carry a name, a device or an account.
    for bad_count in ("1", 3.5, True, -1, 65, [1, 2], {"tools": 2}, None):
        timing.set_pc_tools_offered(bad_count)
    for bad_choice in ("1", 2, -1, True, None, {"called": 1}):
        timing.set_tool_called(bad_choice)

    line = timing.line()

    assert " pc_tools_offered=none tool_called=none " in line, line


def test_the_route_records_the_count_it_offered_and_whether_one_was_requested():
    source = ROUTES.read_text(encoding="utf-8")

    # Offered: the model-first lane's own tool tuple, immediately after it exists.
    offered = source.index("tools = pc_tools_for_context(pc_context, user_text)")
    recorded = source.index("timing.set_pc_tools_offered(len(tools))")
    assert 0 < recorded - offered < 400, (offered, recorded)
    # Requested: both answer shapes mark 1 when the model named a tool and 0 when
    # it answered in text, so the field can never be missing from a model-first turn.
    assert source.count("timing.set_tool_called(1)") == 2
    assert source.count("timing.set_tool_called(0)") == 2