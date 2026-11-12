"""#7065 stage 3 — a pseudo console's VT stream reduced to readable text."""
from __future__ import annotations

import pytest

from claw_connect.session_output_text import TerminalTextFilter


def reduce(*chunks: str) -> str:
    text_filter = TerminalTextFilter()
    return "".join(text_filter.feed(chunk) for chunk in chunks) + text_filter.feed("", final=True)


def test_plain_text_and_korean_pass_through():
    assert reduce("hello 한글\n") == "hello 한글\n"


def test_crlf_becomes_lf_even_when_split_across_chunks():
    assert reduce("a\r\nb\r", "\nc") == "a\nb\nc"


def test_a_lone_carriage_return_and_other_controls_are_dropped():
    assert reduce("50%\r100%\x07 done\x08\x00\x7f\x9b") == "50%100% done"


@pytest.mark.parametrize("sequence", [
    "\x1b[31m", "\x1b[0;1;32m", "\x1b[m", "\x1b[K", "\x1b[2J", "\x1b[?25l", "\x1b[?25h",
    "\x1b[?9001h", "\x1b[?1004h", "\x1b[>4;1m", "\x1b[3X", "\x1b[1 q",
    "\x1b]0;C:\\Windows\\system32\\cmd.exe\x07", "\x1b]0;title\x1b\\",
    "\x1bP1$r0m\x1b\\", "\x1b_app\x1b\\", "\x1b(B", "\x1b=", "\x1b7", "\x1b8",
])
def test_control_sequences_change_no_text(sequence):
    assert reduce("a" + sequence + "b") == "ab"


def test_a_sequence_split_across_chunks_is_never_printed_half():
    assert reduce("a\x1b", "[3", "1", "mb\x1b]0;ti", "tle\x07c") == "abc"


def test_cursor_forward_is_kept_as_spaces():
    assert reduce("a\x1b[3Cb\x1b[Cc") == "a   b c"


def test_a_move_to_another_row_after_text_is_a_line_break():
    # A redraw: clear, home, text, then a jump to row 2 instead of CR LF.
    assert reduce("\x1b[2J\x1b[Hfirst\x1b[2;1Hsecond") == "first\nsecond"


def test_a_move_without_text_or_to_the_same_row_adds_nothing():
    assert reduce("\x1b[H\x1b[5;1H>>> ") == ">>> "
    assert reduce("\x1b[3;1Habc\x1b[3;10Hdef") == "abcdef"


def test_rows_are_followed_across_line_feeds():
    # After "a" CR LF the cursor is on row 2; a move to row 2 is not a new line.
    assert reduce("\x1b[1;1Ha\r\n\x1b[2;1Hb") == "a\nb"


def test_a_malformed_sequence_ends_and_text_resumes():
    assert reduce("a\x1b[" + "1;" * 100 + "zb") == "ab"


def test_a_prompt_keeps_its_trailing_space_and_no_line_end():
    assert reduce("\x1b[?25l>>> \x1b[?25h") == ">>> "
