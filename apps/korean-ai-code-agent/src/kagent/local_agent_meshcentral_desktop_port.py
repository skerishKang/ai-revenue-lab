"""#4139 desktop lane — MeshCentral remote-desktop port for the Oracle executor.

One desktop observation or input runs through the OFFICIAL MeshCentral relay
(``meshrelay.ashx``, protocol ``p=2``) over the same private path the TXT read
and the terminal command already use: Claw Worker -> Workers VPC Service ->
COM1 QUIC tunnel -> local ssh -L -> the Oracle MeshCentral on 127.0.0.1:4443.

There is no ``capture`` or ``relay`` command in the official ``meshctrl.js``
client (verified against the deployed MeshCentral 1.2.5), so this module
speaks the same two websockets the official browser client speaks, in the
same order, with the same bytes:

* ``control.ashx`` with the ``x-meshauth`` header (exactly how
  ``meshctrl.js`` authenticates) to fetch ``{action:'authcookie'}`` ->
  ``{action:'authcookie', cookie, rcookie}``.
* ``meshrelay.ashx?browser=1&p=2&nodeid=<node>&id=<tunnelid>`` with the same
  header, then ``{action:'msg', type:'tunnel', nodeid, value:'*...&id=
  <tunnelid>&rauth=<rcookie>', usage:2}`` on the control socket so the agent
  connects back. On the ``'c'`` pair signal this side sends
  ``{"type":"options"}`` and the ``"2"`` protocol selector, exactly like
  ``public/scripts/agent-redir-ws-0.0.1.js``.
* The MSC frames that follow are the ones
  ``public/scripts/agent-desktop-0.0.2.js`` sends and parses: screen size
  (cmd 7), tiles (cmd 3, normal and jumbo-27 wrapped), compression (cmd 5),
  refresh (cmd 6), pause/unpause (cmd 8), key input (cmd 1), unicode input
  (cmd 85), mouse input (cmd 2), input-lock query (cmd 87) and the
  ``{"ctrlChannel":"102938","type":"close"}`` farewell.

Two facts drive this module:

* A screenshot is only ``captured`` when decoded tiles cover the whole
  reported screen. A partial redraw at the deadline is ``desktop_unavailable``
  with the measured coverage, never a cropped image presented as the screen.
* An input op (type/keys/click) is only ``acted`` when the relay paired
  (``'c'`` seen) and the agent reported its screen. Bytes that never reached
  a paired session are ``desktop_unavailable``; anything refused before the
  agent was asked raises ``MeshCentralDesktopRefused`` and the executor
  reports ``not_executed`` — the PC is never blamed for a call it never got.

The bytes returned here are the agent's own: JPEG tiles are composited
verbatim into one JPEG. Tile decoding needs an image codec (Pillow on the
Oracle host); the compositor is injected so unit tests never need one.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

from .contracts import ContractError

#: Dispatch grammar carried in ``command_text``: ``desktop:<op>`` plus an
#: optional second line for the op argument. The op set is closed: anything
#: else is refused before the PC is asked.
DESKTOP_COMMAND_PREFIX = "desktop:"
_OP_CAPTURE = "capture"
_OP_TYPE = "type"
_OP_KEYS = "keys"
_OP_CLICK = "click"
_DESKTOP_OPS = (_OP_CAPTURE, _OP_TYPE, _OP_KEYS, _OP_CLICK)
#: Key combos with a fixed, reviewed meaning. Anything else is refused rather
#: than guessed at: a wrong guess would press keys the owner never ordered.
_KEY_SEQUENCES: dict[str, tuple[tuple[int, int, bool], ...]] = {
    # (action, keycode, extended) with action 1=DOWN 2=UP, extended as the
    # browser's SendKeyMsgKC extendedKey flag.
    "enter": ((1, 13, False), (2, 13, False)),
    "esc": ((1, 27, False), (2, 27, False)),
    "tab": ((1, 9, False), (2, 9, False)),
    "backspace": ((1, 8, False), (2, 8, False)),
    "delete": ((1, 46, False), (2, 46, False)),
    "ctrl+s": ((1, 17, False), (1, 83, False), (2, 83, False), (2, 17, False)),
    "ctrl+c": ((1, 17, False), (1, 67, False), (2, 67, False), (2, 17, False)),
    "ctrl+v": ((1, 17, False), (1, 86, False), (2, 86, False), (2, 17, False)),
    "ctrl+a": ((1, 17, False), (1, 65, False), (2, 65, False), (2, 17, False)),
    "alt+f4": ((1, 18, False), (1, 115, False), (2, 115, False), (2, 18, False)),
    "win+r": ((5, 91, False), (1, 82, False), (2, 82, False), (4, 91, False)),
    "win": ((5, 91, False), (4, 91, False)),
}
#: The wire mouse field is two bytes: the format's own range, not a product
#: rule. Negative or wider coordinates are refused, never wrapped.
_MAX_WIRE_COORD = 65535
#: MSC input types, key actions and mouse buttons from agent-desktop-0.0.2.js.
_INPUT_KEY = 1
_INPUT_MOUSE = 2
_INPUT_CTRLALTDEL = 10
_INPUT_KEYUNICODE = 85
_KEY_DOWN = 1
_KEY_UP = 2
_KEY_EXDOWN = 5
_KEY_EXUP = 4
_MOUSE_LEFT = 0x02
#: JPEG tiles, the browser default image type (1 = JPEG).
_IMAGE_TYPE_JPEG = 1
_IMAGE_QUALITY = 50
_IMAGE_SCALING = 1024
_IMAGE_FRAMETIMER = 100
#: JPEG magic, checked on every composited screenshot before it may travel.
_JPEG_MAGIC = b"\xff\xd8\xff"
#: The composited screenshot is re-encoded as JPEG: the agent's tiles are
#: already JPEG, and a photo-grade PNG of a multi-monitor desktop does not
#: fit the existing 6 MB wire envelope the submit leg is held to. Quality 85
#: keeps every visible tile detail; the digest pins exactly these bytes.
_COMPOSE_JPEG_QUALITY = 85
#: The relay server drops an unpaired waiter after 15 seconds, so pairing is
#: awaited well inside that bound; the agent still needs seconds to answer.
_PAIR_TIMEOUT_SECONDS = 12.0
#: Overall op wait bound shape, mirroring the command port (1..300 seconds).
_MIN_TIMEOUT_SECONDS = 1
_MAX_TIMEOUT_SECONDS = 300


class MeshCentralDesktopRefused(ValueError):
    """Bounded refusal of one desktop op. Never carries output or secrets."""


@dataclass(frozen=True, slots=True)
class MeshCentralDesktopOutcome:
    """What one real desktop session produced, exactly as observed."""

    #: "captured" | "acted" | "desktop_unavailable" | "timed_out"
    termination: str
    #: Short human-readable observation (resolution, coverage, keys sent).
    #: Text only: no C0 controls except tab/LF, so it can travel the UTF-8 wire.
    note: str
    #: The composited JPEG for a capture, else None.
    image: bytes | None = None
    width: int | None = None
    height: int | None = None


# ---- op grammar ------------------------------------------------------

def parse_desktop_op(command_text: Any) -> tuple[str, str | None]:
    """Split one ``desktop:`` dispatch body into (op, arg).

    Raises :class:`MeshCentralDesktopRefused` for anything outside the
    grammar. The PC is never contacted for a refused op.
    """
    if not isinstance(command_text, str):
        raise MeshCentralDesktopRefused("desktop op must be text")
    if not command_text.startswith(DESKTOP_COMMAND_PREFIX):
        raise MeshCentralDesktopRefused("desktop op must start with 'desktop:'")
    rest = command_text[len(DESKTOP_COMMAND_PREFIX):]
    if "\x00" in rest or "\r" in rest:
        raise MeshCentralDesktopRefused("desktop op must not contain NUL or CR")
    head, _, tail = rest.partition("\n")
    op = head.strip().lower()
    if op not in _DESKTOP_OPS:
        raise MeshCentralDesktopRefused("unknown desktop op")
    if op == _OP_CAPTURE:
        if tail.strip():
            raise MeshCentralDesktopRefused("capture takes no argument")
        return op, None
    arg = tail.strip(" \t\n")
    if not arg:
        raise MeshCentralDesktopRefused("desktop op argument is required")
    if op == _OP_TYPE:
        if any(ord(ch) < 32 and ch not in "\t\n" for ch in arg) or "\x7f" in arg:
            raise MeshCentralDesktopRefused("typed text carries a control character")
        return op, arg
    if op == _OP_KEYS:
        spec = arg.strip().lower()
        if spec not in _KEY_SEQUENCES:
            raise MeshCentralDesktopRefused("unknown key combo")
        return op, spec
    # click: two unsigned wire-range integers, nothing else.
    match = re.fullmatch(r"(\d{1,5}),(\d{1,5})", arg)
    if match is None:
        raise MeshCentralDesktopRefused("click needs 'x,y' coordinates")
    x, y = int(match.group(1)), int(match.group(2))
    if x > _MAX_WIRE_COORD or y > _MAX_WIRE_COORD:
        raise MeshCentralDesktopRefused("click coordinates exceed the wire field")
    return op, f"{x},{y}"


# ---- MSC frames ------------------------------------------------------

def _u16(value: int) -> bytes:
    return bytes(((value >> 8) & 0xFF, value & 0xFF))


def msc_frame(cmd: int, payload: bytes = b"") -> bytes:
    """One MSC frame: [cmd_hi, cmd_lo, size_hi, size_lo, payload...].

    The size counts the whole frame including this 4-byte header, as the
    browser's SendRefresh (``00 06 00 04``) shows.
    """
    if not 0 <= cmd <= 0xFFFF:
        raise MeshCentralDesktopRefused("MSC command out of range")
    if len(payload) > 0xFFFF - 4:
        raise MeshCentralDesktopRefused("MSC payload exceeds the frame")
    return bytes((cmd >> 8, cmd & 0xFF, 0, 4 + len(payload))) + bytes(payload)


def msc_key(action: int, keycode: int, extended: bool = False) -> bytes:
    """One key frame, byte-identical to the browser's SendKeyMsgKC."""
    if action == _KEY_DOWN:
        up = 0
    elif action == _KEY_UP:
        up = 1
    elif action == _KEY_EXDOWN:
        up = 4
    elif action == _KEY_EXUP:
        up = 3
    else:
        raise MeshCentralDesktopRefused("unknown key action")
    if extended:
        up = 3 if up == 1 else 4
    if not 0 <= keycode <= 0xFF:
        raise MeshCentralDesktopRefused("keycode out of range")
    return msc_frame(_INPUT_KEY, bytes((up, keycode)))


def msc_unicode(action: int, code_unit: int) -> bytes:
    """One unicode key frame, as the browser's SendKeyUnicode."""
    if action not in (_KEY_DOWN, _KEY_UP):
        raise MeshCentralDesktopRefused("unknown key action")
    if not 0 <= code_unit <= 0xFFFF:
        raise MeshCentralDesktopRefused("code unit out of range")
    return msc_frame(_INPUT_KEYUNICODE, bytes((action - 1,)) + _u16(code_unit))


def msc_unicode_text(text: str) -> list[bytes]:
    """Down+up unicode frames per UTF-16 code unit, as SendStringUnicode."""
    frames: list[bytes] = []
    for char in text:
        encoded = char.encode("utf-16-be")
        for i in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[i:i + 2], "big")
            frames.append(msc_unicode(_KEY_DOWN, unit))
            frames.append(msc_unicode(_KEY_UP, unit))
    return frames


def msc_mouse_move(x: int, y: int) -> bytes:
    return msc_frame(_INPUT_MOUSE, bytes((0, 0)) + _u16(x) + _u16(y))


def msc_mouse_down(x: int, y: int, button: int = _MOUSE_LEFT) -> bytes:
    return msc_frame(_INPUT_MOUSE, bytes((0, button & 0xFF)) + _u16(x) + _u16(y))


def msc_mouse_up(x: int, y: int, button: int = _MOUSE_LEFT) -> bytes:
    return msc_frame(_INPUT_MOUSE, bytes((0, (button * 2) & 0xFF)) + _u16(x) + _u16(y))


def msc_click(x: int, y: int) -> list[bytes]:
    """Move, press, release — one left click at absolute desktop pixels."""
    return [msc_mouse_move(x, y), msc_mouse_down(x, y), msc_mouse_up(x, y)]


def msc_refresh() -> bytes:
    return msc_frame(6)


def msc_unpause() -> bytes:
    return msc_frame(8, b"\x00")


def msc_compression(
    image_type: int = _IMAGE_TYPE_JPEG,
    level: int = _IMAGE_QUALITY,
    scaling: int = _IMAGE_SCALING,
    frametimer: int = _IMAGE_FRAMETIMER,
) -> bytes:
    return msc_frame(5, bytes((image_type, level)) + _u16(scaling) + _u16(frametimer))


def msc_input_lock_query() -> bytes:
    return msc_frame(87, b"\x02")


def msc_screen_ack() -> bytes:
    """The key-release burst plus cmd 14 the browser sends on screen size."""
    out = b"".join(
        msc_key(_KEY_UP, kc) for kc in (16, 17, 18, 91, 92, 16)
    )
    return out + msc_frame(14)


def msc_close() -> str:
    return '{"ctrlChannel":"102938","type":"close"}'


def msc_options() -> str:
    return '{"ctrlChannel":"102938","type":"options"}'


def msc_pong() -> str:
    return '{"ctrlChannel":"102938","type":"pong"}'


# ---- tile parsing ----------------------------------------------------

@dataclass
class DesktopTile:
    x: int
    y: int
    data: bytes


def parse_msc_packet(packet: bytes) -> tuple[int, bytes] | None:
    """Split one complete MSC packet into (cmd, payload).

    Returns None for a short or jumbo-wrapped header the caller must feed
    through the accumulator first. Jumbo (cmd 27) unwrap follows
    agent-redir-ws-0.1.1.js: [27][8][realsize:4][cmd:2][len:2][payload].
    """
    if len(packet) < 4:
        return None
    cmd = (packet[0] << 8) + packet[1]
    size = (packet[2] << 8) + packet[3]
    if cmd == 27 and size == 8:
        if len(packet) < 12:
            return None
        size = int.from_bytes(packet[4:8], "big")
        cmd = (packet[8] << 8) + packet[9]
        if len(packet) < 8 + size:
            return None
        # The real packet starts at offset 8: [cmd:2][len:2][payload].
        return cmd, bytes(packet[12:8 + size])
    if len(packet) < size:
        return None
    return cmd, bytes(packet[4:size])


def parse_tile(payload: bytes) -> DesktopTile | None:
    """One cmd-3 payload into (x, y, jpeg bytes)."""
    if len(payload) < 4:
        return None
    return DesktopTile(
        x=(payload[0] << 8) + payload[1],
        y=(payload[2] << 8) + payload[3],
        data=bytes(payload[4:]),
    )


def _split_frames(blob: bytes) -> list[bytes]:
    """Split concatenated MSC packets into individual frames."""
    out: list[bytes] = []
    view = bytes(blob)
    while len(view) >= 4:
        size = (view[2] << 8) + view[3]
        if size < 4 or len(view) < size:
            break
        out.append(view[:size])
        view = view[size:]
    return out


class MscAccumulator:
    """Reassemble MSC packets split across websocket frames.

    Mirrors the browser's cmdAcc/cmdAccCmd/cmdAccCmdSize logic: packets
    arrive whole most of the time; a split one is buffered until its
    declared size is reached.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        """Feed raw bytes; return each complete (cmd, payload) in order."""
        out: list[tuple[int, bytes]] = []
        self._buffer += chunk
        while True:
            parsed = parse_msc_packet(bytes(self._buffer))
            if parsed is None:
                break
            cmd, payload = parsed
            if cmd == 27:
                # Should not happen: parse unwraps jumbo already.
                break
            size = _packet_size(bytes(self._buffer))
            del self._buffer[:size]
            out.append((cmd, payload))
        return out


def _packet_size(packet: bytes) -> int:
    """Bytes the buffer must hold (and then drop) for one packet."""
    cmd = (packet[0] << 8) + packet[1]
    size = (packet[2] << 8) + packet[3]
    if cmd == 27 and size == 8 and len(packet) >= 8:
        # Jumbo wrap: 8 header bytes plus the real packet they describe.
        return 8 + int.from_bytes(packet[4:8], "big")
    return size


# ---- websocket transport (stdlib only) ----------------------------------

def build_ws_handshake_request(host: str, path: str, key: str, headers: dict[str, str]) -> bytes:
    """One HTTP/1.1 upgrade request for a websocket client handshake."""
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
    ]
    for name, value in headers.items():
        lines.append(f"{name}: {value}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


def check_ws_handshake_response(raw: bytes, key: str) -> bool:
    """True when the response is a 101 accepting our key (RFC 6455)."""
    try:
        text = raw.decode("latin-1")
    except UnicodeDecodeError:
        return False
    if " 101 " not in text.split("\r\n", 1)[0]:
        return False
    accept = None
    for line in text.split("\r\n"):
        if line.lower().startswith("sec-websocket-accept:"):
            accept = line.split(":", 1)[1].strip()
    if accept is None:
        return False
    digest = hashlib.sha1(
        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
    ).digest()
    return secrets.compare_digest(accept, base64.b64encode(digest).decode("ascii"))


def encode_ws_frame(opcode: int, payload: bytes, *, mask: bool = True) -> bytes:
    """One client websocket frame (masked, as the spec requires of clients)."""
    header = bytes((0x80 | (opcode & 0x0F),))
    length = len(payload)
    if length < 126:
        header += bytes((0x80 | length,) if mask else (length,))
    elif length < 65536:
        header += (bytes((0x80 | 126,) if mask else (126,)) + length.to_bytes(2, "big"))
    else:
        header += (bytes((0x80 | 127,) if mask else (127,)) + length.to_bytes(8, "big"))
    if not mask:
        return header + payload
    mask_key = secrets.token_bytes(4)
    return header + mask_key + bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))


def decode_ws_frames(buffer: bytearray) -> list[tuple[int, bytes]]:
    """Pull complete frames from a buffer; leaves a partial tail in place.

    Returns (opcode, payload) with control frames included; callers answer
    pings and stop at close. Fragmented messages are reassembled.
    """
    out: list[tuple[int, bytes]] = []
    fragments: list[bytes] = []
    frag_opcode = 0
    while True:
        if len(buffer) < 2:
            break
        first, second = buffer[0], buffer[1]
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        index = 2
        if length == 126:
            if len(buffer) < 4:
                break
            length = int.from_bytes(bytes(buffer[2:4]), "big")
            index = 4
        elif length == 127:
            if len(buffer) < 10:
                break
            length = int.from_bytes(bytes(buffer[2:10]), "big")
            index = 10
        if masked:
            if len(buffer) < index + 4:
                break
            mask_key = bytes(buffer[index:index + 4])
            index += 4
        if len(buffer) < index + length:
            break
        payload = bytes(buffer[index:index + length])
        del buffer[:index + length]
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        if opcode == 0x0:  # continuation
            fragments.append(payload)
            if fin:
                out.append((frag_opcode, b"".join(fragments)))
                fragments, frag_opcode = [], 0
        elif opcode in (0x1, 0x2):
            if fin:
                out.append((opcode, payload))
            else:
                fragments, frag_opcode = [payload], opcode
        elif opcode == 0x8:  # close
            out.append((opcode, payload))
            break
        elif opcode == 0x9:  # ping
            out.append((opcode, payload))
        elif opcode == 0xA:  # pong
            out.append((opcode, payload))
        else:
            raise MeshCentralDesktopRefused("unknown websocket opcode")
    return out


class StdlibWebSocket:
    """A minimal RFC 6455 client over an injected connected socket.

    Only what the relay needs: text, binary, ping/pong, close. The socket
    carries its own timeout; ``recv`` pumps until the deadline.
    """

    def __init__(self, sock: Any) -> None:
        self._sock = sock
        self._buffer = bytearray()
        self.closed = False

    def send_text(self, text: str) -> None:
        self._sock.sendall(encode_ws_frame(0x1, text.encode("utf-8")))

    def send_binary(self, data: bytes) -> None:
        self._sock.sendall(encode_ws_frame(0x2, bytes(data)))

    def _fill(self) -> bool:
        try:
            chunk = self._sock.recv(65536)
        except Exception:
            return False
        if not chunk:
            return False
        self._buffer += chunk
        return True

    def recv(self, deadline: float) -> tuple[int, bytes] | None:
        """Next message frame, answering pings on the way. None at deadline."""
        import time

        pending: list[tuple[int, bytes]] = []
        while time.monotonic() < deadline:
            for opcode, payload in decode_ws_frames(self._buffer):
                if opcode == 0x9:
                    try:
                        self._sock.sendall(encode_ws_frame(0xA, payload))
                    except Exception:
                        return None
                    continue
                if opcode == 0xA:
                    continue
                if opcode == 0x8:
                    self.closed = True
                    return None
                pending.append((opcode, payload))
            if pending:
                return pending.pop(0)
            if not self._fill():
                return None
        return None

    def close(self) -> None:
        try:
            self._sock.sendall(encode_ws_frame(0x8, b""))
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass
        self.closed = True


def open_websocket(
    host: str,
    port: int,
    path: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> StdlibWebSocket:
    """Open one wss websocket to the private MeshCentral tunnel endpoint.

    TLS verification is off for this exact loopback tunnel only — the same
    trust basis as the existing ssh -L hop and meshctrl's
    ``rejectUnauthorized: false``. Nothing here ever dials another host.
    """
    import socket
    import ssl

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise MeshCentralDesktopRefused("the desktop relay dials the private tunnel only")
    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    request = build_ws_handshake_request(f"{host}:{port}", path, key, headers)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((host, port), timeout=timeout_seconds)
    try:
        sock = context.wrap_socket(raw, server_hostname=host)
    except Exception:
        raw.close()
        raise MeshCentralDesktopRefused("the private tunnel TLS handshake failed") from None
    sock.settimeout(max(0.5, min(5.0, timeout_seconds)))
    try:
        sock.sendall(request)
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if len(response) > 65536:
                break
    except Exception:
        sock.close()
        raise MeshCentralDesktopRefused("the private tunnel handshake failed") from None
    if b"\r\n\r\n" not in response or not check_ws_handshake_response(
        response.split(b"\r\n\r\n", 1)[0] + b"\r\n", key
    ):
        sock.close()
        raise MeshCentralDesktopRefused("the relay refused the websocket upgrade")
    return StdlibWebSocket(sock)


# ---- image composition -------------------------------------------------

def _tile_size(data: bytes) -> tuple[int, int] | None:
    """Pixel size of one tile image, or None when it does not decode.

    Separated so the coverage check and the compositor share one decoding
    truth, and so tests can stub it without an image codec.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    import io

    try:
        with Image.open(io.BytesIO(data)) as shot:
            shot.load()
            return shot.size
    except Exception:
        return None


def compose_screenshot_jpeg(width: int, height: int, tiles: list[DesktopTile]) -> bytes:
    """Composite JPEG tiles onto a canvas and encode one JPEG (needs Pillow)."""
    try:
        from PIL import Image
    except ImportError:
        raise MeshCentralDesktopRefused(
            "the image codec is unavailable on this host"
        ) from None
    import io

    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    for tile in tiles:
        try:
            with Image.open(io.BytesIO(tile.data)) as shot:
                shot.load()
                canvas.paste(shot.convert("RGB"), (tile.x, tile.y))
        except Exception as exc:
            raise MeshCentralDesktopRefused("a screen tile did not decode") from exc
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=_COMPOSE_JPEG_QUALITY)
    jpeg = out.getvalue()
    if not jpeg.startswith(_JPEG_MAGIC):
        raise MeshCentralDesktopRefused("the composited screenshot is not a JPEG")
    return jpeg


# ---- the port ----------------------------------------------------------

class MeshCentralDesktopPort:
    """One desktop observation or input over the official relay.

    ``websocket_factory`` is injected so the wire is explicit and testable:
    it receives (host, port, path, headers, timeout_seconds) and must return
    an object with ``send_text``/``send_binary``/``recv``/``close`` like
    :class:`StdlibWebSocket`. The operator password travels in the
    ``x-meshauth`` header exactly like the official client — never on argv.
    """

    def __init__(
        self,
        *,
        login_user: str,
        password_provider: Callable[[], str],
        url: str = "wss://127.0.0.1:4443",
        websocket_factory: Callable[..., Any] | None = None,
        compose: Callable[[int, int, list[DesktopTile]], bytes] | None = None,
    ) -> None:
        if not isinstance(login_user, str) or not login_user.strip():
            raise ContractError("the meshcentral login user is required")
        if not callable(password_provider):
            raise ContractError("the login password must be provided at call time")
        if not isinstance(url, str) or not url.startswith("wss://") or "@" in url:
            raise ContractError("the private tunnel URL must be a wss:// endpoint")
        host_port = url[len("wss://"):].split("/", 1)[0]
        if ":" in host_port:
            host, _, port_text = host_port.partition(":")
        else:
            host, port_text = host_port, "443"
        try:
            port = int(port_text)
        except ValueError:
            raise ContractError("the private tunnel URL must carry a numeric port") from None
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ContractError("the desktop relay dials the private tunnel only")
        self._host = host
        self._port = port
        self._login_user = login_user
        self._password_provider = password_provider
        self._connect = websocket_factory or open_websocket
        self._compose = compose or compose_screenshot_jpeg

    def _auth_headers(self) -> dict[str, str]:
        password = self._password_provider()
        if (
            not isinstance(password, str) or not password
            or "\n" in password or "\r" in password
        ):
            raise MeshCentralDesktopRefused(
                "the protected MeshCentral operator credential is invalid"
            )
        token = base64.b64encode(self._login_user.encode("utf-8")).decode("ascii")
        secret = base64.b64encode(password.encode("utf-8")).decode("ascii")
        return {
            "x-meshauth": token + "," + secret,
            "User-Agent": "padiem-oracle-mesh-desktop/1",
        }

    def run_desktop_op(
        self, *, node_ref: str, op: str, arg: str | None = None,
        timeout_seconds: int = 60,
    ) -> MeshCentralDesktopOutcome:
        """Open one relay session, run one op, close it."""
        import time

        if not isinstance(node_ref, str) or not node_ref.strip():
            raise MeshCentralDesktopRefused("node_ref is required")
        if op not in _DESKTOP_OPS:
            raise MeshCentralDesktopRefused("unknown desktop op")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise MeshCentralDesktopRefused("timeout_seconds must be an integer")
        if timeout_seconds < _MIN_TIMEOUT_SECONDS or timeout_seconds > _MAX_TIMEOUT_SECONDS:
            raise MeshCentralDesktopRefused("timeout_seconds is out of range")
        deadline = time.monotonic() + timeout_seconds
        headers = self._auth_headers()
        control = self._connect(
            self._host, self._port, "/control.ashx", headers, timeout_seconds,
        )
        try:
            domain = self._read_server_domain(control, deadline)
            if "/" in node_ref.strip():
                full_node = node_ref.strip()
            else:
                # The deployment map pins the bare node id; the server
                # completes a bare id with its own domain, and the tunnel
                # URL must name the completed id or the command is dropped.
                # The domain is read from the server's own greeting, never
                # assumed.
                full_node = "node/" + domain + "/" + node_ref.strip()
            rcookie = self._fetch_rcookie(control, deadline)
            tunnelid = secrets.token_hex(9)
            relay_path = (
                "/meshrelay.ashx?browser=1&p=2&nodeid=" + quote(full_node, safe="")
                + "&id=" + tunnelid
            )
            relay = self._connect(
                self._host, self._port, relay_path, headers, timeout_seconds,
            )
            try:
                return self._run_session(
                    control, relay, node_ref=full_node, tunnelid=tunnelid,
                    rcookie=rcookie, op=op, arg=arg, deadline=deadline,
                )
            finally:
                try:
                    relay.send_text(msc_close())
                except Exception:
                    pass
                relay.close()
        finally:
            control.close()

    def _read_server_domain(self, control: Any, deadline: float) -> str:
        """The domain id from the server's greeting (default domain is '')."""
        import time

        stop = min(deadline, time.monotonic() + 10.0)
        while time.monotonic() < stop:
            message = control.recv(stop)
            if message is None:
                break
            opcode, payload = message
            if opcode != 0x1:
                continue
            data = self._parse_json(payload)
            if isinstance(data, dict) and data.get("action") == "serverinfo":
                info = data.get("serverinfo")
                if isinstance(info, dict) and isinstance(info.get("domain"), str):
                    return info["domain"]
                return ""
        return ""

    def _recv_json_action(
        self, sock: Any, deadline: float, action: str,
    ) -> dict[str, Any] | None:
        import time

        while time.monotonic() < deadline:
            message = sock.recv(deadline)
            if message is None:
                return None
            opcode, payload = message
            if opcode != 0x1:
                continue
            data = self._parse_json(payload)
            if isinstance(data, dict) and data.get("action") == action:
                return data
        return None

    @staticmethod
    def _parse_json(payload: bytes) -> Any:
        import json

        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    def _fetch_rcookie(self, control: Any, deadline: float) -> str:
        control.send_text('{"action":"authcookie"}')
        data = self._recv_json_action(control, deadline, "authcookie")
        if data is None:
            raise MeshCentralDesktopRefused("the relay credential was not issued")
        rcookie = data.get("rcookie")
        if not isinstance(rcookie, str) or not rcookie:
            raise MeshCentralDesktopRefused("the relay credential was not issued")
        return rcookie

    def _run_session(
        self, control: Any, relay: Any, *, node_ref: str, tunnelid: str,
        rcookie: str, op: str, arg: str | None, deadline: float,
    ) -> MeshCentralDesktopOutcome:
        import json
        import time

        control.send_text(json.dumps({
            "action": "msg",
            "type": "tunnel",
            "nodeid": node_ref,
            "value": (
                "*/meshrelay.ashx?p=2&nodeid=" + quote(node_ref, safe="")
                + "&id=" + tunnelid + "&rauth=" + quote(rcookie, safe="")
            ),
            "usage": 2,
        }))
        # The agent must join within the server's 15-second unpaired window.
        paired = False
        while time.monotonic() < min(deadline, time.monotonic() + _PAIR_TIMEOUT_SECONDS):
            message = relay.recv(deadline)
            if message is None:
                break
            opcode, payload = message
            if opcode == 0x1 and payload == b"c":
                paired = True
                break
        if not paired:
            return MeshCentralDesktopOutcome(
                termination="desktop_unavailable",
                note="the PC desktop did not join the relay session",
            )
        relay.send_text(msc_options())
        relay.send_text("2")
        session = _DesktopSession(
            relay=relay, compose=self._compose, deadline=deadline,
        )
        observed = session.handshake()
        if observed is None:
            return MeshCentralDesktopOutcome(
                termination="desktop_unavailable",
                note="the paired desktop reported no screen",
            )
        width, height = observed
        if op == _OP_CAPTURE:
            return session.capture()
        try:
            if op == _OP_TYPE:
                count = session.type_text(arg or "")
                note = f"sent {count} UTF-16 units on {width}x{height}; screen effect not verified"
            elif op == _OP_KEYS:
                session.press_keys(arg or "")
                note = f"sent keys {arg} on {width}x{height}; screen effect not verified"
            else:
                coords = (arg or "").split(",")
                session.click(int(coords[0]), int(coords[1]))
                note = f"sent click {arg} on {width}x{height}; screen effect not verified"
        except MeshCentralDesktopRefused as exc:
            return MeshCentralDesktopOutcome(
                termination="not_executed",
                note=str(exc), width=width, height=height,
            )
        return MeshCentralDesktopOutcome(
            termination="acted", note=note, width=width, height=height,
        )


class _DesktopSession:
    """MSC exchange inside one paired relay session."""

    def __init__(self, *, relay: Any, compose: Callable, deadline: float) -> None:
        self._relay = relay
        self._compose = compose
        self._deadline = deadline
        self._accumulator = MscAccumulator()
        self._width: int | None = None
        self._height: int | None = None
        self._tiles: list[DesktopTile] = []
        self._alerts: list[str] = []
        self._lock: bool | None = None

    def _drain(self) -> list[tuple[int, bytes]] | None:
        """Pump one websocket message into MSC packets. None at deadline."""
        import time

        message = self._relay.recv(self._deadline)
        if message is None:
            return None
        opcode, payload = message
        if opcode == 0x1:
            self._handle_control_text(payload)
            return []
        if opcode != 0x2:
            return []
        return self._accumulator.feed(bytes(payload))

    def _handle_control_text(self, payload: bytes) -> None:
        import json

        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        if data.get("ctrlChannel") == "102938" and data.get("type") == "ping":
            try:
                self._relay.send_text(msc_pong())
            except Exception:
                pass

    def handshake(self) -> tuple[int, int] | None:
        """Wait for the screen size; answer like the browser. None on silence."""
        import time

        while time.monotonic() < self._deadline:
            packets = self._drain()
            if packets is None:
                return None
            for cmd, payload in packets:
                if cmd == 7 and len(payload) >= 4:
                    width = (payload[0] << 8) + payload[1]
                    height = (payload[2] << 8) + payload[3]
                    if width <= 0 or height <= 0 or width > 16384 or height > 16384:
                        continue
                    self._width, self._height = width, height
                    try:
                        # One MSC packet per websocket message, exactly like
                        # the browser: the agent answers one packet per write.
                        for frame in (
                            msc_compression(), msc_unpause(),
                            msc_input_lock_query(),
                        ):
                            self._relay.send_binary(frame)
                        for chunk in _split_frames(msc_screen_ack()):
                            self._relay.send_binary(chunk)
                        self._relay.send_binary(msc_refresh())
                    except Exception:
                        return None
                    return width, height
                if cmd == 65:
                    self._note_alert(payload)
        return None

    def _note_alert(self, payload: bytes) -> None:
        try:
            text = payload.decode("utf-8", errors="replace")
        except Exception:
            return
        if len(text) > 200:
            text = text[:200]
        if text not in self._alerts and len(self._alerts) < 5:
            self._alerts.append(text)

    def _pump_tiles(self, seconds: float) -> None:
        import time

        stop = min(self._deadline, time.monotonic() + seconds)
        while time.monotonic() < stop:
            packets = self._relay.recv(stop)
            if packets is None:
                return
            opcode, payload = packets
            if opcode == 0x1:
                self._handle_control_text(payload)
                continue
            if opcode != 0x2:
                continue
            for cmd, data in self._accumulator.feed(bytes(payload)):
                if cmd == 3:
                    tile = parse_tile(data)
                    if tile is not None and tile.data:
                        self._tiles.append(tile)
                elif cmd == 7 and len(data) >= 4:
                    # The agent can switch the reported screen mid-session
                    # (display selection). Like the browser, stale tiles are
                    # dropped so they can never composite into the wrong
                    # frame.
                    width = (data[0] << 8) + data[1]
                    height = (data[2] << 8) + data[3]
                    if (
                        width > 0 and height > 0
                        and (width, height) != (self._width, self._height)
                    ):
                        self._width, self._height = width, height
                        self._tiles = []
                elif cmd == 65:
                    self._note_alert(data)
                elif cmd == 87 and len(data) >= 1:
                    self._lock = data[0] != 0

    def capture(self) -> MeshCentralDesktopOutcome:
        """Collect tiles until the screen is covered, then composite one JPEG."""
        import hashlib as _hashlib

        assert self._width and self._height
        self._pump_tiles(10.0)
        width, height = self._width, self._height
        shot = self._try_compose(width, height)
        if shot is None:
            try:
                self._relay.send_binary(msc_refresh())
            except Exception:
                pass
            self._pump_tiles(10.0)
            width, height = self._width, self._height
            shot = self._try_compose(width, height)
        if shot is None:
            covered = self._coverage(width, height)
            return MeshCentralDesktopOutcome(
                termination="desktop_unavailable",
                note=(
                    f"screen {width}x{height} only {covered}% redrawn; "
                    + (f"agent: {'; '.join(self._alerts)}" if self._alerts else "no full frame")
                ),
                width=width, height=height,
            )
        digest = _hashlib.sha256(shot).hexdigest()
        return MeshCentralDesktopOutcome(
            termination="captured",
            note=(
                f"captured {width}x{height} jpeg {len(shot)}B "
                f"sha256 {digest} tiles {len(self._tiles)}"
            ),
            image=shot, width=width, height=height,
        )

    def _coverage(self, width: int, height: int) -> int:
        if not self._tiles:
            return 0
        # Tile pixel sizes need decoding; without a codec no coverage can be
        # claimed, so this stays 0 and the capture is reported unavailable.
        # Sweep disjoint X bands; union Y intervals rather than counting overlapping tiles.
        rectangles = []
        for tile in self._tiles:
            size = _tile_size(tile.data)
            if size is None:
                continue
            w, h = size
            x0, y0 = max(0, tile.x), max(0, tile.y)
            x1, y1 = min(width, tile.x + w), min(height, tile.y + h)
            if x1 > x0 and y1 > y0:
                rectangles.append((x0, y0, x1, y1))
        xs = sorted({edge for x0, _, x1, _ in rectangles for edge in (x0, x1)})
        covered = 0
        for left, right in zip(xs, xs[1:]):
            spans = sorted((y0, y1) for x0, y0, x1, y1 in rectangles
                           if x0 <= left and x1 >= right)
            upper = 0
            for low, high in spans:
                covered += (right - left) * max(0, high - max(upper, low))
                upper = max(upper, high)
        total = width * height
        return (covered * 100) // total if total else 0

    def _try_compose(self, width: int, height: int) -> bytes | None:
        if not self._tiles:
            return None
        if self._coverage(width, height) < 100:
            return None
        try:
            shot = self._compose(width, height, list(self._tiles))
        except MeshCentralDesktopRefused:
            return None
        if not shot.startswith(_JPEG_MAGIC):
            return None
        return shot

    def type_text(self, text: str) -> int:
        """Send unicode down+up per code unit; returns units sent."""
        count = 0
        for char in text:
            encoded = char.encode("utf-16-be")
            for i in range(0, len(encoded), 2):
                unit = int.from_bytes(encoded[i:i + 2], "big")
                # One packet per message, as the browser's SendStringUnicode.
                try:
                    self._relay.send_binary(msc_unicode(_KEY_DOWN, unit))
                    self._relay.send_binary(msc_unicode(_KEY_UP, unit))
                except Exception as exc:
                    raise MeshCentralDesktopRefused(
                        f"input delivery uncertain after {count} complete UTF-16 units; do not replay"
                    ) from exc
                count += 1
        return count

    def press_keys(self, spec: str) -> None:
        sequence = _KEY_SEQUENCES.get(spec, ())
        for action, keycode, extended in sequence:
            try:
                self._relay.send_binary(msc_key(action, keycode, extended))
            except Exception as exc:
                raise MeshCentralDesktopRefused(
                    "key delivery uncertain; do not replay"
                ) from exc

    def click(self, x: int, y: int) -> None:
        for frame in msc_click(x, y):
            try:
                self._relay.send_binary(frame)
            except Exception as exc:
                raise MeshCentralDesktopRefused(
                    "click delivery uncertain; do not replay"
                ) from exc


__all__ = [
    "DESKTOP_COMMAND_PREFIX",
    "MscAccumulator",
    "DesktopTile",
    "MeshCentralDesktopOutcome",
    "MeshCentralDesktopPort",
    "MeshCentralDesktopRefused",
    "StdlibWebSocket",
    "build_ws_handshake_request",
    "check_ws_handshake_response",
    "compose_screenshot_jpeg",
    "decode_ws_frames",
    "encode_ws_frame",
    "msc_click",
    "msc_close",
    "msc_compression",
    "msc_frame",
    "msc_input_lock_query",
    "msc_key",
    "msc_mouse_down",
    "msc_mouse_move",
    "msc_mouse_up",
    "msc_options",
    "msc_pong",
    "msc_refresh",
    "msc_screen_ack",
    "msc_unicode",
    "msc_unicode_text",
    "msc_unpause",
    "open_websocket",
    "parse_desktop_op",
    "parse_msc_packet",
    "parse_tile",
]
