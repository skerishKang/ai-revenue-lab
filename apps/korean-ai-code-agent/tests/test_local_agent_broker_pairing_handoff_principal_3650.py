"""#3650 — the non-Production host has no hardcoded browser principal.

The #3140 evidence host used to speak for ``account.1`` / ``workspace.1`` no
matter which authenticated test account the run was built around, so a real
Chat session could never mint a challenge in its own scope (canonical
``scope_mismatch``). The principal is now injected at host startup and there is
deliberately no fallback: no injection, no host.
"""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from unittest import mock

from kagent.contracts import ContractError
from kagent.local_agent_broker_pairing_handoff_entry import (
    PRINCIPAL_ACCOUNT_ENV,
    PRINCIPAL_WORKSPACE_ENV,
    LoopbackPairingBroker,
    main,
    principal_from_env,
)

ACCOUNT = "owner-3650@example.test"
WORKSPACE = "workspace.3650.e2e"


class BrokerPrincipalInjectionTest(unittest.TestCase):
    def test_broker_requires_an_explicit_principal(self):
        with self.assertRaises(TypeError):
            LoopbackPairingBroker()  # type: ignore[call-arg]

    def test_broker_refuses_malformed_principals(self):
        cases = [
            ("", WORKSPACE),
            (ACCOUNT, ""),
            ("bad principal", WORKSPACE),
            (ACCOUNT, "../escape"),
            (None, WORKSPACE),
            (ACCOUNT, 123),
        ]
        for account, workspace in cases:
            with self.subTest(account=account, workspace=workspace):
                with self.assertRaises((ContractError, TypeError)):
                    LoopbackPairingBroker(account_ref=account, workspace_ref=workspace)

    def test_injected_principal_drives_every_web_leg(self):
        broker = LoopbackPairingBroker(account_ref=ACCOUNT, workspace_ref=WORKSPACE)

        self.assertEqual(broker.account_ref, ACCOUNT)
        self.assertEqual(broker.workspace_ref, WORKSPACE)
        self.assertEqual(broker._device_auth.account_ref, ACCOUNT)
        self.assertEqual(broker._device_auth.workspace_ref, WORKSPACE)
        self.assertEqual(broker._authenticated_device_auth.account_ref, ACCOUNT)
        self.assertEqual(broker._authenticated_device_auth.workspace_ref, WORKSPACE)

        issued = broker.web_issue_challenge(now=datetime.now(timezone.utc).replace(microsecond=0))
        # The canonical mint speaks for the host's own injected principal only.
        self.assertIs(issued["ok"], True)
        self.assertEqual(issued["challenge"]["account_ref"], ACCOUNT)
        self.assertEqual(issued["challenge"]["workspace_ref"], WORKSPACE)
        self.assertEqual(len(issued["pairing_code"]), 32)

    def test_principal_from_env_requires_both_values(self):
        with self.assertRaises(ContractError):
            principal_from_env({})
        with self.assertRaises(ContractError):
            principal_from_env({PRINCIPAL_ACCOUNT_ENV: ACCOUNT})
        with self.assertRaises(ContractError):
            principal_from_env(
                {PRINCIPAL_ACCOUNT_ENV: "bad principal", PRINCIPAL_WORKSPACE_ENV: WORKSPACE}
            )

        account, workspace = principal_from_env(
            {PRINCIPAL_ACCOUNT_ENV: ACCOUNT, PRINCIPAL_WORKSPACE_ENV: WORKSPACE}
        )
        self.assertEqual((account, workspace), (ACCOUNT, WORKSPACE))


class _OwnerHttpServer:
    """A minimal loopback owner around one broker's canonical handler."""

    def __init__(self, broker: LoopbackPairingBroker) -> None:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — stdlib surface
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                path = urllib.parse.urlparse(self.path).path
                route = path if path.startswith("/v1/") else f"/{path.lstrip('/')}"
                body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                response = broker.handler.handle(
                    method="POST",
                    route=route,
                    content_type="application/json",
                    body=body,
                    auth=broker._authenticated_device_auth,
                )
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(json.dumps(response.body).encode())))
                self.end_headers()
                self.wfile.write(json.dumps(response.body).encode("utf-8"))

            def log_message(self, *args) -> None:
                return

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.server = server
        self.url = f"http://127.0.0.1:{server.server_address[1]}"
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        return False


def _redeem_through_canonical_client(
    broker: LoopbackPairingBroker,
    tmp_path: str,
    *,
    pairing_code: str,
    challenge_id: str,
    device_id: str,
):
    """Redeem the carried handoff through the real #3095 pairing client."""

    from kagent.local_agent_broker_pairing_client import LocalAgentBrokerPairingClient
    from kagent.local_agent_pairing_handoff import LocalAgentPairingHandoffRunner
    from kagent.local_agent_secure_transport import (
        OutboundBrokerEndpoint,
        OutboundTransportConfig,
        OutboundTransportMode,
        ProtectedFileDeviceCredentialStore,
    )
    from padiem_control_plane.local_agent_broker_http import TrustedLocalAgentHttpAuthContext

    class _DeterministicProtectedData:
        """The SHA-256 stream DPAPI double the #3140/#3590 lanes use."""

        @staticmethod
        def _stream(entropy: bytes, length: int) -> bytes:
            out = b""
            block = 0
            while len(out) < length:
                out += hashlib.sha256(entropy + block.to_bytes(4, "big")).digest()
                block += 1
            return out[:length]

        def protect(self, credential: bytes, *, entropy: bytes) -> bytes:
            return bytes(a ^ b for a, b in zip(credential, self._stream(entropy, len(credential))))

        def unprotect(self, protected: bytes, *, entropy: bytes) -> bytes:
            return self.protect(protected, entropy=entropy)

    class _DevicePort:
        """The desktop's port shape: unauthenticated on redeem only."""

        def post(self, *, config, operation, payload, timeout_seconds):
            del config, timeout_seconds
            route = f"/{operation.value}"
            response = broker.handler.handle(
                method="POST",
                route=route,
                content_type="application/json",
                body=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                auth=TrustedLocalAgentHttpAuthContext(
                    principal_ref=device_id,
                    account_ref=broker.account_ref,
                    workspace_ref=broker.workspace_ref,
                    authenticated=route != "/v1/broker/pairings/redeem",
                    tls_verified=True,
                ),
            )
            return json.loads(json.dumps(response.body))

    config = OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_3650",
            url="https://broker.3650.principal.test:443/broker",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=30,
        poll_timeout_seconds=15,
        max_response_bytes=262_144,
        tls_required=True,
        public_inbound_port=False,
    )
    credentials = ProtectedFileDeviceCredentialStore(
        base_dir=os.path.join(str(tmp_path), "credentials"),
        protected_data=_DeterministicProtectedData(),
    )
    runner = LocalAgentPairingHandoffRunner(
        config=config,
        credential_store=credentials,
        client=LocalAgentBrokerPairingClient(
            config=config,
            credential_store=credentials,
            request_port=_DevicePort(),
        ),
    )
    return runner.redeem_handoff(
        pairing_code=pairing_code,
        challenge_id=challenge_id,
        device_id=device_id,
        correlation_ref="3650-principal-scope",
        now=broker.clock.now,
    )


class IssueHandoffAgainstRunningOwnerTest(unittest.TestCase):
    def test_issue_handoff_mints_at_the_running_owner_for_the_injected_principal(self):
        broker = LoopbackPairingBroker(account_ref=ACCOUNT, workspace_ref=WORKSPACE)
        with _OwnerHttpServer(broker) as owner:
            with tempfile.TemporaryDirectory() as tmp:
                env = {
                    PRINCIPAL_ACCOUNT_ENV: ACCOUNT,
                    PRINCIPAL_WORKSPACE_ENV: WORKSPACE,
                    "PADIEM_AGENT_BROKER_URL": owner.url,
                }
                out = io.StringIO()
                with mock.patch.dict(os.environ, env, clear=False):
                    with redirect_stdout(out):
                        exit_code = main(["--issue-handoff"])
                self.assertEqual(exit_code, 0)
                emitted = json.loads(out.getvalue().strip().splitlines()[-1])
                self.assertEqual(len(emitted["pairing_code"]), 32)
                self.assertTrue(emitted["challenge_id"])

                # The carried handoff redeems through the real canonical client,
                # and the binding registered at the canonical authority speaks
                # for the INJECTED test principal — not account.1, not a default.
                result = _redeem_through_canonical_client(
                    broker,
                    tmp,
                    pairing_code=emitted["pairing_code"],
                    challenge_id=emitted["challenge_id"],
                    device_id="device.3650.e2e",
                )
                self.assertEqual(result.binding_state, "paired_offline")
                from padiem_control_plane.local_agent_broker_state import (
                    LocalAgentBrokerStateSnapshot,
                )

                registered = [
                    binding
                    for binding in LocalAgentBrokerStateSnapshot.capture(broker.authority).bindings
                    if binding.device_id == "device.3650.e2e"
                ]
                self.assertEqual(len(registered), 1)
                self.assertEqual(registered[0].account_ref, ACCOUNT)
                self.assertEqual(registered[0].workspace_ref, WORKSPACE)

    def test_issue_handoff_refuses_when_the_owner_scope_differs(self):
        broker = LoopbackPairingBroker(account_ref=ACCOUNT, workspace_ref=WORKSPACE)
        with _OwnerHttpServer(broker) as owner:
            # A principal the owner was NOT started for: the canonical mint must
            # refuse with the scope mismatch, and the CLI reports it bounded.
            env = {
                PRINCIPAL_ACCOUNT_ENV: "other-3650@example.test",
                PRINCIPAL_WORKSPACE_ENV: WORKSPACE,
                "PADIEM_AGENT_BROKER_URL": owner.url,
            }
            err = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False):
                with redirect_stderr(err):
                    exit_code = main(["--issue-handoff"])
            self.assertEqual(exit_code, 1)
            captured = json.loads(err.getvalue().strip().splitlines()[-1])
            self.assertIs(captured["ok"], False)
            self.assertEqual(captured["error"], "challenge_refused")

    def test_issue_handoff_refuses_to_start_without_an_injected_principal(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(PRINCIPAL_ACCOUNT_ENV, None)
            os.environ.pop(PRINCIPAL_WORKSPACE_ENV, None)
            with redirect_stderr(err):
                exit_code = main(["--issue-handoff"])
        self.assertEqual(exit_code, 2)
        captured = json.loads(err.getvalue().strip().splitlines()[-1])
        self.assertIs(captured["ok"], False)
        self.assertEqual(captured["error"], "principal_not_injected")
        self.assertEqual(captured["required"], [PRINCIPAL_ACCOUNT_ENV, PRINCIPAL_WORKSPACE_ENV])


class CreateOwnerServerTest(unittest.TestCase):
    """The extracted owner server must keep the #3650 scope rules over a
    real socket, so the packaged serve() and any evidence composition built
    from the same function cannot drift apart."""

    def test_owner_server_serves_and_scope_mismatch_refuses_over_the_wire(self):
        from kagent.local_agent_broker_pairing_handoff_entry import (
            create_owner_server,
        )

        broker = LoopbackPairingBroker(account_ref=ACCOUNT, workspace_ref=WORKSPACE)
        server, url = create_owner_server(broker)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def post(path: str, payload: dict) -> tuple[int, dict]:
                body = json.dumps(payload, sort_keys=True).encode("utf-8")
                request = urllib.request.Request(
                    f"{url}{path}",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        return response.status, json.loads(response.read())
                except urllib.error.HTTPError as exc:
                    return exc.code, json.loads(exc.read())

            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            status, issued = post(
                "/v1/broker/pairings/challenge",
                {"account_ref": ACCOUNT, "workspace_ref": WORKSPACE, "now": now, "ttl_seconds": 300},
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(issued["pairing_code"]), 32)

            # A caller-asserted principal the host was not started for is
            # refused on the wire, not merely at the CLI boundary.
            status, refused = post(
                "/v1/broker/pairings/challenge",
                {
                    "account_ref": "other-3650@example.test",
                    "workspace_ref": WORKSPACE,
                    "now": now,
                    "ttl_seconds": 300,
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(refused["error"]["code"], "local_agent_http_scope_mismatch")

            # The single-use rule holds for this host too: the web-issued
            # code redeems once, and a second redeem of the same code is
            # refused by the canonical authority.
            pairing_code = issued["pairing_code"]
            challenge_id = issued["challenge"]["challenge_id"]
            with tempfile.TemporaryDirectory() as tmp:
                first = _redeem_through_canonical_client(
                    broker,
                    tmp,
                    pairing_code=pairing_code,
                    challenge_id=challenge_id,
                    device_id="device.3650.wire",
                )
                self.assertEqual(first.binding_state, "paired_offline")
                with tempfile.TemporaryDirectory() as tmp2:
                    with self.assertRaises(ContractError):
                        _redeem_through_canonical_client(
                            broker,
                            tmp2,
                            pairing_code=pairing_code,
                            challenge_id=challenge_id,
                            device_id="device.3650.wire",
                        )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
