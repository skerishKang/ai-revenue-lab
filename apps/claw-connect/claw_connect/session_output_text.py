"""#7065 stage 3 — what a pseudo-terminal printed, as plain text.

A pseudo console does not hand back the bytes a program wrote. It renders its
screen and sends the rendering as a VT stream: colours, cursor moves, window
titles, screen clears and mode switches around the text. A session reply is
read by a person or a model, not by a terminal, so the stream is reduced here
to the text a person would see, line by line:

* control sequences (CSI), titles and other strings (OSC, DCS, APC, PM, SOS)
  and two-character escapes are removed;
* a cursor-forward (``CSI n C``), which the renderer uses for runs of spaces, is
  kept as that many spaces;
* a cursor move to another row after text on the current line is kept as a
  line break, so a redraw does not glue two lines together;
* ``CR LF`` becomes ``LF``; a lone ``CR``, the bell and other C0/C1 controls
  are dropped.

A sequence split across two chunks is carried over, never printed half. This is
a reading aid, not a terminal emulator: a full-screen program (an editor, a
pager) is outside what a session is for.
"""
from __future__ import annotations

#: The longest control sequence kept while waiting for its end; anything longer
#: is malformed and is skipped up to its final byte.
MAX_SEQUENCE_CHARS = 64
#: A cursor-forward is rendered as spaces up to this many.
MAX_FORWARD_SPACES = 500
# Internal callback marker; consumed before the session output buffer.
REDRAW_MARKER = "\x00"

_TEXT = "text"
_ESC = "esc"
_ESC_INTERMEDIATE = "esc_intermediate"
_CSI = "csi"
_CSI_SKIP = "csi_skip"
_OSC = "osc"
_STRING = "string"
_OSC_ESC = "osc_esc"
_STRING_ESC = "string_esc"


class TerminalTextFilter:
    """Incremental VT-stream → plain-text reducer. One instance per session."""

    def __init__(self, *, preserve_redraws: bool = False) -> None:
        self._preserve_redraws = preserve_redraws
        self._state = _TEXT
        self._sequence = ""
        self._pending_cr = False
        self._row: int | None = None
        self._line_has_text = False

    def feed(self, data: str, final: bool = False) -> str:
        out: list[str] = []
        for char in data:
            self._step(char, out)
        if final:
            self._pending_cr = False
            self._state = _TEXT
            self._sequence = ""
        return "".join(out)

    # ---- the state machine ---------------------------------------------
    def _step(self, char: str, out: list[str]) -> None:
        state = self._state
        if state == _TEXT:
            self._text(char, out)
        elif state == _ESC:
            if char == "[":
                self._state, self._sequence = _CSI, ""
            elif char == "]":
                self._state = _OSC
            elif char in "PX^_":
                self._state = _STRING
            elif "\x20" <= char <= "\x2f":
                self._state = _ESC_INTERMEDIATE
            else:
                self._state = _TEXT
        elif state == _ESC_INTERMEDIATE:
            if not "\x20" <= char <= "\x2f":
                self._state = _TEXT
        elif state == _CSI:
            if "\x40" <= char <= "\x7e":
                self._state = _TEXT
                self._csi(self._sequence, char, out)
            elif len(self._sequence) < MAX_SEQUENCE_CHARS:
                self._sequence += char
            else:
                self._state = _CSI_SKIP
        elif state == _CSI_SKIP:
            if "\x40" <= char <= "\x7e":
                self._state = _TEXT
        elif state == _OSC:
            if char == "\x07":
                self._state = _TEXT
            elif char == "\x1b":
                self._state = _OSC_ESC
        elif state == _STRING:
            if char == "\x1b":
                self._state = _STRING_ESC
        elif state in (_OSC_ESC, _STRING_ESC):
            if char == "\\":
                self._state = _TEXT
            else:
                self._state = _OSC if state == _OSC_ESC else _STRING

    def _text(self, char: str, out: list[str]) -> None:
        if self._pending_cr:
            self._pending_cr = False
            if char == "\n":
                self._newline(out)
                return
            if self._preserve_redraws:
                out.append(REDRAW_MARKER)
            # A lone carriage return: the line is about to be overwritten. The
            # text already printed stays; nothing is emitted for the CR itself.
        if char == "\x1b":
            self._state = _ESC
        elif char == "\r":
            self._pending_cr = True
        elif char == "\n":
            self._newline(out)
        elif char == "\t":
            out.append(char)
            self._line_has_text = True
        elif ord(char) < 0x20 or char == "\x7f" or "\x80" <= char <= "\x9f":
            return
        else:
            out.append(char)
            self._line_has_text = True

    def _newline(self, out: list[str]) -> None:
        out.append("\n")
        self._line_has_text = False
        if self._row is not None:
            self._row += 1

    def _csi(self, params: str, final: str, out: list[str]) -> None:
        if params[:1] in ("?", ">", "<", "=") or any(c in params for c in " !\"#$%&'()*+,-./"):
            return  # private modes and intermediates change no text
        numbers = []
        for part in params.split(";") if params else []:
            numbers.append(int(part) if part.isdigit() else 0)
        first = numbers[0] if numbers and numbers[0] > 0 else 1
        if final == "C":
            out.append(" " * min(first, MAX_FORWARD_SPACES))
            self._line_has_text = True
        elif final in ("D", "G") and self._preserve_redraws and self._line_has_text:
            out.append(REDRAW_MARKER)
        elif final in ("H", "f", "d"):
            self._move_to_row(first, out)
        elif final == "E" and self._line_has_text:
            self._newline(out)

    def _move_to_row(self, row: int, out: list[str]) -> None:
        if self._line_has_text:
            redraw = (row == 1 if self._row is None else row <= self._row)
            if self._preserve_redraws and redraw:
                out.append(REDRAW_MARKER)
                self._line_has_text = False
            elif row != self._row:
                out.append("\n")
                self._line_has_text = False
        self._row = row


__all__ = ["TerminalTextFilter"]
