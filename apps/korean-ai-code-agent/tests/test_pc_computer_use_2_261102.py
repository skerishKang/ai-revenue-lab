"""#6460 step 2 — open key grammar, one-shot typed text on the PC side.

No relay, no PC: the port's parsers and the executor's claim handling are
exercised with injected fakes. The value must be typed exactly once, only from
the claim that carried it, and must never appear in a persisted record.
"""

from __future__ import annotations

import json

import pytest

from kagent.local_agent_meshcentral_desktop_port import (
    MeshCentralDesktopRefused, parse_desktop_op, parse_key_combo,
)
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshDispatch, _desktop_dispatch_text,
)


@pytest.mark.parametrize("spec", [
    "f5", "alt+f4", "win+r", "ctrl+shift+esc", "alt+tab", "shift+delete",
    "ctrl+alt+t", "f12", "left", "pagedown", "a", "7",
])
def test_the_combo_vocabulary_is_open(spec):
    assert parse_desktop_op("desktop:keys\n" + spec) == ("keys", spec)
    assert parse_key_combo(spec)


@pytest.mark.parametrize("spec", [
    "ctrl+alt+del", "ctrl+alt+delete", "hyper+a", "ctrl+ctrl+a", "ctrl+",
    "+a", "a+b", "ctrl+alt+shift+win+a",
])
def test_unknown_names_and_the_sas_chord_stay_refused(spec):
    with pytest.raises(MeshCentralDesktopRefused):
        parse_desktop_op("desktop:keys\n" + spec)


def test_a_modifier_alone_is_refused():
    with pytest.raises(MeshCentralDesktopRefused):
        parse_key_combo("shift")


def test_korean_emoji_and_newlines_survive_the_op_grammar():
    text = "안녕하세요 🙂\n둘째 줄"
    assert parse_desktop_op("desktop:type\n" + text) == ("type", text)


class _Relay:
    def __init__(self):
        self.frames = []

    def send_binary(self, frame):
        self.frames.append(bytes(frame))


class _Session:
    def __init__(self):
        self.relay = _Relay()


def test_a_newline_is_the_enter_key_not_a_literal_character():
    from kagent.local_agent_meshcentral_desktop_port import _DesktopSession

    session = _DesktopSession.__new__(_DesktopSession)
    session._relay = _Relay()
    sent = session.type_text("a\nb")
    assert sent == 3
    joined = b"".join(session._relay.frames)
    assert joined  # frames were sent; the exact encoding is the relay's own
    # The Enter pair is the VK 13 key, never U+000A.
    assert any(bytes([13]) in frame for frame in session._relay.frames)


def test_the_executor_types_only_the_delivered_value():
    dispatch = OracleMeshDispatch(
        dispatch_id="dsp_" + "a" * 28, nonce="n" * 32, node_ref="node//pc",
        file_path="command", command_id="cmd", run_id="run", kind="desktop",
        command_text="desktop:type\n#5:abc12345:" + "c" * 32,
        desktop_text="안녕하세요",
    )
    assert _desktop_dispatch_text(dispatch) == "안녕하세요"


def test_a_claim_without_the_value_is_refused():
    dispatch = OracleMeshDispatch(
        dispatch_id="dsp_" + "a" * 28, nonce="n" * 32, node_ref="node//pc",
        file_path="command", command_id="cmd", run_id="run", kind="desktop",
        command_text="desktop:type\n#5:abc12345:" + "c" * 32,
    )
    assert _desktop_dispatch_text(dispatch) is None
