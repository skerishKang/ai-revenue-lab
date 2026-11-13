"""A result carries its own dispatch tag, so a shared console buffer cannot mix PCs.

The 2026-11-13 reproduction put another PC's read result in the same buffered
session before the next command's answer. The reader used the *last* envelope, so
the next command could be reported with the other result. These tests pin the
replacement rule: choose the frame whose dispatch id and per-dispatch random value
match this run, and fail the run when that frame is absent.
"""
from __future__ import annotations

import base64
import unittest

from kagent.local_agent_meshcentral_command_port import (
    ENVELOPE_PREFIX,
    EXIT_SENTINEL,
    TERMINAL_SCRIPT_BUDGET_BYTES,
    _envelope_tag,
    _file_dispatch_console_script,
    _session_payload,
    _unwrap_envelope,
    _wrap,
    cancel_kill_command,
    parse_transcript,
)

OURS = "dsp_" + "a" * 32
OTHER = "dsp_" + "b" * 32
OUR_TAG = _envelope_tag(OURS, "1" * 32)
OTHER_TAG = _envelope_tag(OTHER, "2" * 32)


def _frame(tag: str | None, body: bytes, code: int = 0) -> bytes:
    head = (ENVELOPE_PREFIX + (tag + ":" if tag else "")).encode("ascii")
    return (
        head + base64.b64encode(body) + b"\n"
        + (EXIT_SENTINEL + str(code)).encode("ascii") + b"\n"
    )


class TheReaderChoosesItsOwnFrame(unittest.TestCase):
    def test_a_foreign_frame_first_does_not_hide_our_later_frame(self):
        raw = _frame(OTHER_TAG, b"other-pc\n", 9) + _frame(OUR_TAG, b"our-pc\n", 0)
        self.assertEqual(parse_transcript(raw, OUR_TAG), ("exited", 0, b"our-pc\n"))

    def test_a_foreign_frame_after_ours_does_not_replace_it(self):
        raw = _frame(OUR_TAG, b"ours\n", 3) + _frame(OTHER_TAG, b"theirs\n", 0)
        self.assertEqual(parse_transcript(raw, OUR_TAG), ("exited", 3, b"ours\n"))

    def test_only_a_foreign_frame_is_a_bad_reply_never_its_body(self):
        raw = _frame(OTHER_TAG, b"theirs\n", 0)
        self.assertEqual(parse_transcript(raw, OUR_TAG), ("bad_reply", 0, b""))
        self.assertEqual(_session_payload(raw, OUR_TAG), b"")

    def test_an_old_untagged_frame_is_not_accepted_as_ours(self):
        raw = _frame(None, b"legacy\n", 0)
        self.assertEqual(parse_transcript(raw, OUR_TAG), ("bad_reply", 0, b""))

    def test_an_old_executor_reading_a_new_tagged_frame_fails_safely(self):
        # Deployment middle state: old reader, new PC script. The colon is not
        # Base64, so the legacy parser refuses the frame instead of reporting it.
        self.assertEqual(parse_transcript(_frame(OUR_TAG, b"ours\n", 0)),
                         ("bad_reply", 0, b""))

    def test_the_reproduction_order_finds_our_frame_not_the_foreign_one(self):
        # start -> stop -> next command, with another PC's read result landing in
        # the same buffer before this command's own answer. The old "last
        # envelope" rule would return the foreign body; the tagged reader cannot.
        raw = (
            b"start\r\n" + _frame(OTHER_TAG, b"other-pc-read\n", 0)
            + b"stop\r\n" + _frame(OUR_TAG, b"next-command\n", 4)
        )
        payload = _session_payload(raw, OUR_TAG)
        self.assertEqual(parse_transcript(payload, OUR_TAG), ("exited", 4, b"next-command\n"))
        self.assertNotIn(b"other-pc-read", payload)

    def test_the_session_lane_keeps_our_frame_when_another_frame_arrives_first(self):
        raw = b"prompt> " + _frame(OTHER_TAG, b"theirs\n", 0) + _frame(OUR_TAG, b"ours\n", 0)
        payload = _session_payload(raw, OUR_TAG)
        self.assertIn(OUR_TAG.encode("ascii"), payload)
        self.assertNotIn(OTHER_TAG.encode("ascii"), payload)
        self.assertEqual(parse_transcript(payload, OUR_TAG), ("exited", 0, b"ours\n"))

    def test_a_foreign_only_buffer_is_not_unwrapped_by_our_tag(self):
        raw = _frame(OTHER_TAG, b"theirs\n", 0)
        self.assertIsNone(_unwrap_envelope(raw, OUR_TAG))


class TheMarkerTravelsWithTheEnvelope(unittest.TestCase):
    def test_the_wrapped_script_carries_the_tag_too(self):
        script = _wrap("whoami", OURS, None, envelope_tag=OUR_TAG)
        self.assertIn('"' + OUR_TAG + ':"', script)

    def test_the_file_delivery_script_carries_the_tag_and_never_the_joined_marker(self):
        script = _file_dispatch_console_script(
            "whoami", OURS, "padiem-com2-exec.1", envelope_tag=OUR_TAG,
        )
        self.assertIn("'B64='+'" + OUR_TAG + ":'+[Convert]::ToBase64String(", script)
        self.assertNotIn(ENVELOPE_PREFIX, script)

    def test_the_longest_stop_script_stays_under_the_terminal_budget(self):
        longest = "dsp_" + "f" * 64
        size = len(cancel_kill_command(longest).encode("utf-8"))
        self.assertLess(size, TERMINAL_SCRIPT_BUDGET_BYTES)
        # The envelope tag adds 50 ASCII bytes; the budget belongs to the stop
        # script, which has no tag and keeps its existing bound.
        self.assertGreaterEqual(size, 1)


if __name__ == "__main__":
    unittest.main()
