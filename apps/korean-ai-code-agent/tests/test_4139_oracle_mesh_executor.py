"""#4139 — the executor factory must run the official client for real.

One focused check goes through ``make_oracle_mesh_executor`` so the actual
factory-built read port is exercised: the operator credential reaches the child
on stdin, the argv carries only the public marker, and the invocation is
UTF-8 text. No MeshCentral server and no live credential are involved.
"""
from __future__ import annotations

import hashlib
import io
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from kagent.contracts import ContractError
from kagent.local_agent_meshcentral_private_reader import (
    MeshCentralCliFileReadPort, MeshCentralReadRefused, _PASSWORD_MARKER,
)
from kagent.local_agent_oracle_mesh_executor import (
    BUSY_PATH, CANCEL_PATH, CHANNEL_HEADER, CHANNEL_SOCKET_TIMEOUT_SECONDS,
    CHANNEL_STALL_SECONDS, LEASE_RENEW_PATH, POLL_PATH, PRODUCT_USER_AGENT, RESULT_PATH,
    OracleMeshChannelRefused, OracleMeshDispatch, OracleMeshExecutor,
    MAX_RESULT_REJECTIONS, OracleMeshExecutionOutcome, make_oracle_mesh_executor,
)

SECRET = "deployment-channel-secret-value-261017"
PASSWORD = "op3rator-meshtr0ll-secret"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
FILE_PATH = "C:\\ProgramData\\Padiem\\report.txt"


class _StubPort:
    """Stand-in read port; the channel transport is what is under test here."""

    def read_bytes(self, *, node_ref, file_path, timeout_seconds):  # noqa: D102
        del node_ref, file_path, timeout_seconds
        return b""


class _RecordingStdin:
    """Records the one credential write even after the real close."""

    def __init__(self):
        self.value = ""
        self.closed = False

    def write(self, text):
        self.value += text

    def close(self):
        self.closed = True


class ChannelTransportHeaderTests(unittest.TestCase):
    """Every channel leg must identify the product, never Python-urllib.

    Cloudflare's Browser Integrity Check refuses the default urllib signature
    with error 1010 *before* the channel secret is evaluated, so the first-party
    product token has to ride on the request while the channel auth header and
    the existing redirect refusal stay exactly as they were.
    """

    class _Response:
        status = 200

        def read(self, _n=-1):  # noqa: D102
            return b'{"ok": true, "dispatch": null}'

        def __enter__(self):  # noqa: D102
            return self

        def __exit__(self, *exc):  # noqa: D102
            return False

    def _executor(self) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubPort(),
        )

    def test_poll_leg_sends_the_product_user_agent_and_keeps_channel_auth(self):
        executor = self._executor()
        sent: dict = {}

        class _Opener:
            def open(self, request, timeout=None):  # noqa: D102
                del timeout
                sent["headers"] = dict(request.header_items())
                return ChannelTransportHeaderTests._Response()

        with patch("urllib.request.build_opener", return_value=_Opener()):
            status, data = executor._https_post(POLL_PATH, None)

        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        lowered = {name.lower(): value for name, value in sent["headers"].items()}
        self.assertEqual(lowered["user-agent"], PRODUCT_USER_AGENT)
        self.assertNotIn("python-urllib", lowered["user-agent"].lower())
        # Channel auth and content negotiation are untouched by the fix.
        self.assertEqual(lowered[CHANNEL_HEADER.lower()], SECRET)
        self.assertEqual(lowered["content-type"], "application/json")
        self.assertEqual(lowered["accept"], "application/json")


class ChannelSocketDeadlineTests(unittest.TestCase):
    """#4139: the channel gets a socket deadline; a running command keeps none.

    Measured 2026-10-28: one executor met a half-dead TCP path on a single poll and
    blocked for 5 h 36 m with no log line at all (last send and last receive 20,125 s
    apart, 1,971 of 3,099 bytes retransmitted). Nothing was claimable on any PC during
    that time, and the operator saw it as "the PC lane is down". A poll may never own
    the loop, while a command still runs until the console answers by owner decision.
    """

    class _RecordingPort:
        def __init__(self):
            self.calls: list[dict] = []

        def read_bytes(self, **call):  # noqa: D102
            self.calls.append(dict(call))
            return b"ok"

    def _executor(self, **kwargs) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubPort(),
            **kwargs,
        )

    def _opener(self, record: dict, outcome: str = "answer"):
        class _Opener:
            def open(self, request, timeout=None):  # noqa: D102
                record["timeout"] = timeout
                if outcome == "dead":
                    raise OSError("connection reset by peer")
                return ChannelTransportHeaderTests._Response()

        return _Opener()

    def test_every_channel_round_uses_the_socket_deadline(self):
        for path in (POLL_PATH, RESULT_PATH):
            seen: dict = {}
            with patch("urllib.request.build_opener", return_value=self._opener(seen)):
                self._executor()._https_post(path, None)
            self.assertEqual(seen["timeout"], CHANNEL_SOCKET_TIMEOUT_SECONDS, path)

    def test_the_deadline_is_no_ceiling_on_the_work_itself(self):
        port = self._RecordingPort()
        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net", channel_secret=SECRET,
            read_port=port, timeout_seconds=None, channel_timeout_seconds=7,
        )
        executor._execute_read(OracleMeshDispatch(
            dispatch_id="dsp-1", nonce="n" * 32, node_ref=NODE,
            file_path=FILE_PATH, command_id="cmd-1", run_id="run-1",
        ))
        self.assertIsNone(port.calls[0]["timeout_seconds"])

        seen: dict = {}
        with patch("urllib.request.build_opener", return_value=self._opener(seen)):
            executor._https_post(POLL_PATH, None)
        self.assertEqual(seen["timeout"], 7)

    def test_a_round_that_never_completes_is_the_only_thing_the_watchdog_stops(self):
        executor = self._executor()
        self.assertFalse(executor.channel_stalled())
        self.assertFalse(executor.watchdog_tick())

        executor._last_round_at = time.monotonic() - CHANNEL_STALL_SECONDS - 1
        self.assertTrue(executor.watchdog_tick())

    def test_a_round_that_answers_badly_is_still_a_round(self):
        executor = self._executor()
        executor._last_round_at = time.monotonic() - CHANNEL_STALL_SECONDS - 1
        seen: dict = {}
        with patch("urllib.request.build_opener",
                   return_value=self._opener(seen, outcome="dead")):
            with self.assertRaises(OracleMeshChannelRefused):
                executor._https_post(POLL_PATH, None)
        self.assertFalse(executor.channel_stalled())

    def test_the_operational_composition_keeps_the_deadline_off_the_dispatch_cap(self):
        executor = make_oracle_mesh_executor(
            chat_origin="https://chat.padiem.net", channel_secret=SECRET,
            meshctrl_js="/opt/padiem/meshcentral/node_modules/meshcentral/meshctrl.js",
            login_user="padiemadmin", password_provider=lambda: PASSWORD,
            channel_timeout_seconds=11,
        )
        self.assertEqual(executor._channel_timeout, 11)
        self.assertIsNone(executor._timeout)

    def test_an_unusable_deadline_refuses_to_start(self):
        for bad in (0, -1, 901, True, "90", None):
            with self.assertRaises(ContractError):
                self._executor(channel_timeout_seconds=bad)


class FactoryRunnerTests(unittest.TestCase):
    def _factory(self) -> OracleMeshExecutor:
        work = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="oracle_exec_4139_")
        ))
        return make_oracle_mesh_executor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            meshctrl_js=str(work / "meshctrl.js"),
            login_user="padiemadmin",
            password_provider=lambda: PASSWORD,
            work_dir=str(work),
        )

    def test_factory_builds_the_real_official_client_port(self):
        executor = self._factory()
        port = executor._read_port
        self.assertIsInstance(port, MeshCentralCliFileReadPort)
        self.assertTrue(port._meshctrl_js.endswith("meshctrl.js"))

    class _FakePopen:
        """A download child that stages the target and exits on first poll."""

        def __init__(self, argv, *, staged=b"", returncode=0, **kwargs):
            self.argv = list(argv)
            self.kwargs = kwargs
            self.stdin = _RecordingStdin()
            self.returncode = returncode
            self.terminated = False
            self.target = argv[argv.index("--target") + 1]
            if staged:
                Path(self.target).write_bytes(staged)

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.terminated = True
            self.returncode = -9

        def wait(self, timeout=None):
            del timeout
            return self.returncode

    def test_credential_reaches_the_child_on_stdin_and_never_on_argv(self):
        executor = self._factory()
        created: list = []

        def fake_popen(argv, **kwargs):
            process = self._FakePopen(
                argv, staged=b"PADIEM MESH\r\nEND\n", **kwargs,
            )
            created.append(process)
            return process

        with patch("subprocess.Popen", side_effect=fake_popen):
            body = executor._read_port.read_bytes(
                node_ref=NODE, file_path=FILE_PATH, timeout_seconds=30,
            )

        self.assertEqual(body, b"PADIEM MESH\r\nEND\n")
        self.assertEqual(len(created), 1)
        process = created[0]
        # The credential is delivered as UTF-8 text on stdin, once.
        self.assertEqual(process.stdin.value, PASSWORD + "\n")
        self.assertIs(process.kwargs.get("stdin"), subprocess.PIPE)
        self.assertIs(process.kwargs.get("stdout"), subprocess.DEVNULL)
        self.assertIs(process.kwargs.get("stderr"), subprocess.DEVNULL)
        self.assertIs(process.kwargs.get("text"), True)
        self.assertEqual(process.kwargs.get("encoding"), "utf-8")
        # The argv carries the public marker, never the credential.
        argv = process.argv
        self.assertIn(_PASSWORD_MARKER, argv)
        self.assertNotIn(PASSWORD, argv)
        self.assertNotIn(PASSWORD + "\n", argv)
        for token in argv:
            self.assertNotIn(PASSWORD, token)
        self.assertFalse(Path(process.target).exists())

    def test_failed_client_run_still_refuses_without_leaking(self):
        executor = self._factory()
        created: list = []

        def fake_popen(argv, **kwargs):
            process = self._FakePopen(argv, returncode=1, **kwargs)
            created.append(process)
            return process

        with patch("subprocess.Popen", side_effect=fake_popen):
            with self.assertRaises(MeshCentralReadRefused):
                executor._read_port.read_bytes(
                    node_ref=NODE, file_path=FILE_PATH, timeout_seconds=30,
                )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].stdin.value, PASSWORD + "\n")
        self.assertFalse(Path(created[0].target).exists())

    def test_no_input_means_no_forced_pipe(self):
        """A runner call without input must not fabricate an empty stdin write."""
        executor = self._factory()
        captured: dict = {}

        def fake_run(argv, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, "", "")

        runner = None
        port = executor._read_port
        # Reach the factory's own runner through the port's stored runner.
        runner = getattr(port, "_command_runner")
        assert callable(runner)
        with patch("subprocess.run", side_effect=fake_run):
            runner(["node", "--version"], timeout=5)
        self.assertNotIn("input", captured)
        self.assertIs(captured["text"], True)
        self.assertEqual(captured["encoding"], "utf-8")


class EntrypointTests(unittest.TestCase):
    def test_main_refuses_to_start_without_required_configuration(self):
        from kagent.local_agent_oracle_mesh_executor import main

        import io
        import contextlib

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main({"ORACLE_MESH_CHAT_ORIGIN": "https://chat.padiem.net"})
        self.assertEqual(code, 2)
        self.assertIn("refused to start", err.getvalue())
        self.assertNotIn(SECRET, err.getvalue())

    def test_main_refuses_a_non_https_origin_before_reading_anything(self):
        from kagent.local_agent_oracle_mesh_executor import main

        import io
        import contextlib

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main({
                "ORACLE_MESH_CHAT_ORIGIN": "http://chat.padiem.net",
                "ORACLE_MESH_CHANNEL_SECRET_FILE": "/nonexistent/secret",
                "ORACLE_MESH_MESHCTRL_JS": "/nonexistent/meshctrl.js",
                "ORACLE_MESH_LOGIN_USER": "padiemadmin",
                "ORACLE_MESH_PASSWORD_FILE": "/nonexistent/password",
            })
        self.assertEqual(code, 2)


class QueueChannelOriginTests(unittest.TestCase):
    """#5881 follow-on: the claim lane may be served on this host's loopback, nowhere else.

    The 컴2 PC queue listens on 127.0.0.1:8797 and the executor runs on that host, so the
    queue leg can be a same-host call with no TLS in front of it. That relaxation is
    confined to the queue field: the Worker's own origin still has to be https, because
    its traffic can leave the machine, and the secret travels in the same header checked
    the same way by whichever server answers.
    """

    def _queue_origin(self, origin: str) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net", channel_secret=SECRET,
            read_port=_StubPort(), queue_origin=origin,
        )

    def test_a_loopback_queue_origin_is_accepted_as_written(self):
        for origin in ("http://127.0.0.1:8797", "http://localhost:8797",
                       "http://[::1]:8797"):
            with self.subTest(origin=origin):
                self.assertEqual(self._queue_origin(origin)._queue_origin, origin)

    def test_the_worker_origin_still_refuses_http_even_on_loopback(self):
        for origin in ("http://127.0.0.1:8797", "http://localhost:8797",
                       "http://chat.padiem.net", "ftp://127.0.0.1", "//127.0.0.1:8797"):
            with self.subTest(origin=origin):
                with self.assertRaises(ContractError):
                    OracleMeshExecutor(chat_origin=origin, channel_secret=SECRET,
                                       read_port=_StubPort())

    def test_a_queue_origin_that_could_leave_this_host_is_refused(self):
        for origin in (
            "http://queue.example",
            "http://localhost.evil.example",
            "http://127.0.0.1.attacker.example",
            "http://127.0.0.1:8797@evil.example",
            "http://[::1].evil.example",
            "ftp://127.0.0.1",
            "//127.0.0.1:8797",
            "https://",
        ):
            with self.subTest(origin=origin):
                with self.assertRaises(ContractError):
                    self._queue_origin(origin)

    def test_the_bare_origin_rule_applies_to_the_queue_leg_as_to_the_worker_leg(self):
        for origin in ("http://127.0.0.1:8797/", "https://queue.example/"):
            with self.subTest(origin=origin):
                with self.assertRaises(ContractError):
                    self._queue_origin(origin)


class QueueOriginLaneTests(unittest.TestCase):
    """#5881 follow-on: the claim lane and the answer are asked at two servers.

    The queue answers poll, renew, cancel and busy on this host's loopback. It does not
    serve the result submission — framing the answer and writing the conversation rows
    stay in the Chat Worker — so a configured queue origin must redirect the claim legs
    and leave the submission exactly where it is. Unset, every leg goes to the Worker:
    that is the state the lane ran in before the queue, and the rollback.
    """

    QUEUE = "http://127.0.0.1:8797"
    CHAT = "https://chat.padiem.net"

    def _executor(self, **kwargs) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin=self.CHAT, channel_secret=SECRET, read_port=_StubPort(), **kwargs)

    def _urls(self, executor: OracleMeshExecutor, *paths) -> list[str]:
        asked: list[str] = []

        class _Opener:
            def open(self, request, timeout=None):  # noqa: D102
                del timeout
                asked.append(request.full_url)
                return ChannelTransportHeaderTests._Response()

        with patch("urllib.request.build_opener", return_value=_Opener()):
            for path in paths:
                executor._https_post(path, None)
        return asked

    def test_the_claim_legs_go_to_the_queue_and_the_answer_to_the_worker(self):
        urls = self._urls(self._executor(queue_origin=self.QUEUE),
                          POLL_PATH, LEASE_RENEW_PATH, CANCEL_PATH, BUSY_PATH, RESULT_PATH)
        self.assertEqual(urls, [
            self.QUEUE + POLL_PATH, self.QUEUE + LEASE_RENEW_PATH,
            self.QUEUE + CANCEL_PATH, self.QUEUE + BUSY_PATH,
            self.CHAT + RESULT_PATH,
        ])

    def test_without_a_queue_everything_still_goes_to_the_worker(self):
        paths = (POLL_PATH, LEASE_RENEW_PATH, CANCEL_PATH, BUSY_PATH, RESULT_PATH)
        self.assertEqual(self._urls(self._executor(), *paths),
                         [self.CHAT + path for path in paths])

    def test_an_empty_queue_origin_is_the_worker_lane_not_a_broken_one(self):
        for blank in (None, ""):
            with self.subTest(queue_origin=blank):
                executor = self._executor(queue_origin=blank)
                self.assertIsNone(executor._queue_origin)
                self.assertEqual(self._urls(executor, POLL_PATH), [self.CHAT + POLL_PATH])

    def test_the_secret_travels_to_the_queue_exactly_as_it_travels_to_the_worker(self):
        sent: list[dict] = []

        class _Opener:
            def open(self, request, timeout=None):  # noqa: D102
                del timeout
                sent.append(dict(request.header_items()))
                return ChannelTransportHeaderTests._Response()

        executor = self._executor(queue_origin=self.QUEUE)
        with patch("urllib.request.build_opener", return_value=_Opener()):
            executor._https_post(POLL_PATH, None)
            executor._https_post(RESULT_PATH, None)

        for headers in sent:
            lowered = {name.lower(): value for name, value in headers.items()}
            self.assertEqual(lowered[CHANNEL_HEADER.lower()], SECRET)
            self.assertEqual(lowered["user-agent"], PRODUCT_USER_AGENT)


class ResultSubmitTests(unittest.TestCase):
    """0-byte outcomes carry the canonical empty digest; refusals keep the hold."""

    def _executor(self, transport) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubPort(),
            transport=transport,
        )

    def _dispatch(self) -> OracleMeshDispatch:
        return OracleMeshDispatch(
            dispatch_id="dsp-1", nonce="n" * 32, node_ref=NODE,
            file_path=FILE_PATH, command_id="cmd-1", run_id="run-1",
        )

    def test_empty_body_submits_the_canonical_empty_digest(self):
        seen: dict = {}

        def transport(path, payload):
            seen["path"] = path
            seen["payload"] = dict(payload)
            return 200, {"ok": True, "status": "failed"}

        executor = self._executor(transport)
        outcome = OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=b"")
        result = executor.submit(self._dispatch(), outcome)

        self.assertTrue(result.get("ok"))
        self.assertEqual(seen["path"], RESULT_PATH)
        self.assertEqual(seen["payload"]["content_bytes"], 0)
        self.assertEqual(
            seen["payload"]["content_sha256"], hashlib.sha256(b"").hexdigest()
        )

    def test_dispatch_rejection_is_retried_bounded_then_quarantined(self):
        # The same 409 code is also answered while the row is still an
        # unfinished received row, so the held outcome is kept for a few
        # attempts — then preserved with the cause instead of looping
        # forever or vanishing silently.
        attempts = []

        def transport(path, payload):
            attempts.append(path)
            return 409, {"ok": False, "error": {"code": "oracle_mesh_dispatch_rejected"}}

        executor = self._executor(transport)
        outcome = OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=b"")
        first = executor.submit(self._dispatch(), outcome)
        self.assertFalse(first.get("ok"))
        self.assertTrue(first.get("retryable"))
        self.assertTrue(executor.resend_pending)
        final = None
        for _ in range(MAX_RESULT_REJECTIONS + 1):
            if not executor.resend_pending:
                break
            final = executor.resend_pending_result()
        self.assertTrue(final.get("dropped"))
        self.assertTrue(final.get("quarantined"))
        self.assertEqual(final.get("status"), 409)
        self.assertFalse(executor.resend_pending)
        self.assertEqual(len(attempts), MAX_RESULT_REJECTIONS)

    def test_fingerprint_mismatch_is_quarantined_immediately(self):
        # The held bytes differ from what the server pinned first: resending
        # cannot change that, so the result is preserved with the cause on
        # the first refusal instead of looping.
        def transport(path, payload):
            return 409, {
                "ok": False, "error": {"code": "oracle_mesh_result_fingerprint_mismatch"}
            }

        executor = self._executor(transport)
        outcome = OracleMeshExecutionOutcome(termination="exited", exit_code=0, body=b"abc")
        first = executor.submit(self._dispatch(), outcome)
        self.assertFalse(first.get("ok"))
        self.assertTrue(first.get("dropped"))
        self.assertTrue(first.get("quarantined"))
        self.assertFalse(first.get("retryable"))
        self.assertFalse(executor.resend_pending)


class ClaimGateTests(unittest.TestCase):
    """#5462: a host that is not the active target must not claim.

    The failover controller hands out an epoch and this host's decision
    file says which target owns the claim. When it is not this host, the
    executor must not even ask the channel for a dispatch, so the same
    work can never be claimed by both hosts at once.
    """

    def _executor(self, gate, transport=None) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubPort(),
            transport=transport,
            claim_gate=gate,
        )

    def test_a_closed_gate_means_the_channel_is_never_polled(self):
        polled = []

        def transport(*_args, **_kwargs):
            polled.append(True)
            raise AssertionError("the channel must not be polled")

        executor = self._executor(lambda: False, transport)
        self.assertIsNone(executor.run_once())
        self.assertEqual(polled, [])

    def test_an_open_gate_polls_as_before(self):
        polled = []

        def transport(*_args, **_kwargs):
            polled.append(True)
            return 200, {"ok": True, "dispatch": None}

        executor = self._executor(lambda: True, transport)
        self.assertIsNone(executor.run_once())
        self.assertEqual(len(polled), 1)

    def test_a_non_callable_gate_is_refused(self):
        with self.assertRaises(ContractError):
            OracleMeshExecutor(
                chat_origin="https://chat.padiem.net",
                channel_secret=SECRET,
                read_port=_StubPort(),
                claim_gate="yes",
            )

    def test_a_host_without_a_gate_keeps_the_historical_behaviour(self):
        polled = []

        def transport(*_args, **_kwargs):
            polled.append(True)
            return 200, {"ok": True, "dispatch": None}

        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubPort(),
            transport=transport,
        )
        self.assertIsNone(executor.run_once())
        self.assertEqual(len(polled), 1)


class PollPresenceTests(unittest.TestCase):
    """#5553: presence rides on the existing poll, and never blocks it."""

    def _executor(self, presence_provider=None, transport=None, gate=None):
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubPort(),
            transport=transport,
            claim_gate=gate,
            presence_provider=presence_provider,
        )

    def test_the_poll_carries_the_presence_beat(self):
        seen: dict = {}

        def transport(path, payload):
            seen["path"] = path
            seen["payload"] = payload
            return 200, {"ok": True, "dispatch": None}

        executor = self._executor(
            lambda: [{"device_id": NODE, "connected": True}], transport
        )
        self.assertIsNone(executor.run_once())
        self.assertEqual(seen["path"], POLL_PATH)
        self.assertEqual(
            seen["payload"], {"presence": [{"device_id": NODE, "connected": True}]}
        )

    def test_a_failed_presence_probe_omits_the_field_and_polls(self):
        probed = []

        def broken_provider():
            probed.append(True)
            raise RuntimeError("listdevices refused")

        seen: dict = {}

        def transport(path, payload):
            seen["path"] = path
            seen["payload"] = payload
            return 200, {"ok": True, "dispatch": None}

        executor = self._executor(broken_provider, transport)
        self.assertIsNone(executor.run_once())
        self.assertEqual(probed, [True])
        # The historical body is untouched: no presence key, poll still runs.
        self.assertEqual(seen["path"], POLL_PATH)
        self.assertIsNone(seen["payload"])

    def test_an_inactive_host_polls_without_presence_at_all(self):
        polled = []
        probed = []

        def transport(*_args, **_kwargs):
            polled.append(True)
            raise AssertionError("an inactive host must not poll")

        def provider():
            probed.append(True)
            return [{"device_id": NODE, "connected": True}]

        executor = self._executor(provider, transport, gate=lambda: False)
        self.assertIsNone(executor.run_once())
        self.assertEqual(polled, [])
        self.assertEqual(probed, [])



class MultiplePresenceEntrypointTests(unittest.TestCase):
    def _beats(self, configured, refused=False):
        import kagent.local_agent_oracle_mesh_executor as entry
        import kagent.local_agent_mesh_failover as failover
        class Stop(Exception): pass
        captured = {}
        def factory(**kwargs):
            captured["provider"] = kwargs["presence_provider"]
            raise Stop()
        class Presence:
            def __init__(self, **kwargs): pass
            def is_connected(self, device): return device.endswith("1")
        env = {"MESH_FAILOVER_DEVICE_ID": configured, "ORACLE_MESH_PASSWORD_FILE": "fake",
               "ORACLE_MESH_CHANNEL_SECRET_FILE": "fake", "ORACLE_MESH_MESHCTRL_JS": "fake",
               "ORACLE_MESH_LOGIN_USER": "synthetic", "ORACLE_MESH_CHAT_ORIGIN": "https://chat.example.test"}
        with patch.object(entry, "deployment_secret_password_provider", return_value=lambda: "fake"), \
             patch.object(entry, "_read_secret_file", return_value=SECRET), \
             patch.object(entry, "make_oracle_mesh_executor", side_effect=factory), \
             patch.object(failover, "MeshCentralDevicePresence", Presence):
            if refused:
                self.assertEqual(entry.main(env), 2)
                return None
            with self.assertRaises(Stop): entry.main(env)
        seen = []
        executor = OracleMeshExecutor(chat_origin="https://chat.example.test", channel_secret=SECRET,
            read_port=_StubPort(), presence_provider=captured["provider"],
            transport=lambda path, payload: (seen.append(payload) or (200, {"ok": True, "dispatch": None})))
        executor.run_once()
        return seen[0]

    def test_multiple_devices_reach_the_actual_poll_envelope(self):
        self.assertEqual(self._beats("pc@mesh+1, pc@mesh+2"), {"presence": [
            {"device_id": "pc@mesh+1", "connected": True}, {"device_id": "pc@mesh+2", "connected": False}]})

    def test_single_value_and_absent_setting_are_backward_compatible(self):
        self.assertEqual(self._beats("pc@mesh+1"), {"presence": [{"device_id": "pc@mesh+1", "connected": True}]})
        self.assertIsNone(self._beats(""))

    def test_eight_devices_are_carried_and_duplicates_do_not_duplicate_beats(self):
        self.assertEqual(len(self._beats(",".join("pc"+str(i) for i in range(8)))["presence"]), 8)
        self.assertEqual(len(self._beats("pc1,pc1")["presence"]), 1)

    def test_nine_devices_or_empty_segments_are_refused_before_factory(self):
        self.assertIsNone(self._beats(",".join("pc"+str(i) for i in range(9)), refused=True))
        self.assertIsNone(self._beats("pc1,", refused=True))


if __name__ == "__main__":
    unittest.main()
