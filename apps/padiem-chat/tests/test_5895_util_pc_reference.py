"""#5895 — 축사·SNS 화면이 공통 부품으로 내 PC의 예전 글을 쓰고, 결과를 되돌려 저장한다.

What the owner does on these two screens: bring one or more old writings from their own
PC, see them, have the draft written in that voice, then put the draft back on the PC.
The browser module under test is the shipped `static/util-menu.js`; the shared picker
is the shipped `static/pc-file-exchange.js` surface the menu loads on first use.

Three behaviours the CTO asked for are pinned here:
* the reference text travels with the generation request;
* "내 PC에 저장" opens the shared save dialog with the draft and a title+date name;
* a user with no PC gets one plain line and the existing connect entry, not a dead
  button.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _5785_util_runner as util  # noqa: E402


def test_the_reference_text_travels_with_the_generation_request():
    observed = util.run("pcref")
    assert observed["pickCalls"] == 1, observed
    assert observed["preview"].strip(), observed
    assert observed["promptHasReference"] is True, observed
    assert observed["promptNamesFile"] is True, observed


def test_the_draft_is_offered_back_to_the_pc_with_a_title_and_date_name():
    observed = util.run("pcref")
    assert observed["saveCalled"] is True, observed
    assert observed["saveContent"].strip(), observed
    name = observed["saveFileName"]
    assert name.endswith(".txt"), observed
    assert name.startswith("창립기념식_"), observed
    assert len(name.split("_")[1].removesuffix(".txt")) == len("2026-10-28"), observed
    # Nothing asked the owner to confirm before either action.
    assert observed["alerts"] == [], observed


def test_a_user_without_a_pc_gets_a_line_and_the_existing_connect_entry():
    observed = util.run("pcref_nopc")
    assert observed["pickHidden"] is True, observed
    assert observed["noteHidden"] is False, observed
    assert observed["noteText"] == "PC를 연결하면 예전 글을 가져올 수 있습니다.", observed
    assert observed["connectLabel"] == "이 PC 연결", observed
    assert observed["pickerOpened"] == 0, observed


def test_a_sealed_hwp_a_distributed_hwp_and_a_dead_lane_say_so_in_korean():
    observed = util.run("pcref_refusals")
    refusals = observed["refusals"]
    # The refusal codes the Worker and the lane answer are said out loud in the
    # same Korean the picker uses everywhere: a sealed or distributed 한글 file is
    # not a broken picker, and a lane that is down is named as a service.
    assert refusals["hwpEncrypted"] == "암호가 걸린 한글 파일은 읽을 수 없어요.", refusals
    assert refusals["hwpDistributable"] == "배포용으로 저장된 한글 파일은 읽을 수 없어요.", refusals
    assert refusals["laneDown"] == "파일 읽기 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.", refusals
    assert observed["pageErrors"] == [], observed
