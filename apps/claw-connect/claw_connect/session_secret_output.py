"""In-memory masking of explicitly secret session input, before output storage.

Only registered input values are matched. An unfinished match stays here rather
than entering the output buffer: later chunks may complete it. ConPTY has
already reduced VT controls before this filter runs; spaces and line breaks
inserted by its renderer may occur between the input's visible characters.
"""
from __future__ import annotations

import re

from .session_output_text import REDRAW_MARKER, TerminalTextFilter

MASK = "••••"
MAX_PENDING_CHARS = 8192
_RENDER_SPACE = frozenset(" \n\r")
_SECRET_PROMPT = re.compile(r"(?:password|passphrase|암호|비밀번호|pin)\s*:\s*$", re.IGNORECASE)


class SecretOutputFilter:
    """One session's secrets and unfinished output; never a durable record.

    The manager serializes registration, filtering and buffer append with its
    output lock. This object's repr deliberately contains no state. Values are
    remembered until the output closes, so delayed/repeated echoes remain
    protected; close also masks an incomplete final echo and releases them.
    """

    def __init__(self) -> None:
        self._patterns: dict[str, set[str]] = {}
        self._pending = ""
        self._masked_prefix: list[tuple[str, int]] = []
        self._terminal = False
        self._closed = False

    def __repr__(self) -> str:
        return "<SecretOutputFilter>"

    def register(self, text: str, *, terminal: bool, encoding: str) -> None:
        if self._closed:
            return
        self._terminal = terminal
        # A pipe may replace characters unavailable in its chosen input code
        # page. Protect the value the child actually receives as well.
        sent = text if terminal else text.encode(encoding, errors="replace").decode(encoding)
        variants = {text, sent}
        if terminal:
            variants.add(TerminalTextFilter().feed(sent, final=True))
        for value in variants:
            for line in value.split("\n"):
                if terminal:
                    # Cursor-forward and automatic wrapping can insert spaces
                    # or newlines. This changes matching of this value only.
                    compact = "".join(char for char in line if char not in _RENDER_SPACE)
                    line = compact or line
                if line:
                    self._patterns.setdefault(line[0], set()).add(line)

    def feed(self, text: str, *, final: bool = False) -> str:
        chunks = text.split(REDRAW_MARKER)
        out = []
        for index, chunk in enumerate(chunks):
            if index:
                continuations = set(self._masked_prefix)
                if self._pending:
                    for pattern in self._patterns.get(self._pending[0], ()):
                        _, unfinished, matched = self._match(self._pending, 0, pattern)
                        if unfinished:
                            continuations.add((pattern, matched))
                    out.append(MASK)
                    self._pending = ""
                # A cursor movement can either resume the remaining suffix or
                # repaint the value from its start. Protect both interpretations
                # without exposing the already masked prefix again.
                self._masked_prefix = list(continuations | {
                    (pattern, 0) for pattern, _ in continuations})
            out.append(self._feed_text(chunk, final=final and index == len(chunks) - 1))
        return "".join(out)

    def _feed_text(self, text: str, *, final: bool = False) -> str:
        if self._closed:
            return ""
        data = self._pending + self._continue_masked_prefix(text)
        self._pending = ""
        out: list[str] = []
        position = 0
        while position < len(data):
            complete = position
            pending: list[tuple[str, int]] = []
            for pattern in self._patterns.get(data[position], ()):
                end, unfinished, index = self._match(data, position, pattern)
                complete = max(complete, end)
                if unfinished:
                    pending.append((pattern, index))
            if pending and not final:
                if len(data) - position <= MAX_PENDING_CHARS:
                    self._pending = data[position:]
                else:
                    # Arbitrarily many terminal spaces must not create an
                    # unbounded second output buffer. Once this span is
                    # masked, retain only pattern references and positions;
                    # its remaining characters are consumed without storage.
                    out.append(MASK)
                    self._masked_prefix = pending
                break
            if pending and final:
                # A program may die halfway through echoing the value. Its
                # unfinished prefix must not become visible on the final read.
                out.append(MASK)
                break
            if complete > position:
                out.append(MASK)
                position = complete
            else:
                out.append(data[position])
                position += 1
        if final:
            self._closed = True
            self._patterns.clear()
            self._pending = ""
            self._masked_prefix.clear()
        return "".join(out)

    def _continue_masked_prefix(self, text: str) -> str:
        for position, char in enumerate(text):
            if not self._masked_prefix:
                return text[position:]
            remaining = []
            for pattern, index in self._masked_prefix:
                if index == len(pattern):
                    continue
                if char == pattern[index]:
                    remaining.append((pattern, index + 1))
                elif self._terminal and char in _RENDER_SPACE:
                    remaining.append((pattern, index))
            self._masked_prefix = remaining
            if not remaining:
                return text[position:]
            if all(index == len(pattern) for pattern, index in remaining):
                self._masked_prefix.clear()
        return ""

    def _match(self, data: str, start: int, pattern: str) -> tuple[int, bool, int]:
        position = start
        crossed_line = False
        for index, expected in enumerate(pattern):
            if self._terminal and index and expected not in _RENDER_SPACE:
                while position < len(data) and data[position] in _RENDER_SPACE:
                    crossed_line = crossed_line or data[position] in "\r\n"
                    position += 1
            if position == len(data):
                return start, True, index
            if data[position] != expected:
                if index > 1 and (data[position] in "\r\n" or crossed_line):
                    # A terminated partial echo is sensitive too. Keep the
                    # next character for the following match. Repaints have
                    # an explicit marker, not a guess from repeated letters.
                    return position, False, index
                return start, False, index
            position += 1
        return position, False, len(pattern)


def prompt_hints(tail: str, *, alive: bool, ends_with_newline: bool) -> dict[str, str]:
    """Advisory hints from the current final line, never permission to input."""
    if not alive or not tail or ends_with_newline:
        return {}
    hints = {"waiting_hint": "input"}
    if _SECRET_PROMPT.search(tail.rsplit("\n", 1)[-1]):
        hints["prompt_kind"] = "secret"
    return hints


__all__ = ["MASK", "SecretOutputFilter", "prompt_hints"]
