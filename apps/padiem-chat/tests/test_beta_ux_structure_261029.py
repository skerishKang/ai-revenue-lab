"""#6100 beta-ux structure pass — the speech 참고 글 lane and the shared dialog's
root state.

The SNS tool already leads its form with a 참고 글 fieldset (PR #6098); the speech
tool's PC reference still floats inside the tone fieldset, and the shared PC
file-exchange dialog ships an 이전 폴더 button that looks pressable at the root
where there is no parent folder to go to. These pins hold the shipped bytes to
the structure the captures document; the rendered numbers live in the
padiem-reports/2026-10-29 evidence.
"""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_speech_reference_lane_leads_the_form_like_sns():
    # 2026-11-01: both authoring forms moved to /apps/council/, and the 참고 글
    # lane still leads each of them before its first field.
    council = (STATIC.parent.parent / "padiem-council-apps" / "static" / "council-app.js").read_text(encoding="utf-8")
    speech = council[council.index("const speechModule"):council.index("const snsModule")]
    assert 'refFieldset.appendChild(el("legend", null, "참고 글"))' in speech
    assert speech.index("refFieldset") < speech.index('el("legend", null, "행사 정보")')
    sns = council[council.index("const snsModule"):council.index("const meetingModule")]
    assert 'refFieldset.appendChild(el("legend", null, "참고 글"))' in sns
    assert sns.index("refFieldset") < sns.index("const fields = [")


def test_dialog_back_is_disabled_at_the_root_and_stays_named_on_mobile():
    script = (STATIC / "pc-file-exchange.js").read_text(encoding="utf-8")
    # The dialog opens at the root, so the button is born disabled and
    # paintList keeps the state glued to the path the owner is in.
    assert 'back.disabled = state.path === "."' in script
    assert "nodes.back.disabled = state.path" in script
    # The icon-only mobile form still says its name to assistive tech.
    assert 'back.setAttribute("aria-label", copy("pc-exchange-up"))' in script

    css = (STATIC / "pc-file-exchange.css").read_text(encoding="utf-8")
    # Disabled is visible, not just inert.
    assert ".pc-exchange-back:disabled" in css
    assert "opacity: 0.45" in css
    # One tool row on the phone: the words give way to the arrow, the touch
    # target keeps its 44px floor.
    assert "@media (max-width: 480px)" in css
    mobile = css.split("@media (max-width: 480px)", 1)[1]
    assert ".pc-exchange-back" in mobile
    assert "min-width: 44px" in mobile
    assert "font-size: 0" in mobile
