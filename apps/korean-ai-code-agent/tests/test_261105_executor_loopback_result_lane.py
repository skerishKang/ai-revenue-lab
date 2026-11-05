"""#261105 — the result lane may be aimed at the Chat host's loopback, behind its edge.

Measured on COM2 on 2026-11-05: the claim lane already answers on this host
(``http://127.0.0.1:8797``) while the one leg that never goes there is the result
submission, and it crosses ``https://chat.padiem.net`` — 3020 ms and 4520 ms for the
two PC reads in the journal, against 150-550 ms of Chat-side work. Loopback is the
fix, and the thing that stands in its way is ``com2_edge_middleware``, which answers
an unsigned request with a bare 403 before any route reads the channel secret.

These tests pin the four rules that make that safe, and nothing else:

* a chat origin may be https or a literal loopback http origin — any other http
  origin is still refused, because the channel secret crosses the wire;
* exactly the four ``x-padiem-edge-*`` headers appear on a chat leg that reaches
  the edge, and none appear on the public https origin;
* the headers are checked by **Chat's own verifier**, loaded from
  ``packages/padiem-control-plane/com2_edge_proof.py`` — the contract under test is
  the deployed one, and a reused request id is the replay that verifier exists to
  refuse;
* the opener and its TLS context are built once per executor, not once per request.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from kagent.local_agent_oracle_mesh_executor import (
    EDGE_HEADERS,
    POLL_PATH,
    RESULT_PATH,
    ContractError,
    OracleMeshExecutor,
    edge_proof_headers,
)

SECRET = "deployment-channel-secret-value-261105"
EDGE_SECRET = "com2-edge-proof-secret-" + "e" * 32
CHAT_HTTPS = "https://chat.padiem.net"
CHAT_LOOPBACK = "http://127.0.0.1:8798"
QUEUE_LOOPBACK = "http://127.0.0.1:8797"

_EDGE_MODULE = (Path(__file__).resolve().parents[3]
                / "packages" / "padiem-control-plane" / "com2_edge_proof.py")
_spec = importlib.util.spec_from_file_location("_edge_proof_under_test", _EDGE_MODULE)
assert _spec and _spec.loader
edge = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = edge
_spec.loader.exec_module(edge)


class _StubPort:
    def read_bytes(self, *, node_ref, file_path, timeout_seconds):
        del node_ref, file_path, timeout_seconds
        return b""


class _Response:
    status = 200

    def read(self):
        return b'{"ok":true}'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _RecordingOpener:
    """Stands in for the opener and keeps the requests the executor signed."""

    def __init__(self, record):
        self.record = record

    def open(self, request, timeout=None):
        self.record.append(request)
        return _Response()


def _executor(**kwargs):
    return OracleMeshExecutor(read_port=_StubPort(), channel_secret=SECRET, **kwargs)


def _posted(executor, paths):
    record = []
    with patch("urllib.request.build_opener",
               side_effect=lambda *a, **k: _RecordingOpener(record)):
        for path in paths:
            executor._https_post(path, {})
    return record


def _lower(request):
    # urllib capitalizes what it sends; the ASGI scope hands the server lowercase
    # names, which is the shape the verifier reads.
    return {name.lower(): value for name, value in request.headers.items()}


class TestOriginRule(unittest.TestCase):
    def test_a_loopback_chat_origin_is_accepted(self):
        executor = _executor(chat_origin=CHAT_LOOPBACK, edge_secret=EDGE_SECRET)
        self.assertEqual(executor._origin_for(RESULT_PATH), CHAT_LOOPBACK)

    def test_a_loopback_chat_origin_without_edge_material_is_refused(self):
        with self.assertRaises(ContractError):
            _executor(chat_origin=CHAT_LOOPBACK)

    def test_any_other_http_origin_stays_refused(self):
        for origin in ("http://chat.padiem.net", "http://10.0.0.8:8798",
                       "http://localhost.local:8798", "http://127.0.0.1:8798/prefix"):
            with self.subTest(origin=origin), self.assertRaises(ContractError):
                _executor(chat_origin=origin, edge_secret=EDGE_SECRET)

    def test_the_queue_leg_is_unaffected_by_the_chat_origin_rule(self):
        executor = _executor(chat_origin=CHAT_HTTPS, queue_origin=QUEUE_LOOPBACK)
        self.assertEqual(executor._leg_for(POLL_PATH), "queue")


class TestEdgeHeaders(unittest.TestCase):
    def test_a_loopback_chat_leg_carries_the_four_headers_once_each(self):
        executor = _executor(chat_origin=CHAT_LOOPBACK, queue_origin=QUEUE_LOOPBACK,
                             edge_secret=EDGE_SECRET)
        record = _posted(executor, [RESULT_PATH])
        headers = _lower(record[0])
        for name in EDGE_HEADERS:
            self.assertEqual(list(headers).count(name), 1, name)

    def test_the_loopback_queue_leg_still_carries_none_of_them(self):
        executor = _executor(chat_origin=CHAT_LOOPBACK, queue_origin=QUEUE_LOOPBACK,
                             edge_secret=EDGE_SECRET)
        record = _posted(executor, [POLL_PATH])
        headers = _lower(record[0])
        for name in EDGE_HEADERS:
            self.assertNotIn(name, headers, name)

    def test_the_public_https_origin_carries_nothing_new(self):
        executor = _executor(chat_origin=CHAT_HTTPS, queue_origin=QUEUE_LOOPBACK)
        record = _posted(executor, [RESULT_PATH])
        headers = _lower(record[0])
        for name in EDGE_HEADERS:
            self.assertNotIn(name, headers, name)


class TestAgainstTheDeployedVerifier(unittest.TestCase):
    """The proof is only worth what Chat's own verifier says it is worth."""

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.verifier_db = str(Path(self.workspace.name) / "replay.db")

    def _verifier(self):
        return edge.EdgeProofVerifier(EDGE_SECRET, self.verifier_db)

    def test_the_headers_the_executor_produced_pass_the_real_verifier(self):
        executor = _executor(chat_origin=CHAT_LOOPBACK, edge_secret=EDGE_SECRET)
        record = _posted(executor, [RESULT_PATH])
        self.assertTrue(
            self._verifier().verify(method="POST", path=RESULT_PATH,
                                    headers=_lower(record[0])))

    def test_a_replay_of_that_request_id_is_refused_and_the_next_post_signs_a_new_one(
            self,):
        executor = _executor(chat_origin=CHAT_LOOPBACK, edge_secret=EDGE_SECRET)
        first, second = _posted(executor, [RESULT_PATH, RESULT_PATH])
        verifier = self._verifier()
        headers = _lower(first)
        self.assertTrue(verifier.verify(method="POST", path=RESULT_PATH, headers=headers))
        self.assertFalse(verifier.verify(method="POST", path=RESULT_PATH, headers=headers))
        self.assertTrue(verifier.verify(method="POST", path=RESULT_PATH,
                                        headers=_lower(second)))

    def test_a_different_secret_is_refused(self):
        forged = edge_proof_headers("another-edge-secret-" + "w" * 35,
                                    method="POST", path=RESULT_PATH)
        self.assertFalse(self._verifier().verify(
            method="POST", path=RESULT_PATH, headers=forged))


class TestConnectionPiecesAreBuiltOnce(unittest.TestCase):
    def test_two_posts_build_one_opener(self):
        executor = _executor(chat_origin=CHAT_LOOPBACK, edge_secret=EDGE_SECRET)
        builds = []

        def _counting_builder(*args, **kwargs):
            builds.append(args)
            return _RecordingOpener([])

        with patch("urllib.request.build_opener", side_effect=_counting_builder):
            executor._https_post(POLL_PATH, {})
            executor._https_post(RESULT_PATH, {})
        self.assertEqual(len(builds), 1)
        self.assertIsNotNone(executor._ssl_context)


if __name__ == "__main__":
    unittest.main()
