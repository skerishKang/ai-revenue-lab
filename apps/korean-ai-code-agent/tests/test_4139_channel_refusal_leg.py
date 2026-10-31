"""#84 - which server refused? The line names the leg; the message does not change.

The evidence for this file is the 2026-10-30 cutover attempt: the Worker had switched to
the queue, the queue's edge was refusing the Worker's calls, and the executor journal said
`chat channel refused the poll` for all of it. Nothing in the journal distinguished a
Cloudflare bot block on a loopback service's public name from a Worker that was down, and
the lane had to be diagnosed by comparing two databases instead.
"""
from __future__ import annotations

import io
import unittest
import urllib.request
from unittest.mock import patch

from kagent.local_agent_oracle_mesh_executor import (
    BUSY_PATH, CHANNEL_HEADER, CANCEL_PATH, LEASE_RENEW_PATH, POLL_PATH, RESULT_PATH,
    OracleMeshChannelRefused, OracleMeshExecutor, channel_refusal_line,
)

SECRET = "deployment-channel-secret-value-261017"
CHAT = "https://chat.padiem.net"
QUEUE = "http://127.0.0.1:8797"


def _executor(**kwargs) -> OracleMeshExecutor:
    class _StubPort:
        def read_bytes(self, *, node_ref, file_path, timeout_seconds):
            del node_ref, file_path, timeout_seconds
            return b""

    return OracleMeshExecutor(chat_origin=CHAT, channel_secret=SECRET,
                              read_port=_StubPort(), **kwargs)


class TestLegNaming(unittest.TestCase):
    def test_without_a_queue_every_leg_is_the_chat_one(self):
        executor = _executor()
        for path in (POLL_PATH, LEASE_RENEW_PATH, CANCEL_PATH, BUSY_PATH, RESULT_PATH):
            self.assertEqual(executor._leg_for(path), "chat", path)

    def test_with_a_queue_the_claim_legs_are_queue_and_the_result_stays_chat(self):
        executor = _executor(queue_origin=QUEUE)
        for path in (POLL_PATH, LEASE_RENEW_PATH, CANCEL_PATH, BUSY_PATH):
            self.assertEqual(executor._leg_for(path), "queue", path)
        self.assertEqual(executor._leg_for(RESULT_PATH), "chat")

    def test_the_leg_is_the_same_ruling_that_routes_the_request(self):
        # Not a second table of paths: the word comes out of _origin_for itself, so the
        # monitor cannot be left counting one server while the socket asks another.
        executor = _executor(queue_origin=QUEUE)
        for path in (POLL_PATH, RESULT_PATH):
            asked = executor._origin_for(path)
            named = executor._leg_for(path)
            self.assertEqual(asked, QUEUE if named == "queue" else CHAT, path)


class TestRefusalsCarryTheLeg(unittest.TestCase):
    def _refusing(self, executor, status=503, body=b'{"ok":false}'):
        class _Response(io.BytesIO):
            def __init__(self, payload, code=200):
                super().__init__(payload)
                self.status = code

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()
                return False

        class _Opener:
            def open(self, request, timeout=None):
                del request, timeout
                return _Response(body, status)

        with patch("urllib.request.build_opener", return_value=_Opener()):
            with self.assertRaises(OracleMeshChannelRefused) as caught:
                executor.poll_once()
        return caught.exception

    def test_a_refused_poll_names_the_server_that_was_asked(self):
        exc = self._refusing(_executor(queue_origin=QUEUE))
        self.assertEqual(exc.leg, "queue")
        exc = self._refusing(_executor())
        self.assertEqual(exc.leg, "chat")

    def test_the_message_is_word_for_word_what_it_always_was(self):
        # Monitors and operators read this text; adding a field must not rewrite it.
        exc = self._refusing(_executor(queue_origin=QUEUE))
        self.assertEqual(str(exc), "chat channel refused the poll")

    def test_the_line_appends_the_field_and_keeps_the_prefix(self):
        exc = self._refusing(_executor(queue_origin=QUEUE))
        line = channel_refusal_line(exc)
        self.assertTrue(line.startswith("oracle-mesh-executor channel refusal: "))
        self.assertIn(" leg=queue", line)
        self.assertIn("chat channel refused the poll", line)

    def test_a_refusal_without_a_leg_prints_the_old_line_exactly(self):
        # An installed executor that predates this field must stay readable, and an
        # unattributed refusal is counted as unattributed rather than guessed as chat.
        bare = OracleMeshChannelRefused("the deployment secret file is empty")
        line = channel_refusal_line(bare)
        self.assertEqual(
            line, "oracle-mesh-executor channel refusal: the deployment secret file is empty")
        self.assertNotIn("leg=", line)

    def test_the_line_never_carries_an_origin_a_secret_or_a_header(self):
        exc = self._refusing(_executor(queue_origin=QUEUE))
        line = channel_refusal_line(exc)
        for forbidden in (QUEUE, CHAT, SECRET, CHANNEL_HEADER):
            self.assertNotIn(forbidden, line, forbidden)


if __name__ == "__main__":
    unittest.main()
