"""261105 — one small read must cost one MeshCentral login, not two.

A relay read used to run the PC ReparsePoint walk over the command channel and
then start a second ``meshctrl.js download`` child: two logins, two logins' worth
of 4.5 s. The single-roundtrip path sends the SAME walk first and only reads the
bytes when the walk is clear, then verifies length and SHA-256 before using them.

These tests pin the three answers that matter:

* a clear small file arrives from ONE command reply and never opens a download;
* the walk still runs before a byte is read, inside that same reply;
* anything the executor cannot verify (digest, truncated payload, a file past
  the lane's bound, a reply it cannot parse) falls back to the existing two-step
  path instead of reporting a body it did not verify.

A guard hit is still a refusal with no bytes, exactly as the separate walk
refused before.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import unittest

from kagent.local_agent_meshcentral_command_port import MeshCentralCommandOutcome
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshDispatch,
    OracleMeshExecutor,
    PC_FILE_LINK_REFUSED_MARKER,
    SINGLE_ROUNDTRIP_MAX_BYTES,
    _single_roundtrip_enabled,
)

SECRET = "deployment-channel-secret-value-261105"
NODE = "k0pVCZx5VqYn8P9FW23CaqTNZWHGSlLASVKF1tqJTPRjRGBOhcTfgZbmfi$D62t1"
ROOT = "C:\\"
FILE_PATH = "C:\\Reports\\note.txt"
BODY = "작은 파일 본문\n".encode("utf-8")
DOWNLOAD_BODY = b"download-path-body"


def _guard_marker(hit: bool = False) -> bytes:
    payload = base64.b64encode(json.dumps({"hit": hit}).encode()).decode()
    return ("PADIEM_PC_REPARSE=" + payload + "\n").encode()


def _single_reply(
    payload: bytes | None = None,
    *,
    declared: int | None = None,
    digest: str | None = None,
    verdict: str | None = None,
    wrap_at: int | None = None,
) -> bytes:
    if verdict is not None:
        return ("PADIEM_READ=" + verdict + "\n").encode()
    assert payload is not None
    length = len(payload) if declared is None else declared
    hexdigest = hashlib.sha256(payload).hexdigest() if digest is None else digest
    encoded = base64.b64encode(payload).decode()
    if wrap_at:
        encoded = "\n".join(
            encoded[index:index + wrap_at] for index in range(0, len(encoded), wrap_at)
        )
    return ("PADIEM_READ=" + str(length) + ":" + hexdigest + "\n" + encoded + "\n").encode()


class _CommandPort:
    """Answers a scripted list of replies; records every script it was sent."""

    def __init__(self, outputs, terminations=None):
        self.outputs = list(outputs)
        self.terminations = list(terminations) if terminations else None
        self.scripts: list[str] = []
        self.timeouts: list[object] = []

    def run_command(self, *, node_ref, command, timeout_seconds=30, **kwargs):
        del node_ref, kwargs
        self.scripts.append(command)
        self.timeouts.append(timeout_seconds)
        index = min(len(self.scripts) - 1, len(self.outputs) - 1)
        termination = (
            self.terminations[index] if self.terminations else "exited"
        )
        return MeshCentralCommandOutcome(
            termination=termination,
            exit_code=0 if termination == "exited" else None,
            output=self.outputs[index],
        )


class _ReadPort:
    """The two-step download port; it must not run on the one-reply path."""

    def __init__(self, body: bytes = DOWNLOAD_BODY):
        self.body = body
        self.calls = 0

    def read_bytes(self, *, node_ref, file_path, timeout_seconds=60, max_bytes=None):
        del node_ref, file_path, timeout_seconds, max_bytes
        self.calls += 1
        return self.body


class SingleRoundtripReadTests(unittest.TestCase):
    def _dispatch(self) -> OracleMeshDispatch:
        return OracleMeshDispatch(
            dispatch_id="dsp_single_roundtrip_1",
            nonce="nonce-261105",
            node_ref=NODE,
            file_path=FILE_PATH,
            command_id="cmd.single.1",
            run_id="chat_pcq_925cfc301234567890abcdef12345678",
            granted_root=ROOT,
        )

    def _run(self, command_port, read_port=None, *, enabled=True, timeout_seconds=None):
        read_port = read_port or _ReadPort()
        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=read_port,
            command_port=command_port,
            timeout_seconds=timeout_seconds,
            read_single_roundtrip=enabled,
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            outcome = executor.execute(self._dispatch())
        return outcome, stderr.getvalue(), read_port, command_port

    def test_a_small_file_arrives_from_one_command_reply(self):
        port = _CommandPort([_single_reply(BODY)])
        outcome, trace, read_port, command_port = self._run(port)
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(outcome.body, BODY)
        self.assertEqual(read_port.calls, 0, "one reply means no download child")
        self.assertEqual(len(command_port.scripts), 1)
        self.assertIn("path=single_roundtrip", trace)
        self.assertIn("phase=read_ok", trace)

    def test_the_walk_still_runs_before_a_byte_is_read(self):
        port = _CommandPort([_single_reply(BODY)])
        self._run(port)
        script = port.scripts[0]
        self.assertIn("ReparsePoint", script)
        self.assertIn("ReadAllBytes", script)
        self.assertLess(
            script.index("ReparsePoint"), script.index("ReadAllBytes"),
            "the guard must be decided before the file is read",
        )
        self.assertIn(str(SINGLE_ROUNDTRIP_MAX_BYTES), script)

    def test_a_wrapped_payload_is_read_as_one_body(self):
        port = _CommandPort([_single_reply(BODY * 8, wrap_at=40)])
        outcome, _trace, read_port, _cmds = self._run(port)
        self.assertEqual(outcome.body, BODY * 8)
        self.assertEqual(read_port.calls, 0)

    def test_a_cmdlet_only_reply_is_accepted(self):
        port = _CommandPort([_single_reply(BODY)], terminations=["no_exit_code"])
        outcome, _trace, read_port, _cmds = self._run(port)
        self.assertEqual(outcome.body, BODY)
        self.assertEqual(read_port.calls, 0)

    def test_a_guard_hit_refuses_without_one_byte(self):
        port = _CommandPort([_single_reply(verdict="link_refused")])
        outcome, trace, read_port, _cmds = self._run(port)
        self.assertEqual(outcome.body, PC_FILE_LINK_REFUSED_MARKER.encode("utf-8"))
        self.assertEqual(read_port.calls, 0)
        self.assertIn("phase=link_refused", trace)
        self.assertIn("reason=pc_hit", trace)

    def test_a_digest_mismatch_falls_back_to_the_two_step_path(self):
        port = _CommandPort([
            _single_reply(BODY, digest="0" * 64),
            _guard_marker(),
        ])
        outcome, trace, read_port, command_port = self._run(port)
        self.assertEqual(outcome.body, DOWNLOAD_BODY)
        self.assertEqual(read_port.calls, 1)
        self.assertEqual(len(command_port.scripts), 2)
        self.assertIn("single_roundtrip_fallback", trace)

    def test_a_truncated_payload_falls_back(self):
        port = _CommandPort([
            _single_reply(BODY, declared=len(BODY) + 7),
            _guard_marker(),
        ])
        outcome, _trace, read_port, _cmds = self._run(port)
        self.assertEqual(outcome.body, DOWNLOAD_BODY)
        self.assertEqual(read_port.calls, 1)

    def test_a_file_past_the_bound_falls_back(self):
        port = _CommandPort([_single_reply(verdict="too_large"), _guard_marker()])
        outcome, _trace, read_port, _cmds = self._run(port)
        self.assertEqual(outcome.body, DOWNLOAD_BODY)
        self.assertEqual(read_port.calls, 1)

    def test_an_unreadable_reply_falls_back(self):
        for output in (b"", b"not what the lane writes\n", _single_reply(verdict="guard_error")):
            with self.subTest(output=output):
                port = _CommandPort([output, _guard_marker()])
                outcome, _trace, read_port, _cmds = self._run(port)
                self.assertEqual(outcome.body, DOWNLOAD_BODY)
                self.assertEqual(read_port.calls, 1)

    def test_the_switch_off_keeps_the_existing_two_step_path(self):
        port = _CommandPort([_guard_marker()])
        outcome, _trace, read_port, command_port = self._run(port, enabled=False)
        self.assertEqual(outcome.body, DOWNLOAD_BODY)
        self.assertEqual(read_port.calls, 1)
        self.assertEqual(len(command_port.scripts), 1)
        self.assertNotIn("ReadAllBytes", command_port.scripts[0])

    def test_the_switch_is_a_boolean(self):
        with self.assertRaises(Exception):
            OracleMeshExecutor(
                chat_origin="https://chat.padiem.net",
                channel_secret=SECRET,
                read_port=_ReadPort(),
                read_single_roundtrip="0",
            )


class SwitchFromEnvironmentTests(unittest.TestCase):
    def test_absent_means_on(self):
        self.assertTrue(_single_roundtrip_enabled({}))
        self.assertTrue(_single_roundtrip_enabled({"ORACLE_MESH_READ_SINGLE_ROUNDTRIP": "  "}))

    def test_zero_turns_it_off(self):
        self.assertFalse(
            _single_roundtrip_enabled({"ORACLE_MESH_READ_SINGLE_ROUNDTRIP": "0"})
        )
        self.assertFalse(
            _single_roundtrip_enabled({"ORACLE_MESH_READ_SINGLE_ROUNDTRIP": "off"})
        )

    def test_one_keeps_it_on(self):
        self.assertTrue(
            _single_roundtrip_enabled({"ORACLE_MESH_READ_SINGLE_ROUNDTRIP": "1"})
        )


if __name__ == "__main__":
    unittest.main()
