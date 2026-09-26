"""#3095 (CLAW5) — bounded pairing handoff redemption + authenticated E2E.

Covers seam-audit G3 (the deep-link seam dropped the pairing code value, so
nothing could actually redeem) and G5 (no authenticated challenge/redemption
loop was ever executed end to end).

The E2E path uses the *existing* in-memory broker pairing authority, the
existing pinned transport config, and the existing protected credential store
port. Production pairing is never activated here.

    AUTHENTICATED_CHALLENGE_CALLER_E2E=YES
    PINNED_TLS_REDEMPTION_E2E=YES
    PRODUCTION_PAIRING_ACTIVATION=NO
    FULL_WEB_TO_DESKTOP_PAIRING_E2E=NO   (waits for #3094)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_broker_pairing_client import (
    BrokerPairingHttpsOperation,
    LocalAgentBrokerPairingClient,
    UnconfiguredLocalAgentBrokerPairingClient,
    pairing_proof_ref,
)
from kagent.local_agent_pairing import DeviceLifecycle
from kagent.local_agent_pairing_handoff import (
    LocalAgentPairingHandoffRunner,
    PairingHandoffError,
    PairingHandoffRequest,
    PairingHandoffResult,
    SHELL_PAIRING_CODE_PARAM,
    unconfigured_pairing_handoff_runner,
)
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
    StoredDeviceCredentialProjection,
)
from kagent.local_agent_server_projection import project_server_backed_online_binding
from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_http import TrustedLocalAgentHttpAuthContext
from padiem_control_plane.local_agent_broker_pairing import InMemoryBrokerPairingAuthority
from padiem_control_plane.local_agent_broker_pairing_http import (
    PAIRING_CHALLENGE_ROUTE,
    PairingEnabledLocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

BASE = datetime(2026, 9, 26, 6, 0, tzinfo=timezone.utc)
CREDENTIAL = b"pairing-handoff-3095-credential"
BROKER_PEPPER = b"control-plane-local-agent-broker-pepper"
PAIRING_PEPPER = b"control-plane-local-agent-pairing-pepper"
CODE = "0123456789abcdef0123456789abcdef"
DEVICE_ID = "device.handoff.3095"
CHALLENGE_DEVICE = "device.paired.3095"


def _config(*, url: str = "https://local-agent.padiem.net:443/broker") -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_handoff_3095",
            url=url,
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=30,
        poll_timeout_seconds=15,
        max_response_bytes=65_536,
    )


class _Clock:
    def __init__(self, now: datetime = BASE) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _CredentialStore:
    """Protected credential store double recording only non-secret facts."""

    def __init__(self) -> None:
        self.saves: list[dict] = []
        self.loads = 0
        self._saved: dict[str, bytes] = {}

    def save(self, *, binding, credential, now) -> StoredDeviceCredentialProjection:
        self.saves.append(
            {
                "binding_ref": binding.binding_ref,
                "credential_generation": binding.credential_generation,
                "credential_bytes": len(credential),
                "now": now,
            }
        )
        self._saved[binding.binding_ref] = credential
        return StoredDeviceCredentialProjection(
            binding_ref=binding.binding_ref,
            device_id=binding.device_id,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_generation=binding.credential_generation,
            credential_ref_fingerprint=hashlib.sha256(
                binding.credential_ref.encode("utf-8")
            ).hexdigest(),
            stored_at=now,
            credential_expires_at=binding.credential_expires_at,
        )

    def load(self, *, binding, now) -> bytes:
        del now
        self.loads += 1
        return self._saved[binding.binding_ref]

    def delete(self, binding_ref: str) -> None:
        self._saved.pop(binding_ref, None)


class _Resolver:
    def resolve(self, request):  # pragma: no cover - pairing never materializes a command
        raise AssertionError(request)


class _DurableState:
    """Minimal durable state port for the deployable broker HTTP handler."""

    durable = True

    def __init__(self) -> None:
        self.records: dict[str, object] = {}

    def save_session(self, record) -> None:
        self.records[record.session_id] = record

    def load_session(self, session_id: str):
        try:
            return self.records[session_id]
        except KeyError as exc:
            raise RuntimeError("session is not present in durable test state") from exc

    def record_last_seen(self, session_id: str, *, seen_at: datetime):
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


def _pairing_handler(*, nonce: str = "b" * 32):
    authority = InMemoryLocalAgentBrokerAuthority(
        pepper=BROKER_PEPPER,
        authority_ref="control-plane.local-agent-broker.v1",
    )
    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=authority,
        code_nonce_factory=lambda: nonce,
        credential_factory=lambda: CREDENTIAL,
    )
    handler = PairingEnabledLocalAgentBrokerHttpHandler(
        pairing_authority=pairing,
        rpc=LocalAgentBrokerRpcFacade(authority=authority),
        state=_DurableState(),
        material_resolver=_Resolver(),
        clock=_Clock(),
    )
    return handler, authority, pairing


def _browser_auth() -> TrustedLocalAgentHttpAuthContext:
    return TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.browser.1",
        account_ref="account.1",
        workspace_ref="workspace.1",
        authenticated=True,
        tls_verified=True,
    )


def _device_auth() -> TrustedLocalAgentHttpAuthContext:
    return TrustedLocalAgentHttpAuthContext(
        principal_ref=CHALLENGE_DEVICE,
        account_ref="account.1",
        workspace_ref="workspace.1",
        authenticated=False,
        tls_verified=True,
    )


def _issue_challenge(handler) -> dict:
    """Authenticated browser-side challenge issuance (the signed-in session)."""
    response = handler.handle(
        method="POST",
        route=PAIRING_CHALLENGE_ROUTE,
        content_type="application/json",
        body=json.dumps(
            {
                "account_ref": "account.1",
                "workspace_ref": "workspace.1",
                "now": BASE.isoformat(),
                "ttl_seconds": 300,
            }
        ).encode("utf-8"),
        auth=_browser_auth(),
    )
    assert response.status == 200
    return response.body


class _HandlerPairingPort:
    """Routes the pinned outbound pairing request into the real broker handler."""

    def __init__(self, *, handler) -> None:
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del timeout_seconds
        assert isinstance(config, OutboundTransportConfig)
        assert operation is BrokerPairingHttpsOperation.REDEEM
        self.calls.append((operation.value, json.loads(json.dumps(payload))))
        response = self.handler.handle(
            method="POST",
            route=f"/{operation.value}",
            content_type="application/json",
            body=json.dumps(payload).encode("utf-8"),
            auth=_device_auth(),
        )
        return json.loads(json.dumps(response.body))


class PairingHandoff3095Test(unittest.TestCase):
    # -- G5: the full authenticated redemption loop ----------------------

    def test_authenticated_challenge_and_pinned_tls_redemption_e2e(self) -> None:
        handler, _authority, _pairing = _pairing_handler()
        store = _CredentialStore()
        port = _HandlerPairingPort(handler=handler)

        # 1. Authenticated browser session issues the single-use challenge.
        issued = _issue_challenge(handler)
        challenge_id = issued["challenge"]["challenge_id"]
        issued_code = issued["pairing_code"]
        self.assertEqual(issued["challenge"]["single_use"], True)
        self.assertEqual(issued["pairing_code_returned_once"], True)

        # 2. The bounded handoff runtime redeems through the pinned transport.
        runner = LocalAgentPairingHandoffRunner(
            config=_config(),
            credential_store=store,
            client=LocalAgentBrokerPairingClient(
                config=_config(),
                credential_store=store,
                request_port=port,
            ),
        )
        result = runner.redeem_handoff(
            pairing_code=issued_code,
            challenge_id=challenge_id,
            device_id=CHALLENGE_DEVICE,
            correlation_ref="pairref-3095",
            now=BASE,
        )

        self.assertIsInstance(result, PairingHandoffResult)
        self.assertEqual(result.binding_state, DeviceLifecycle.PAIRED_OFFLINE.value)
        self.assertEqual(result.online_requires_server_projection, True)
        self.assertEqual(result.local_online_claim, False)
        self.assertEqual(result.production_pairing_activated, False)
        self.assertEqual(result.public_inbound_port, False)
        self.assertEqual(result.pairing_code_persisted, False)
        self.assertEqual(result.pairing_code_logged, False)

        # 3. The proof actually crossed the wire as a proof reference only.
        self.assertEqual(len(port.calls), 1)
        route, payload = port.calls[0]
        self.assertEqual(route, "v1/broker/pairings/redeem")
        self.assertEqual(
            payload["proof_ref"],
            pairing_proof_ref(
                challenge_id=challenge_id,
                device_id=CHALLENGE_DEVICE,
                pairing_code=issued_code,
            ),
        )
        self.assertNotIn(issued_code, json.dumps(payload))
        self.assertNotIn("pairing_code", payload)

        # 4. The protected credential store persisted it exactly once.
        self.assertEqual(len(store.saves), 1)
        self.assertEqual(store.saves[0]["credential_bytes"], len(CREDENTIAL))

    def test_pairing_code_is_single_use(self) -> None:
        handler, _authority, _pairing = _pairing_handler()
        store = _CredentialStore()
        port = _HandlerPairingPort(handler=handler)
        issued = _issue_challenge(handler)
        challenge_id = issued["challenge"]["challenge_id"]
        issued_code = issued["pairing_code"]
        runner = LocalAgentPairingHandoffRunner(
            config=_config(),
            credential_store=store,
            client=LocalAgentBrokerPairingClient(
                config=_config(),
                credential_store=store,
                request_port=port,
            ),
        )
        runner.redeem_handoff(
            pairing_code=issued_code,
            challenge_id=challenge_id,
            device_id=CHALLENGE_DEVICE,
            now=BASE,
        )
        with self.assertRaises(ContractError):
            runner.redeem_handoff(
                pairing_code=issued_code,
                challenge_id=challenge_id,
                device_id=CHALLENGE_DEVICE,
                now=BASE,
            )

    # -- Security locks ---------------------------------------------------

    def test_handoff_never_persists_or_logs_the_pairing_code(self) -> None:
        handler, _authority, _pairing = _pairing_handler()
        store = _CredentialStore()
        runner = LocalAgentPairingHandoffRunner(
            config=_config(),
            credential_store=store,
            client=LocalAgentBrokerPairingClient(
                config=_config(),
                credential_store=store,
                request_port=_HandlerPairingPort(handler=handler),
            ),
        )
        issued = _issue_challenge(handler)
        issued_code = issued["pairing_code"]
        result = runner.redeem_handoff(
            pairing_code=issued_code,
            challenge_id=issued["challenge"]["challenge_id"],
            device_id=CHALLENGE_DEVICE,
            now=BASE,
        )
        projection = result.safe_dict()
        self.assertNotIn(issued_code, json.dumps(projection))
        # No store field ever receives the code.
        for saved in store.saves:
            self.assertNotIn(issued_code, json.dumps(saved, default=str))
        # The runner itself holds no pairing-code attribute at all.
        self.assertEqual(
            [a for a in vars(runner) if "code" in a.lower()], []
        )
        for value in vars(runner).values():
            self.assertNotIn(issued_code, repr(value))

    def test_request_repr_redacts_the_pairing_code(self) -> None:
        request = PairingHandoffRequest(
            pairing_code=CODE,
            challenge_id="challenge.3095",
            device_id=DEVICE_ID,
        )
        self.assertNotIn(CODE, repr(request))

    def test_malformed_pairing_code_fails_closed_before_transport(self) -> None:
        handler, _authority, _pairing = _pairing_handler()
        port = _HandlerPairingPort(handler=handler)
        runner = LocalAgentPairingHandoffRunner(
            config=_config(),
            credential_store=_CredentialStore(),
            client=LocalAgentBrokerPairingClient(
                config=_config(),
                credential_store=_CredentialStore(),
                request_port=port,
            ),
        )
        for bad in ("", "short", CODE.upper(), CODE[:-1] + "g", CODE + "0"):
            with self.subTest(code=bad):
                with self.assertRaises((PairingHandoffError, ContractError)):
                    runner.redeem_handoff(
                        pairing_code=bad,
                        challenge_id="challenge.3095",
                        device_id=DEVICE_ID,
                        now=BASE,
                    )
        # No transport call happened for any rejected code.
        self.assertEqual(port.calls, [])

    def test_unconfigured_runner_fails_closed(self) -> None:
        runner = unconfigured_pairing_handoff_runner()
        with self.assertRaises(ContractError):
            runner.redeem_handoff(
                pairing_code=CODE,
                challenge_id="challenge.3095",
                device_id=DEVICE_ID,
                now=BASE,
            )

    def test_canonical_unconfigured_client_still_fails_closed(self) -> None:
        client = UnconfiguredLocalAgentBrokerPairingClient()
        with self.assertRaises(ContractError):
            client.redeem(
                challenge_id="challenge.3095",
                pairing_code=CODE,
                device_id=DEVICE_ID,
                now=BASE,
            )

    # -- Reuse / no second authority --------------------------------------

    def test_runner_reuses_canonical_authorities(self) -> None:
        runner = LocalAgentPairingHandoffRunner(
            config=_config(),
            credential_store=_CredentialStore(),
        )
        projection = runner.safe_dict()
        self.assertEqual(projection["canonical_client_reused"], True)
        self.assertEqual(projection["canonical_credential_store_reused"], True)
        self.assertEqual(projection["pinned_outbound_transport_reused"], True)
        self.assertEqual(projection["server_projection_trigger_reused"], True)
        self.assertEqual(projection["second_pairing_authority"], 0)
        self.assertEqual(projection["second_credential_authority"], 0)
        self.assertEqual(projection["second_device_lifecycle_authority"], 0)
        self.assertEqual(projection["second_deeplink_parser"], 0)
        self.assertEqual(projection["challenge_issuance_authority"], False)
        self.assertEqual(projection["pairing_authority_owner"], "#3080")
        self.assertEqual(projection["single_transfer_param"], SHELL_PAIRING_CODE_PARAM)
        self.assertEqual(projection["pairing_code_persisted"], False)
        self.assertEqual(projection["pairing_code_logged"], False)
        self.assertEqual(projection["pairing_code_renderer_diagnostic"], False)
        self.assertEqual(projection["public_inbound_port"], False)
        self.assertEqual(projection["upnp_required"], False)
        self.assertEqual(projection["outbound_only"], True)
        self.assertEqual(projection["local_online_claim"], False)
        self.assertEqual(projection["production_pairing_activated"], False)
        self.assertEqual(projection["production_endpoint_configured"], False)
        self.assertEqual(projection["production_mutation"], False)

    def test_handoff_refuses_to_claim_online_without_server_facts(self) -> None:
        """A local caller cannot flip a binding ONLINE on its own."""
        handler, _authority, _pairing = _pairing_handler()
        store = _CredentialStore()
        runner = LocalAgentPairingHandoffRunner(
            config=_config(),
            credential_store=store,
            client=LocalAgentBrokerPairingClient(
                config=_config(),
                credential_store=store,
                request_port=_HandlerPairingPort(handler=handler),
            ),
        )
        issued = _issue_challenge(handler)
        result = runner.redeem_handoff(
            pairing_code=issued["pairing_code"],
            challenge_id=issued["challenge"]["challenge_id"],
            device_id=CHALLENGE_DEVICE,
            now=BASE,
        )
        self.assertEqual(result.binding_state, DeviceLifecycle.PAIRED_OFFLINE.value)
        self.assertEqual(result.local_online_claim, False)

    def test_server_projection_trigger_still_owns_online(self) -> None:
        """The reused trigger refuses ONLINE without a real session+heartbeat."""
        from kagent.local_agent_pairing import DeviceBinding

        binding = DeviceBinding(
            device_id=DEVICE_ID,
            binding_ref="binding.3095",
            account_ref="account.1",
            workspace_ref="workspace.1",
            credential_ref="credential.3095",
            credential_generation=1,
            issued_at=BASE,
            credential_expires_at=BASE + timedelta(hours=1),
            state=DeviceLifecycle.PAIRED_OFFLINE,
        )
        with self.assertRaises(ContractError):
            project_server_backed_online_binding(
                binding=binding,
                session=None,
                heartbeat=None,
                now=BASE,
            )

    def test_full_web_to_desktop_pairing_e2e_is_not_claimed(self) -> None:
        """#3095 must not claim the Web->Desktop E2E; that waits for #3094."""
        runner = LocalAgentPairingHandoffRunner(
            config=_config(),
            credential_store=_CredentialStore(),
        )
        self.assertEqual(runner.safe_dict()["full_web_to_desktop_pairing_e2e"], False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
