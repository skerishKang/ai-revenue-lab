"""#4139 desktop lane — executor branch, submit wire and held-result recovery.

The desktop dispatch flows through the same claim/execute/submit machinery
as the read and command lanes: the op grammar is parsed before the PC is
asked, a screenshot travels as PNG evidence beside its observation note,
and a held desktop result resends byte-identical after a restart. No
MeshCentral server and no live credential are involved.
"""
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from kagent.local_agent_meshcentral_desktop_port import (
    MeshCentralDesktopOutcome,
    MeshCentralDesktopRefused,
)
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshDispatch,
    OracleMeshExecutionOutcome,
    OracleMeshExecutor,
    make_oracle_mesh_executor,
)

SECRET = "deployment-channel-secret-value-261017"
NODE = "e" * 64
PNG = b"\xff\xd8\xff" + b"\x00" * 64
NOTE = "captured 800x600 png 72B sha256 deadbeef tiles 1"


class _StubReadPort:
    def read_bytes(self, *, node_ref, file_path, timeout_seconds):  # noqa: D102
        del node_ref, file_path, timeout_seconds
        return b""


class _StubDesktopPort:
    def __init__(self, outcome=None, error=None):
        self.outcome = outcome
        self.error = error
        self.calls = []

    def run_desktop_op(self, *, node_ref, op, arg=None, timeout_seconds=120):  # noqa: D102
        self.calls.append((node_ref, op, arg, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.outcome


def _desktop_dispatch(command_text="desktop:capture"):
    return OracleMeshDispatch(
        dispatch_id="dsp_" + "a" * 28,
        nonce="n" * 32,
        node_ref=NODE,
        file_path="command",
        command_id="cmd_test",
        run_id="run_test",
        kind="desktop",
        command_text=command_text,
    )


class DesktopExecuteTests(unittest.TestCase):
    def _executor(self, port):
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubReadPort(),
            desktop_port=port,
        )

    def test_capture_returns_png_body_and_note(self):
        outcome = MeshCentralDesktopOutcome(
            termination="captured", note=NOTE, image=PNG, width=800, height=600)
        port = _StubDesktopPort(outcome=outcome)
        result = self._executor(port).execute(_desktop_dispatch())
        self.assertEqual(result.termination, "captured")
        self.assertEqual(result.body, PNG)
        self.assertEqual(result.note, NOTE)
        self.assertEqual(port.calls[0][:3], (NODE, "capture", None))
        # A full redraw waits longer than a console transcript.
        self.assertEqual(port.calls[0][3], 120)

    def test_act_returns_note_without_body(self):
        outcome = MeshCentralDesktopOutcome(termination="acted", note="keys enter")
        port = _StubDesktopPort(outcome=outcome)
        result = self._executor(port).execute(_desktop_dispatch("desktop:keys\nenter"))
        self.assertEqual((result.termination, result.body, result.note),
                         ("acted", b"", "keys enter"))
        self.assertEqual(port.calls[0][1:3], ("keys", "enter"))

    def test_type_arg_reaches_the_port_verbatim(self):
        outcome = MeshCentralDesktopOutcome(termination="acted", note="typed 4 characters")
        port = _StubDesktopPort(outcome=outcome)
        self._executor(port).execute(_desktop_dispatch("desktop:type\nAb12"))
        self.assertEqual(port.calls[0][1:3], ("type", "Ab12"))

    def test_unknown_op_never_reaches_the_port(self):
        port = _StubDesktopPort(outcome=MeshCentralDesktopOutcome(
            termination="acted", note="x"))
        result = self._executor(port).execute(_desktop_dispatch("desktop:explode"))
        self.assertEqual(result.termination, "not_executed")
        self.assertEqual(port.calls, [])

    def test_refused_relay_is_not_executed(self):
        port = _StubDesktopPort(error=MeshCentralDesktopRefused("nope"))
        result = self._executor(port).execute(_desktop_dispatch())
        self.assertEqual((result.termination, result.body), ("not_executed", b""))

    def test_broken_relay_is_unavailable_not_silent(self):
        port = _StubDesktopPort(error=OSError("tunnel down"))
        result = self._executor(port).execute(_desktop_dispatch())
        self.assertEqual(result.termination, "desktop_unavailable")

    def test_missing_desktop_port_is_a_misconfiguration(self):
        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubReadPort(),
        )
        with self.assertRaises(Exception):
            executor.execute(_desktop_dispatch())

    def test_oversize_png_is_withheld_with_its_note(self):
        big = b"\xff\xd8\xff" + b"\x00" * (6_000_001)
        outcome = MeshCentralDesktopOutcome(
            termination="captured", note="captured huge", image=big)
        result = self._executor(_StubDesktopPort(outcome=outcome)).execute(
            _desktop_dispatch())
        self.assertEqual(result.termination, "output_too_large")
        self.assertEqual(result.body, b"")
        self.assertEqual(result.note, "captured huge")

    def test_poll_accepts_desktop_with_an_op(self):
        seen = {}

        def transport(path, payload):
            seen["payload"] = payload
            return 200, {"ok": True, "dispatch": {
                "dispatch_id": "dsp_x", "nonce": "n" * 32, "node_ref": NODE,
                "file_path": "command", "command_id": "c", "run_id": "r",
                "kind": "desktop", "command_text": "desktop:capture"}}

        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net", channel_secret=SECRET,
            read_port=_StubReadPort(), transport=transport)
        dispatch = executor.poll_once()
        self.assertIsNotNone(dispatch)
        self.assertEqual(dispatch.kind, "desktop")
        self.assertEqual(dispatch.command_text, "desktop:capture")

    def test_poll_refuses_desktop_without_an_op(self):
        def transport(path, payload):
            return 200, {"ok": True, "dispatch": {
                "dispatch_id": "dsp_x", "nonce": "n" * 32, "node_ref": NODE,
                "file_path": "command", "command_id": "c", "run_id": "r",
                "kind": "desktop", "command_text": "  "}}

        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net", channel_secret=SECRET,
            read_port=_StubReadPort(), transport=transport)
        with self.assertRaises(Exception):
            executor.poll_once()

    def test_factory_composes_a_desktop_port(self):
        executor = make_oracle_mesh_executor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            meshctrl_js="/opt/meshcentral/meshctrl.js",
            login_user="padiemadmin",
            password_provider=lambda: "pw",
        )
        self.assertTrue(callable(executor._desktop_port.run_desktop_op))


class DesktopSubmitTests(unittest.TestCase):
    def _executor(self, transport, work_dir=None):
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net", channel_secret=SECRET,
            read_port=_StubReadPort(),
            desktop_port=_StubDesktopPort(),
            transport=transport, pending_dir=work_dir,
        )

    def test_serialized_jpeg_over_envelope_is_preserved_not_posted(self):
        calls = []
        def transport(path, payload):
            calls.append(path)
            return 200, {"ok": True}
        with tempfile.TemporaryDirectory() as work:
            executor = self._executor(transport, work)
            outcome = OracleMeshExecutionOutcome(
                termination="captured", exit_code=None,
                body=b"\xff\xd8\xff" + b"x" * 4_600_000,
                note="capture")
            verdict = executor.submit(_desktop_dispatch(), outcome)
            self.assertEqual(verdict.get("reason"), "desktop_result_wire_envelope_exceeded")
            self.assertTrue(verdict.get("outcome_preserved"))
            self.assertEqual(calls, [])
            self.assertTrue(executor.resend_pending)

    def test_capture_payload_pins_the_png(self):
        seen = {}

        def transport(path, payload):
            seen.update(payload)
            return 200, {"ok": True}

        outcome = OracleMeshExecutionOutcome(
            termination="captured", exit_code=None, body=PNG, note=NOTE)
        result = self._executor(transport).submit(_desktop_dispatch(), outcome)
        self.assertTrue(result.get("ok"))
        self.assertEqual(seen["content_utf8"], NOTE)
        self.assertEqual(seen["content_sha256"], hashlib.sha256(PNG).hexdigest())
        self.assertEqual(seen["content_bytes"], len(PNG))
        self.assertEqual(seen["content_blob_sha256"], hashlib.sha256(PNG).hexdigest())
        self.assertEqual(seen["content_blob_bytes"], len(PNG))
        self.assertEqual(seen["content_blob_media_type"], "image/jpeg")
        self.assertEqual(base64.b64decode(seen["content_blob_base64"]), PNG)

    def test_act_payload_pins_the_note(self):
        seen = {}

        def transport(path, payload):
            seen.update(payload)
            return 200, {"ok": True}

        outcome = OracleMeshExecutionOutcome(
            termination="acted", exit_code=None, body=b"", note="keys enter")
        result = self._executor(transport).submit(_desktop_dispatch(), outcome)
        self.assertTrue(result.get("ok"))
        self.assertEqual(seen["content_utf8"], "keys enter")
        self.assertEqual(seen["content_sha256"], hashlib.sha256(b"keys enter").hexdigest())
        self.assertEqual(seen["content_bytes"], len(b"keys enter"))
        self.assertNotIn("content_blob_base64", seen)

    def test_transient_failure_keeps_png_for_resend(self):
        calls = []

        def transport(path, payload):
            calls.append(dict(payload))
            return 503, {"error": {"code": "oracle_mesh_dispatch_unavailable"}}

        executor = self._executor(transport)
        outcome = OracleMeshExecutionOutcome(
            termination="captured", exit_code=None, body=PNG, note=NOTE)
        result = executor.submit(_desktop_dispatch(), outcome)
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("retryable"))
        self.assertTrue(executor.resend_pending)

    def test_shared_refusal_policy_on_desktop_leg(self):
        def transport_409(path, payload):
            return 409, {"error": {"code": "oracle_mesh_dispatch_rejected"}}

        executor = self._executor(transport_409)
        outcome = OracleMeshExecutionOutcome(
            termination="acted", exit_code=None, body=b"", note="keys enter")
        first = executor.submit(_desktop_dispatch(), outcome)
        self.assertTrue(first.get("resend_pending"))
        # Bounded retries, then quarantined — never resent forever.
        second = executor.resend_pending_result()
        self.assertTrue(second.get("resend_pending"))
        third = executor.resend_pending_result()
        self.assertTrue(third.get("quarantined"))
        self.assertFalse(executor.resend_pending)

    def test_held_desktop_result_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as work:
            def transport_ok(path, payload):
                return 200, {"ok": True}

            first = self._executor(transport_ok, work_dir=work)
            outcome = OracleMeshExecutionOutcome(
                termination="captured", exit_code=None, body=PNG, note=NOTE)
            dispatch = _desktop_dispatch()

            def transport_down(path, payload):
                raise ConnectionError("tunnel down")

            down = self._executor(transport_down, work_dir=work)
            held = down.submit(dispatch, outcome)
            self.assertTrue(held.get("resend_pending"))

            manifest = json.loads(
                (Path(work) / "pending-result.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["kind"], "desktop")
            self.assertEqual(manifest["note"], NOTE)
            self.assertEqual(manifest["termination"], "captured")

            revived = self._executor(transport_ok, work_dir=work)
            self.assertTrue(revived.load_pending())
            again = revived.resend_pending_result()
            self.assertTrue(again.get("ok"))

    def test_invalid_note_is_quarantined_never_sent(self):
        sent = []

        def transport(path, payload):
            sent.append(payload)
            return 200, {"ok": True}

        outcome = OracleMeshExecutionOutcome(
            termination="acted", exit_code=None, body=b"", note="bad\x07note")
        result = self._executor(transport).submit(_desktop_dispatch(), outcome)
        self.assertTrue(result.get("quarantined"))
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
