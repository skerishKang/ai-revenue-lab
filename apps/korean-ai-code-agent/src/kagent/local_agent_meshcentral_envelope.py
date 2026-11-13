"""Result-envelope correlation for the MeshCentral command port.

The PC returns one Base64 frame per command, tagged with the dispatch and a value
generated fresh for that run. A console buffer may also hold another dispatch's
frame, so the reader must choose its own frame rather than the last frame. This
module owns that selection and the legacy untagged reader.
"""
from __future__ import annotations

import base64
import re

#: Marker appended to the requested command so the PC reports its own exit code.
EXIT_SENTINEL = "__PADIEM_EXIT__"
#: #5573: the PC's own console label for the encoded reply body.
ENVELOPE_PREFIX = "PADIEM_B64="
#: A result envelope tag is a dispatch id plus the per-run random value.
_ENVELOPE_TAG = re.compile(r"^dsp_[0-9a-f]{16,64}:[0-9a-f]{16,64}$")
_SENTINEL_LINE = re.compile(rb"__PADIEM_EXIT__(-?\d+)?")
_ENVELOPE_WHITESPACE = re.compile(rb"\s+")


def _checked_tag(value: str) -> str:
    if not isinstance(value, str) or _ENVELOPE_TAG.fullmatch(value) is None:
        raise ValueError("the result envelope tag is not a dispatch tag")
    return value


def _session_payload(raw: bytes, expected_tag: str | None = None) -> bytes:
    """The reply from this command's own envelope onward, with terminal noise dropped.

    A terminal writes prompts, echoes and escape sequences around what the PC
    actually printed, and it can also carry a frame that belongs to another
    dispatch. With an ``expected_tag`` the boundary is this command's own marker,
    wherever it appears; without one (legacy callers and tests) it is the last
    marker, exactly as before.
    """
    marker = ENVELOPE_PREFIX.encode("ascii")
    if expected_tag is not None:
        position = raw.rfind(marker + _checked_tag(expected_tag).encode("ascii") + b":")
    else:
        position = raw.rfind(marker)
    if position < 0:
        # No envelope means nothing this lane printed as an answer. A terminal that
        # only mirrors its input must not be shown as the command's output: the reply
        # is noise, and the caller reports an unanswered console.
        return b""
    tail = raw[position:]
    # The shell prompt returns right after the sentinel line, and a prompt is not part
    # of the reply: keep the frame and drop whatever the terminal appended after it.
    index = tail.find(EXIT_SENTINEL.encode("ascii"))
    if index < 0:
        return tail
    end = tail.find(b"\n", index)
    return tail if end < 0 else tail[:end + 1]


def _unwrap_envelope(output: bytes, expected_tag: str | None = None) -> tuple[bytes, bytes] | None:
    """Split one transcript into (text before the envelope, decoded body).

    ``None`` means the reply is not a readable envelope: no marker, a payload
    that is not Base64, or bytes that are not valid UTF-8. A caller that got a
    console answer must not present mangled bytes as if the PC had printed them.

    With ``expected_tag`` only that envelope is read, wherever it sits in the
    buffer; another dispatch's frame before or after it is ignored. The returned
    prefix is empty on that path because the buffer may also hold that other
    frame, and none of it belongs to this result.
    """
    marker = ENVELOPE_PREFIX.encode("ascii")
    if expected_tag is None:
        position = output.find(marker)
        if position < 0:
            return None
        prefix = output[:position]
        payload = _ENVELOPE_WHITESPACE.sub(b"", output[position + len(marker):])
    else:
        needle = marker + _checked_tag(expected_tag).encode("ascii") + b":"
        position = output.find(needle)
        if position < 0:
            return None
        start = position + len(needle)
        end = len(output)
        sentinel = output.find(EXIT_SENTINEL.encode("ascii"), start)
        if sentinel >= 0:
            end = sentinel
        following = output.find(marker, start)
        if 0 <= following < end:
            end = following
        prefix = b""
        payload = _ENVELOPE_WHITESPACE.sub(b"", output[start:end])
    try:
        body = base64.b64decode(payload, validate=True)
    except Exception:
        return None
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return prefix, body


def parse_transcript(
    raw: bytes, expected_tag: str | None = None,
) -> tuple[str, int | None, bytes]:
    """Split one ``--reply`` transcript into (termination, exit code, output).

    ``meshctrl`` prints the agent's console result with ``console.log``, which
    appends exactly one newline of its own; that single byte is removed so the
    returned output is the PC's bytes only. Everything else is preserved
    verbatim, including CR/LF and edge whitespace.

    With ``expected_tag`` the sentinel and envelope are both read from this
    command's own frame. A buffer that carries another dispatch's frame first,
    or only another dispatch's frame, can no longer be returned as this result.
    """
    if not isinstance(raw, (bytes, bytearray)):
        return "no_reply", None, b""
    data = bytes(raw)
    if data.endswith(b"\n"):
        data = data[:-1]
    if expected_tag is not None:
        needle = ENVELOPE_PREFIX.encode("ascii") + _checked_tag(expected_tag).encode("ascii") + b":"
        marker_at = data.find(needle)
        if marker_at < 0:
            index = data.find(EXIT_SENTINEL.encode("ascii"))
            if index < 0:
                return "no_reply", None, b""
            line_end = data.find(b"\n", index)
            if line_end < 0:
                line_end = len(data)
            match = _SENTINEL_LINE.fullmatch(data[data.rfind(b"\n", 0, index) + 1:line_end].strip())
            code = None if match is None or match.group(1) is None else int(match.group(1))
            return "bad_reply", code, b""
        index = data.find(EXIT_SENTINEL.encode("ascii"), marker_at + len(needle))
        following = data.find(ENVELOPE_PREFIX.encode("ascii"), marker_at + len(needle))
        if index < 0 or (following >= 0 and following < index):
            # A partial own frame must not borrow the next dispatch's exit code.
            return "no_reply", None, b""
        start = data.rfind(b"\n", 0, index) + 1
        end = data.find(b"\n", index)
        if end < 0:
            end = len(data)
        match = _SENTINEL_LINE.fullmatch(data[start:end].strip())
        if match is None:
            return "bad_reply", None, b""
        raw_code = match.group(1)
        code = None if raw_code is None else int(raw_code)
        envelope = _unwrap_envelope(data[marker_at:end + 1], expected_tag)
        if envelope is None:
            return "bad_reply", code, b""
        _prefix, body = envelope
        if raw_code is None:
            return "no_exit_code", None, body
        return "exited", code, body
    index = data.rfind(EXIT_SENTINEL.encode("ascii"))
    if index < 0:
        return "no_reply", None, data
    start = data.rfind(b"\n", 0, index) + 1
    end = data.find(b"\n", index)
    if end < 0:
        end = len(data)
    line = data[start:end].strip()
    match = _SENTINEL_LINE.fullmatch(line)
    if match is None:
        return "no_reply", None, data
    raw_code = match.group(1)
    # Drop the sentinel line (and the newline that ended it) from the output.
    output = data[:start] + (data[end + 1:] if end < len(data) else b"")
    code = None if raw_code is None else int(raw_code)
    envelope = _unwrap_envelope(output)
    if envelope is None:
        # The console answered, but not with a readable envelope. This is not a
        # silent console and not a truncation: it is a reply that cannot be
        # presented as the PC's output, so it keeps its own outcome.
        return "bad_reply", code, b""
    prefix, body = envelope
    if prefix:
        body = prefix + body
    if raw_code is None:
        # The sentinel printed an empty value. That is not a console that never
        # answered: PowerShell records `$LASTEXITCODE` only for "the exit code of
        # the last native program or PowerShell script that ran" (Microsoft,
        # about_Automatic_Variables), so a pipeline made only of cmdlets and .NET
        # calls leaves it empty while still returning its whole output. The code
        # stays unobserved here and is never turned into 0.
        return "no_exit_code", None, body
    return "exited", int(raw_code), body
