"""2026-11-05: the AI tier of 의원3종 generations.

This page ships no Chat tier picker, so every request used to carry
tier:"free" — a Plus/Pro/Max or administrator account generated on the Free
tier here. Now the signed-in account's stored selection (#5222 contract,
GET/PUT /api/account/model-selection — the same row Chat reads and writes)
decides the tier, the header offers exactly the tiers the server listed,
labelled as Chat labels them, and the server stays the only authority: a
refused change reverts, and every request is still verified server-side.

The harness runs the shipped JS against a recording fake of the existing
endpoints; nothing here invents a tier the server did not list.
"""
from __future__ import annotations

from pathlib import Path

from _council_module import run

STATIC = Path(__file__).resolve().parents[1] / "static"
JS = (STATIC / "council-app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "council-app.css").read_text(encoding="utf-8")


def test_the_header_offers_only_the_servers_tiers_with_chat_labels() -> None:
    pro = run("tier")["pro"]
    assert pro["wrapHidden"] is False
    assert pro["choices"] == ["free", "plus", "pro"], "allowed_tiers verbatim — no admin lane the server did not list"
    assert pro["labels"] == ["Padiem Free", "Padiem Plus", "Padiem Pro"]
    assert pro["disabled"] is False


def test_the_restored_choice_rides_the_generation_and_a_change_is_saved() -> None:
    pro = run("tier")["pro"]
    assert pro["initial"] == "plus", "the account's stored choice, not its highest tier and not free"
    assert pro["firstTier"] == "plus"
    assert pro["secondTier"] == "pro", "the new choice rides the next request"
    assert pro["writes"][0] == {"tier": "pro"}, "saved through the same account route Chat uses"


def test_a_refused_tier_reverts_and_says_so() -> None:
    pro = run("tier")["pro"]
    assert pro["writes"][-1] == {"tier": "free"}, "the attempt reached the server"
    assert pro["afterRefusal"] == "pro" and pro["selectAfterRefusal"] == "pro"
    assert pro["refusalStatus"] == "이 계정에서는 고를 수 없는 AI 등급입니다."


def test_a_free_only_account_sees_one_fixed_choice_and_sends_free() -> None:
    free = run("tier")["free"]
    assert free["wrapHidden"] is False
    assert free["choices"] == ["free"]
    assert free["disabled"] is True, "one choice is a label, not a control"
    assert free["tier"] == "free"


def test_a_signed_out_visitor_has_no_tier_control_and_no_writes() -> None:
    obs = run("tier")
    assert obs["guest"]["wrapHidden"] is True
    assert obs["guest"]["writes"] == 2, "no write beyond the two the Pro scenario made"
    assert obs["alerts"] == [] and obs["pageErrors"] == []


def test_the_control_names_padiem_tiers_only() -> None:
    # The 2026-11-04 rule: no model or provider name on a user screen — tiers only.
    assert 'id="councilTier"' in HTML and 'id="councilTierWrap"' in HTML
    for forbidden in ("gemini", "openai", "claude", "deepseek", "gemma", "anthropic", "mistral"):
        assert forbidden not in JS.lower(), forbidden
        assert forbidden not in HTML.lower(), forbidden
    assert "Padiem 관리자" in JS and "Padiem Max" in JS
    # The control sits inside the single 44px floor block (#6075), never restated.
    assert ".council-tier select" in CSS
