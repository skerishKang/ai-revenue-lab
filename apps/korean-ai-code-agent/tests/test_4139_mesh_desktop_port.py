"""#4139 desktop lane — unit tests for the MeshCentral desktop port.

Every expected byte below is hand-computed from the official browser client
(``public/scripts/agent-desktop-0.0.2.js``) and its redirect wrapper
(``agent-redir-ws-0.0.1.js``): a frame the tests accept is a frame the real
agent answers. No test touches the network; the port's websocket factory is
a scripted double, and tile sizing/compositing are stubs unless Pillow is
present (then one real compositing test also runs).
"""
from __future__ import annotations

import base64
import hashlib
import json
import socket

import pytest

from kagent.local_agent_meshcentral_desktop_port import (
    DesktopTile,
    MeshCentralDesktopOutcome,
    MeshCentralDesktopPort,
    MeshCentralDesktopRefused,
    MscAccumulator,
    StdlibWebSocket,
    build_ws_handshake_request,
    check_ws_handshake_response,
    compose_screenshot_jpeg,
    decode_ws_frames,
    encode_ws_frame,
    msc_click,
    msc_close,
    msc_compression,
    msc_frame,
    msc_input_lock_query,
    msc_key,
    msc_mouse_down,
    msc_mouse_move,
    msc_mouse_up,
    msc_options,
    msc_pong,
    msc_refresh,
    msc_screen_ack,
    msc_unicode,
    msc_unicode_text,
    msc_unpause,
    parse_desktop_op,
    parse_msc_packet,
    parse_tile,
)
import kagent.local_agent_meshcentral_desktop_port as desktop_module


# ---- op grammar ------------------------------------------------------

def test_parse_capture():
    assert parse_desktop_op("desktop:capture") == ("capture", None)


def test_parse_capture_rejects_argument():
    with pytest.raises(MeshCentralDesktopRefused):
        parse_desktop_op("desktop:capture\n800x600")


def test_parse_type_keeps_text_verbatim():
    op, arg = parse_desktop_op("desktop:type\nPADIEM-GUI-E2E-261017-OK")
    assert op == "type"
    assert arg == "PADIEM-GUI-E2E-261017-OK"


def test_parse_type_korean_multiline():
    op, arg = parse_desktop_op("desktop:type\n한글 입력\n둘째 줄")
    assert (op, arg) == ("type", "한글 입력\n둘째 줄")


def test_parse_type_rejects_control_characters():
    with pytest.raises(MeshCentralDesktopRefused):
        parse_desktop_op("desktop:type\nbad\x07text")
    with pytest.raises(MeshCentralDesktopRefused):
        parse_desktop_op("desktop:type\nbad\rtext")


def test_parse_type_rejects_empty():
    with pytest.raises(MeshCentralDesktopRefused):
        parse_desktop_op("desktop:type\n   ")


@pytest.mark.parametrize("spec", [
    "enter", "esc", "tab", "backspace", "delete",
    "ctrl+s", "ctrl+c", "ctrl+v", "ctrl+a", "alt+f4", "win+r", "win",
])
def test_parse_known_key_combos(spec):
    assert parse_desktop_op("desktop:keys\n" + spec) == ("keys", spec)


def test_parse_keys_case_insensitive():
    assert parse_desktop_op("desktop:keys\nCTRL+S") == ("keys", "ctrl+s")


@pytest.mark.parametrize("spec", ["ctrl+alt+del", "f5", "shift", "", "enter " * 1 + "x"])
def test_parse_unknown_key_combos_refused(spec):
    with pytest.raises(MeshCentralDesktopRefused):
        parse_desktop_op("desktop:keys\n" + spec)


def test_parse_click():
    assert parse_desktop_op("desktop:click\n960,540") == ("click", "960,540")


@pytest.mark.parametrize("bad", [
    "desktop:", "desktop: clic", "command:hostname.exe", "desktop:capture\nx",
    "desktop:click\n960", "desktop:click\n960,540,1", "desktop:click\n-1,5",
    "desktop:click\n99999,5", "desktop:click\na,b", "desktop:type",
])
def test_parse_refusals(bad):
    with pytest.raises(MeshCentralDesktopRefused):
        parse_desktop_op(bad)


def test_parse_non_text_refused():
    with pytest.raises(MeshCentralDesktopRefused):
        parse_desktop_op(None)


# ---- MSC frames: byte-identical to the browser -------------------------

def test_key_down_up():
    assert msc_key(1, 65) == bytes((0x00, 0x01, 0x00, 0x06, 0x00, 0x41))
    assert msc_key(2, 65) == bytes((0x00, 0x01, 0x00, 0x06, 0x01, 0x41))


def test_key_extended_windows_key():
    # SendStartMsg: EXDOWN/EXUP of L-Windows (0x5B).
    assert msc_key(5, 0x5B) == bytes((0x00, 0x01, 0x00, 0x06, 0x04, 0x5B))
    assert msc_key(4, 0x5B) == bytes((0x00, 0x01, 0x00, 0x06, 0x03, 0x5B))


def test_key_extended_flag_remap():
    # extendedKey=True turns DOWN into EXDOWN bytes and UP into EXUP bytes.
    assert msc_key(1, 37, extended=True) == bytes((0x00, 0x01, 0x00, 0x06, 0x04, 37))
    assert msc_key(2, 37, extended=True) == bytes((0x00, 0x01, 0x00, 0x06, 0x03, 37))


def test_unicode_frames():
    assert msc_unicode(1, 65) == bytes((0x00, 0x55, 0x00, 0x07, 0x00, 0x00, 0x41))
    assert msc_unicode(2, 65) == bytes((0x00, 0x55, 0x00, 0x07, 0x01, 0x00, 0x41))
    assert msc_unicode_text("A") == [msc_unicode(1, 65), msc_unicode(2, 65)]


def test_unicode_text_surrogate_pair():
    # Astral chars travel as two UTF-16 code units, exactly like charCodeAt.
    frames = msc_unicode_text("𝄞")  # U+1D11E -> D834 DD1E
    assert frames == [
        msc_unicode(1, 0xD834), msc_unicode(2, 0xD834),
        msc_unicode(1, 0xDD1E), msc_unicode(2, 0xDD1E),
    ]


def test_mouse_buttons():
    assert msc_mouse_move(100, 200) == bytes(
        (0x00, 0x02, 0x00, 0x0A, 0x00, 0x00, 0x00, 0x64, 0x00, 0xC8))
    assert msc_mouse_down(100, 200) == bytes(
        (0x00, 0x02, 0x00, 0x0A, 0x00, 0x02, 0x00, 0x64, 0x00, 0xC8))
    assert msc_mouse_up(100, 200) == bytes(
        (0x00, 0x02, 0x00, 0x0A, 0x00, 0x04, 0x00, 0x64, 0x00, 0xC8))
    assert msc_click(100, 200) == [
        msc_mouse_move(100, 200), msc_mouse_down(100, 200), msc_mouse_up(100, 200),
    ]


def test_session_frames():
    assert msc_refresh() == bytes((0x00, 0x06, 0x00, 0x04))
    assert msc_unpause() == bytes((0x00, 0x08, 0x00, 0x05, 0x00))
    assert msc_compression() == bytes(
        (0x00, 0x05, 0x00, 0x0A, 0x01, 0x32, 0x04, 0x00, 0x00, 0x64))
    assert msc_input_lock_query() == bytes((0x00, 0x57, 0x00, 0x05, 0x02))
    ack = msc_screen_ack()
    assert ack.endswith(bytes((0x00, 0x0E, 0x00, 0x04)))
    assert ack.count(bytes((0x00, 0x01, 0x00, 0x06, 0x01))) == 6  # six key-ups
    assert msc_close() == '{"ctrlChannel":"102938","type":"close"}'
    assert msc_options() == '{"ctrlChannel":"102938","type":"options"}'
    assert msc_pong() == '{"ctrlChannel":"102938","type":"pong"}'


def test_frame_size_counts_header():
    assert msc_frame(6) == bytes((0, 6, 0, 4))
    frame = msc_frame(3, b"\x00\x00\x01\x02" + b"J" * 10)
    assert frame[:4] == bytes((0, 3, 0, 18))
    assert frame[4:8] == b"\x00\x00\x01\x02"


# ---- tile parsing ------------------------------------------------------

def _tile_packet(x: int, y: int, jpeg: bytes) -> bytes:
    return msc_frame(3, bytes(((x >> 8) & 0xFF, x & 0xFF, (y >> 8) & 0xFF, y & 0xFF)) + jpeg)


def test_parse_tile_packet():
    cmd, payload = parse_msc_packet(_tile_packet(16, 32, b"JPEGDATA"))
    assert cmd == 3
    tile = parse_tile(payload)
    assert tile is not None
    assert (tile.x, tile.y, tile.data) == (16, 32, b"JPEGDATA")


def test_parse_short_packet_returns_none():
    assert parse_msc_packet(b"\x00\x03\x00") is None


def test_parse_jumbo_packet_unwrap():
    inner = bytes((0, 3, 0, 12)) + bytes((0, 0, 0, 0)) + b"JPEG"
    assert len(inner) == 12
    jumbo = (
        bytes((0, 27, 0, 8)) + len(inner).to_bytes(4, "big") + bytes((0, 3))
        + inner[2:]
    )
    cmd, payload = parse_msc_packet(jumbo)
    assert cmd == 3
    tile = parse_tile(payload)
    assert tile is not None and tile.data == b"JPEG"


def test_accumulator_reassembles_splits():
    acc = MscAccumulator()
    packet = _tile_packet(0, 0, b"X" * 100)
    assert acc.feed(packet[:5]) == []
    done = acc.feed(packet[5:])
    assert len(done) == 1 and done[0][0] == 3
    assert parse_tile(done[0][1]).data == b"X" * 100


def test_accumulator_multiple_packets_one_feed():
    acc = MscAccumulator()
    out = acc.feed(_tile_packet(0, 0, b"A") + _tile_packet(8, 8, b"B"))
    assert [cmd for cmd, _ in out] == [3, 3]


def test_accumulator_jumbo_then_normal():
    inner = bytes((0, 3, 0, 12)) + bytes((1, 2, 3, 4)) + b"JPEG"
    jumbo = (
        bytes((0, 27, 0, 8)) + len(inner).to_bytes(4, "big") + bytes((0, 3))
        + inner[2:]
    )
    acc = MscAccumulator()
    out = acc.feed(jumbo + _tile_packet(8, 8, b"B"))
    assert [cmd for cmd, _ in out] == [3, 3]
    assert parse_tile(out[0][1]).data == b"JPEG"


# ---- websocket codec ---------------------------------------------------

def test_handshake_roundtrip():
    key = base64.b64encode(b"0123456789abcdef").decode("ascii")
    request = build_ws_handshake_request(
        "127.0.0.1:4443", "/meshrelay.ashx?p=2", key,
        {"x-meshauth": "dXNlcg==,cGFzcw=="},
    )
    text = request.decode("ascii")
    assert text.startswith("GET /meshrelay.ashx?p=2 HTTP/1.1\r\n")
    assert "Upgrade: websocket\r\n" in text
    assert "x-meshauth: dXNlcg==,cGFzcw==\r\n" in text
    digest = hashlib.sha1(
        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    accept = base64.b64encode(digest).decode("ascii")
    response = (
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept.encode("ascii") + b"\r\n\r\n"
    )
    assert check_ws_handshake_response(response, key) is True
    assert check_ws_handshake_response(response, "other-key") is False
    assert check_ws_handshake_response(b"HTTP/1.1 403 Forbidden\r\n\r\n", key) is False


def test_frame_masked_roundtrip():
    payload = b"\x00\x01\x00\x06\x00\x41" * 10
    wire = encode_ws_frame(0x2, payload, mask=True)
    assert wire[1] & 0x80  # client frames are masked
    buffer = bytearray(wire)
    assert decode_ws_frames(buffer) == [(0x2, payload)]
    assert bytes(buffer) == b""


def test_frame_fragmentation():
    part1 = encode_ws_frame(0x2, b"AB", mask=False)[:3]
    part2 = encode_ws_frame(0x2, b"AB", mask=False)[3:]
    buffer = bytearray(part1)
    assert decode_ws_frames(buffer) == []
    buffer += part2
    assert decode_ws_frames(buffer) == [(0x2, b"AB")]


def test_frame_16bit_length():
    payload = b"Z" * 1000
    wire = encode_ws_frame(0x2, payload, mask=False)
    assert wire[1] == 126
    assert decode_ws_frames(bytearray(wire)) == [(0x2, payload)]


def test_stdlib_socket_ping_pong_and_close():
    import time

    client, server = socket.socketpair()
    client.settimeout(5)
    server.settimeout(5)
    ws = StdlibWebSocket(client)
    # Deadlines are absolute monotonic timestamps, as the port uses them.
    deadline = time.monotonic() + 5
    # Server pings; the client answers with a pong and keeps going.
    server.sendall(encode_ws_frame(0x9, b"hi", mask=False))
    server.sendall(encode_ws_frame(0x1, b"c", mask=False))
    assert ws.recv(deadline) == (0x1, b"c")
    pong = decode_ws_frames(bytearray(server.recv(65536)))
    assert pong == [(0xA, b"hi")]
    server.sendall(encode_ws_frame(0x8, b"", mask=False))
    assert ws.recv(deadline) is None
    assert ws.closed is True
    server.close()


# ---- scripted relay sessions -------------------------------------------

class _FakeSocket:
    """A scripted websocket double: pops (opcode, payload), records sends."""

    def __init__(self, script: list):
        self._script = list(script)
        self.sent_text: list[str] = []
        self.sent_binary: list[bytes] = []
        self.closed = False

    def send_text(self, text: str) -> None:
        self.sent_text.append(text)

    def send_binary(self, data: bytes) -> None:
        self.sent_binary.append(bytes(data))

    def recv(self, deadline: float):
        if not self._script:
            return None
        return self._script.pop(0)

    def close(self) -> None:
        self.closed = True


def _screen_size_frame(width: int, height: int) -> bytes:
    return msc_frame(7, bytes((
        (width >> 8) & 0xFF, width & 0xFF, (height >> 8) & 0xFF, height & 0xFF)))


def _serverinfo_message(domain: str = "") -> bytes:
    return json.dumps(
        {"action": "serverinfo", "serverinfo": {"domain": domain}}).encode()


def _authcookie_script(domain: str = "") -> list:
    return [
        (0x1, _serverinfo_message(domain)),
        (0x1, json.dumps(
            {"action": "authcookie", "cookie": "C", "rcookie": "R"}).encode()),
    ]


def _make_port(script_control, script_relay, **kwargs):
    sockets = {"control": None, "relay": None}

    def factory(host, port, path, headers, timeout_seconds):
        assert headers["x-meshauth"].startswith(
            base64.b64encode(b"padiemadmin").decode("ascii") + ",")
        if path == "/control.ashx":
            sockets["control"] = _FakeSocket(script_control)
            return sockets["control"]
        assert path.startswith("/meshrelay.ashx?browser=1&p=2&nodeid=node%2F")
        sockets["relay"] = _FakeSocket(script_relay)
        return sockets["relay"]

    port = MeshCentralDesktopPort(
        login_user="padiemadmin",
        password_provider=lambda: "s3cret",
        url="wss://127.0.0.1:4443",
        websocket_factory=factory,
        **kwargs,
    )
    return port, sockets


def _stub_compose_png(width, height, tiles):
    return b"\xff\xd8\xffFAKEJPEG"


def _full_cover_tile_sizes(monkeypatch):
    monkeypatch.setattr(
        desktop_module, "_tile_size", lambda data: (800, 600))


def test_capture_full_session(monkeypatch):
    _full_cover_tile_sizes(monkeypatch)
    control_script = _authcookie_script()
    relay_script = [
        (0x1, b"c"),
        (0x2, _screen_size_frame(800, 600)),
        (0x2, _tile_packet(0, 0, b"TILE0")),
    ]
    port, sockets = _make_port(control_script, relay_script, compose=_stub_compose_png)
    outcome = port.run_desktop_op(
        node_ref="node//abc", op="capture", timeout_seconds=30)
    assert outcome.termination == "captured"
    assert outcome.width == 800 and outcome.height == 600
    assert outcome.image is not None and outcome.image.startswith(b"\xff\xd8\xff")
    assert "800x600" in outcome.note
    assert hashlib.sha256(outcome.image).hexdigest() in outcome.note
    # Handshake order: options, protocol selector, then MSC setup frames.
    relay = sockets["relay"]
    assert relay.sent_text[0] == msc_options()
    assert relay.sent_text[1] == "2"
    setup = b"".join(relay.sent_binary)
    assert msc_refresh() in setup
    assert msc_unpause() in setup
    assert msc_compression() in setup
    # One MSC packet per websocket message, as the browser sends them: the
    # agent answers one packet per write.
    for chunk in relay.sent_binary:
        assert len(chunk) >= 4
        assert (chunk[2] << 8) + chunk[3] == len(chunk)
    # Farewell close is always sent.
    assert relay.sent_text[-1] == msc_close()
    assert relay.closed is True
    assert sockets["control"].closed is True
    # The tunnel command went to the agent with the relay credential.
    tunnel = json.loads(sockets["control"].sent_text[1])
    assert tunnel["action"] == "msg" and tunnel["type"] == "tunnel"
    assert tunnel["nodeid"] == "node//abc" and tunnel["usage"] == 2
    assert "&rauth=R" in tunnel["value"]


def test_bare_node_id_completed_with_server_domain():
    # The deployment map pins the bare id; the server completes it with the
    # domain from its own greeting, and the tunnel names the completed id.
    control_script = _authcookie_script(domain="")
    relay_script = [(0x1, b"c"), (0x2, _screen_size_frame(800, 600))]
    port, sockets = _make_port(control_script, relay_script)
    outcome = port.run_desktop_op(node_ref="bareid123", op="keys", arg="enter",
                                  timeout_seconds=10)
    assert outcome.termination == "acted"
    tunnel = json.loads(sockets["control"].sent_text[1])
    assert tunnel["nodeid"] == "node//bareid123"
    assert "nodeid=node%2F%2Fbareid123" in tunnel["value"]


def test_screen_change_drops_stale_tiles(monkeypatch):
    # The agent switches displays mid-session: stale tiles must not
    # composite into the new frame.
    monkeypatch.setattr(desktop_module, "_tile_size", lambda data: (800, 600))
    control_script = _authcookie_script()
    relay_script = [
        (0x1, b"c"),
        (0x2, _screen_size_frame(800, 600)),
        (0x2, _tile_packet(0, 0, b"STALE")),
        (0x2, _screen_size_frame(1024, 768)),
        (0x2, _tile_packet(0, 0, b"NEW")),
    ]
    port, _ = _make_port(control_script, relay_script, compose=_stub_compose_png)
    outcome = port.run_desktop_op(node_ref="node//abc", op="capture", timeout_seconds=5)
    # Only the 1024x768 tile survives, covering 800x600 of 1024x768: partial.
    assert outcome.termination == "desktop_unavailable"
    assert "1024x768" in outcome.note


def test_capture_partial_coverage_is_not_captured(monkeypatch):
    monkeypatch.setattr(desktop_module, "_tile_size", lambda data: (100, 100))
    control_script = _authcookie_script()
    relay_script = [
        (0x1, b"c"),
        (0x2, _screen_size_frame(800, 600)),
        (0x2, _tile_packet(0, 0, b"TILE0")),
    ]
    port, sockets = _make_port(control_script, relay_script, compose=_stub_compose_png)
    outcome = port.run_desktop_op(node_ref="node//abc", op="capture", timeout_seconds=5)
    assert outcome.termination == "desktop_unavailable"
    assert outcome.image is None
    assert "%" in outcome.note


def test_unpaired_relay_is_unavailable():
    control_script = _authcookie_script()
    port, _ = _make_port(control_script, [])
    outcome = port.run_desktop_op(node_ref="node//abc", op="capture", timeout_seconds=5)
    assert outcome.termination == "desktop_unavailable"
    assert "did not join" in outcome.note


def test_no_screen_after_pair_is_unavailable():
    control_script = _authcookie_script()
    port, _ = _make_port(control_script, [(0x1, b"c")])
    outcome = port.run_desktop_op(node_ref="node//abc", op="type", arg="hi",
                                  timeout_seconds=5)
    assert outcome.termination == "desktop_unavailable"


def test_type_sends_unicode_frames():
    control_script = _authcookie_script()
    relay_script = [(0x1, b"c"), (0x2, _screen_size_frame(800, 600))]
    port, sockets = _make_port(control_script, relay_script)
    outcome = port.run_desktop_op(node_ref="node//abc", op="type", arg="Ab",
                                  timeout_seconds=10)
    assert outcome.termination == "acted"
    assert "sent 2 UTF-16 units" in outcome.note and "not verified" in outcome.note
    assert outcome.image is None
    assert b"".join(sockets["relay"].sent_binary).count(msc_refresh()) >= 0
    sent = b"".join(sockets["relay"].sent_binary)
    assert msc_unicode_text("Ab")[0] in sent
    assert msc_unicode_text("Ab")[-1] in sent


def test_keys_send_exact_sequence():
    control_script = _authcookie_script()
    relay_script = [(0x1, b"c"), (0x2, _screen_size_frame(800, 600))]
    port, sockets = _make_port(control_script, relay_script)
    outcome = port.run_desktop_op(node_ref="node//abc", op="keys", arg="ctrl+s",
                                  timeout_seconds=10)
    assert outcome.termination == "acted"
    sent = b"".join(sockets["relay"].sent_binary)
    for frame in (msc_key(1, 17), msc_key(1, 83), msc_key(2, 83), msc_key(2, 17)):
        assert frame in sent


def test_click_sends_move_press_release():
    control_script = _authcookie_script()
    relay_script = [(0x1, b"c"), (0x2, _screen_size_frame(800, 600))]
    port, sockets = _make_port(control_script, relay_script)
    outcome = port.run_desktop_op(node_ref="node//abc", op="click", arg="960,540",
                                  timeout_seconds=10)
    assert outcome.termination == "acted"
    sent = b"".join(sockets["relay"].sent_binary)
    for frame in msc_click(960, 540):
        assert frame in sent


def test_refused_op_never_touches_the_network():
    calls = []

    def factory(host, port, path, headers, timeout_seconds):
        calls.append(path)
        raise AssertionError("must not connect")

    port = MeshCentralDesktopPort(
        login_user="padiemadmin", password_provider=lambda: "s3cret",
        websocket_factory=factory,
    )
    with pytest.raises(MeshCentralDesktopRefused):
        port.run_desktop_op(node_ref="node//abc", op="explode", timeout_seconds=10)
    assert calls == []


def test_bad_credential_never_touches_the_network():
    calls = []

    def factory(host, port, path, headers, timeout_seconds):
        calls.append(path)
        raise AssertionError("must not connect")

    port = MeshCentralDesktopPort(
        login_user="padiemadmin", password_provider=lambda: "",
        websocket_factory=factory,
    )
    with pytest.raises(MeshCentralDesktopRefused):
        port.run_desktop_op(node_ref="node//abc", op="capture", timeout_seconds=10)
    assert calls == []


def test_constructor_bounds():
    with pytest.raises(Exception):
        MeshCentralDesktopPort(login_user="", password_provider=lambda: "x")
    with pytest.raises(Exception):
        MeshCentralDesktopPort(login_user="u", password_provider=lambda: "x",
                               url="https://127.0.0.1:4443")
    with pytest.raises(Exception):
        MeshCentralDesktopPort(login_user="u", password_provider=lambda: "x",
                               url="wss://example.com:4443")
    port = MeshCentralDesktopPort(login_user="u", password_provider=lambda: "x",
                                   websocket_factory=lambda *a: None)
    with pytest.raises(MeshCentralDesktopRefused):
        port.run_desktop_op(node_ref="", op="capture")
    with pytest.raises(MeshCentralDesktopRefused):
        port.run_desktop_op(node_ref="n", op="capture", timeout_seconds=0)
    with pytest.raises(MeshCentralDesktopRefused):
        port.run_desktop_op(node_ref="n", op="capture", timeout_seconds=301)


def test_real_pillow_compose_when_available():
    pil = pytest.importorskip("PIL.Image")
    tile_img = pil.new("RGB", (8, 6), (10, 20, 30))
    import io

    buf = io.BytesIO()
    tile_img.save(buf, format="JPEG")
    shot = compose_screenshot_jpeg(8, 6, [DesktopTile(x=0, y=0, data=buf.getvalue())])
    assert shot.startswith(b"\xff\xd8\xff")
    back = pil.open(io.BytesIO(shot))
    assert back.size == (8, 6)
    assert back.getpixel((0, 0)) is not None


def test_compose_without_codec_is_refused(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no PIL in this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(MeshCentralDesktopRefused):
        compose_screenshot_jpeg(8, 6, [DesktopTile(x=0, y=0, data=b"xx")])
    assert desktop_module._tile_size(b"xx") is None


def test_outcome_defaults():
    outcome = MeshCentralDesktopOutcome(termination="acted", note="keys enter")
    assert outcome.image is None and outcome.width is None


def test_coverage_uses_union_not_sum(monkeypatch):
    from kagent.local_agent_meshcentral_desktop_port import _DesktopSession
    monkeypatch.setattr(desktop_module, "_tile_size", lambda data: (5, 10))
    session = _DesktopSession(relay=None, compose=None, deadline=0)
    session._tiles = [DesktopTile(x=0, y=0, data=b"a"),
                      DesktopTile(x=0, y=0, data=b"b")]
    assert session._coverage(10, 10) == 50


@pytest.mark.parametrize("op,arg", [("type", "Ab"), ("keys", "enter"), ("click", "1,2")])
def test_partial_send_is_not_success(monkeypatch, op, arg):
    control = _authcookie_script()
    relay = [(0x1, b"c"), (0x2, _screen_size_frame(800, 600))]
    port, sockets = _make_port(control, relay)
    from kagent.local_agent_meshcentral_desktop_port import _DesktopSession
    original = _DesktopSession.handshake
    def fail_after_handshake(self):
        size = original(self)
        def refused(frame):
            raise OSError("broken relay")
        self._relay.send_binary = refused
        return size
    monkeypatch.setattr(_DesktopSession, "handshake", fail_after_handshake)
    result = port.run_desktop_op(node_ref="node//abc", op=op, arg=arg, timeout_seconds=10)
    assert result.termination != "acted"
    assert "uncertain" in result.note
