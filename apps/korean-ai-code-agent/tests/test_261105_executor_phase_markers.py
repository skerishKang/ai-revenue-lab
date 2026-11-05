"""#261105 — the instants between "the queue handed it over" and "the PC answered".

A PC read on COM2 measured 12.5 s and 15.2 s from dispatch creation to submission
(2026-11-05, against 8.9 s an hour earlier) while the submission itself was solved at
0.2-0.3 s. Nothing between the claim and the answer carried a timestamp, so the wait
could not be blamed on the queue, on the guard's round trip, or on the download
without running the read again. These lines answer that and carry nothing else: the
existing phase format, and never a path, a value or command content.

The read itself is already timed by #6960 as ``phase=read_ok``, on both the one-reply
and the two-step path, so no second name is put on the same instant. What was missing
is the claim and the end of the guard, and those are what this adds.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import types
import unittest

from kagent.local_agent_oracle_mesh_executor import (
    POLL_PATH,
    RESULT_PATH,
    OracleMeshExecutor,
)

SECRET = "deployment-channel-secret-value-261105"
CHAT = "http://127.0.0.1:8798"
EDGE = "com2-edge-proof-secret-" + "e" * 32
NODE = "node-ref-261105"
FILE_PATH = "C:/synthetic/night.txt"
BODY = "본문".encode("utf-8")


def _dispatch(**extra) -> dict:
    payload = {
        "dispatch_id": "dsp-261105",
        "nonce": "n" * 32,
        "node_ref": NODE,
        "file_path": FILE_PATH,
        "command_id": "cmd-261105",
        "run_id": "run-261105",
        "granted_root": "C:/synthetic",
    }
    payload.update(extra)
    return payload


class _ReadPort:
    def read_bytes(self, **kwargs):
        del kwargs
        return BODY


class _OneReplyPort:
    """Answers the fused guard+read script with a reply the executor can verify."""

    def __init__(self, body: bytes = BODY) -> None:
        self.body = body
        self.calls = 0

    def run_command(self, **kwargs):
        del kwargs
        self.calls += 1
        encoded = base64.b64encode(self.body).decode("ascii")
        reply = (
            f"PADIEM_READ={len(self.body)}:"
            f"{hashlib.sha256(self.body).hexdigest()}{encoded}"
        ).encode("utf-8")
        return types.SimpleNamespace(termination="exited", exit_code=0, output=reply)


def _round(executor):
    calls = []

    def transport(path, payload):
        calls.append(path)
        if path == POLL_PATH:
            return 200, {"ok": True, "dispatch": _dispatch()}
        return 200, {"ok": True, "accepted": True}

    executor._transport = transport
    journal = io.StringIO()
    with contextlib.redirect_stderr(journal):
        executor.run_once()
    return journal.getvalue(), calls


def _phases(journal: str) -> list[str]:
    return [
        line.split(" phase=")[1].split(" ")[0]
        for line in journal.splitlines() if " phase=" in line
    ]


def _executor(**kwargs):
    return OracleMeshExecutor(
        chat_origin=CHAT, channel_secret=SECRET, edge_secret=EDGE,
        read_port=_ReadPort(), **kwargs,
    )


class TestClaimAndGuardMarkers(unittest.TestCase):
    def test_the_two_step_read_marks_claim_then_guard_then_read(self):
        journal, calls = _round(_executor())
        seen = _phases(journal)
        for phase in ("claimed", "guard_done", "read_ok"):
            self.assertIn(phase, seen)
            self.assertEqual(seen.count(phase), 1, phase)
        self.assertLess(seen.index("claimed"), seen.index("guard_done"))
        self.assertLess(seen.index("guard_done"), seen.index("read_ok"))
        self.assertEqual(calls, [POLL_PATH, RESULT_PATH], "one claim, one submit")

    def test_the_one_reply_read_marks_no_guard_line_of_its_own(self):
        # The fused path answers the walk and the bytes in one trip, so a second
        # timestamp would claim a round trip that never happened.
        journal, _ = _round(
            _executor(command_port=_OneReplyPort(), read_single_roundtrip=True)
        )
        seen = _phases(journal)
        self.assertEqual(seen.count("claimed"), 1)
        self.assertIn("phase=read_ok", journal.replace(" phase=", "phase="))
        self.assertNotIn("guard_done", seen)
        self.assertIn("single_roundtrip", journal)

    def test_a_failed_read_keeps_its_own_phase_and_never_reads_done(self):
        class _Refusing:
            def read_bytes(self, **kwargs):
                del kwargs
                raise OSError("channel died")

        executor = _executor()
        executor._read_port = _Refusing()
        journal, _ = _round(executor)
        seen = _phases(journal)
        self.assertIn("guard_done", seen)
        self.assertIn("read_failed", seen)
        self.assertNotIn("read_ok", seen)
        self.assertEqual(seen.count("claimed"), 1)

    def test_the_new_lines_keep_the_existing_phase_shape(self):
        journal, _ = _round(_executor())
        for phase in ("claimed", "guard_done"):
            line = next(l for l in journal.splitlines() if f" phase={phase}" in l)
            for field in (" ts=", " elapsed_ms=", " dispatch_id=", " run_hash="):
                self.assertIn(field, line, f"{phase}: {line}")
            self.assertIn("dsp-261105", line)

    def test_no_marker_carries_a_path_a_value_or_a_secret(self):
        journal, _ = _round(_executor())
        for forbidden in (FILE_PATH, NODE, SECRET, EDGE, CHAT, "본문"):
            self.assertNotIn(forbidden, journal, forbidden)

    def test_a_skipped_or_empty_round_prints_no_claim(self):
        def transport(path, payload):
            return 200, {"ok": True, "dispatch": None}

        executor = _executor()
        executor._transport = transport
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            self.assertIsNone(executor.run_once())
        self.assertNotIn("claimed", _phases(journal.getvalue()))


if __name__ == "__main__":
    unittest.main()
