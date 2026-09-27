"""#3140 — the single long-lived resident host process.

Issuer and redeemer share **one** broker authority instance here, which is the
only way a same-authority redeem can be proven without a deployed broker. The
resident process itself never constructs an authority and never re-issues a
challenge: it is handed this shared boundary and redeems the Web-issued one.

The two legs present different principals, exactly as the real broker requires:
the Web session is an authenticated browser, the device redeems with an
unauthenticated device principal and a possession proof.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from kagent.contracts import ContractError
from kagent.local_agent_resident_process import (
    ACK_CONTRACT_VERSION,
    BrokerEntry,
    HANDOFF_CONTRACT_VERSION,
    RESIDENT_PROCESS_CONTRACT,
    acknowledge_handoff,
    build_resident_host,
    handoff_delivery_marker,
    read_handoff,
    redeem_handoff,
)
from kagent.windows_execution_authorization import (
    P01LocalPermissionWindowsExecutionAuthorizationPort,
)
from kagent.windows_local_executor import DeterministicWorktreeStatePort
from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_http import TrustedLocalAgentHttpAuthContext
from padiem_control_plane.local_agent_broker_pairing import InMemoryBrokerPairingAuthority
from padiem_control_plane.local_agent_broker_pairing_http import (
    PAIRING_CHALLENGE_ROUTE,
    PairingAndAdmissionLocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

BASE = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
BROKER_PEPPER = b"control-plane-broker-pepper-16bytes!!"
PAIRING_PEPPER = b"control-plane-pairing-pepper16byte!!"
AUTHORITY_REF = "control-plane.local-agent-broker.3140.shared.v1"
DEVICE_ID = "device.3140.resident"
CREDENTIAL = b"3140-shared-authority-credential"


class _Clock:
    def __init__(self, now=BASE):
        self.now = now

    def __call__(self):
        return self.now


class _DurableState:
    durable = True

    def __init__(self):
        self.records: dict = {}

    def save_session(self, record):
        self.records[record.session_id] = record
        return record

    def load_session(self, session_id):
        return self.records[session_id]

    def record_last_seen(self, session_id, *, seen_at):
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class _MaterialResolver:
    def resolve(self, request):
        raise AssertionError("pairing must not resolve command material")


class _References:
    def __call__(self):
        return "admission_3140_1", "evidence_3140_1"


class _Nonces:
    def __init__(self, start=0xE0000):
        self._next = start

    def __call__(self):
        self._next += 1
        return f"{self._next:032x}"


class _SharedBroker:
    """One authority, one pairing authority, one handler, one request port.

    The port is the single boundary both legs cross: the Web session issues
    through it, and the resident redeems through it. That is what makes the
    redemption a real one rather than a reconstruction.
    """

    def __init__(self, *, nonce_start=0xE0000):
        self.clock = _Clock()
        self.authority = InMemoryLocalAgentBrokerAuthority(
            pepper=BROKER_PEPPER, authority_ref=AUTHORITY_REF
        )
        self.pairing = InMemoryBrokerPairingAuthority(
            pepper=PAIRING_PEPPER,
            authority=self.authority,
            code_nonce_factory=_Nonces(nonce_start),
            credential_factory=lambda: CREDENTIAL,
        )
        self.handler = PairingAndAdmissionLocalAgentBrokerHttpHandler(
            pairing_authority=self.pairing,
            admission_reference_factory=_References(),
            rpc=LocalAgentBrokerRpcFacade(authority=self.authority),
            state=_DurableState(),
            material_resolver=_MaterialResolver(),
            clock=self.clock,
        )
        self.audit: list[str] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del config, timeout_seconds
        name = operation.value
        self.audit.append(name)
        if name == "heartbeat" and isinstance(payload, dict) and "now" in payload:
            self.clock.now = datetime.fromisoformat(
                str(payload["now"]).replace("Z", "+00:00")
            )
        # The device redeems with an unauthenticated device principal; the
        # possession proof in the payload is what the broker checks.
        response = self.handler.handle(
            method="POST",
            route=f"/{name}",
            content_type="application/json",
            body=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            auth=TrustedLocalAgentHttpAuthContext(
                principal_ref=DEVICE_ID,
                account_ref="account.1",
                workspace_ref="workspace.1",
                authenticated=False,
                tls_verified=True,
            ),
        )
        return json.loads(json.dumps(response.body))

    def web_issues(self):
        """The Web leg: an authenticated browser session issues the challenge."""

        issued = self.handler.handle(
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
            auth=TrustedLocalAgentHttpAuthContext(
                principal_ref="principal.browser.3140",
                account_ref="account.1",
                workspace_ref="workspace.1",
                authenticated=True,
                tls_verified=True,
            ),
        ).body
        return issued["challenge"]["challenge_id"], issued["pairing_code"]


class _ProtectedDataPort:
    def _stream(self, entropy, length):
        out = b""
        block = 0
        while len(out) < length:
            out += hashlib.sha256(entropy + block.to_bytes(4, "big")).digest()
            block += 1
        return out[:length]

    def protect(self, credential, *, entropy):
        stream = self._stream(entropy, len(credential))
        return bytes(a ^ b for a, b in zip(credential, stream))

    def unprotect(self, protected, *, entropy):
        stream = self._stream(entropy, len(protected))
        return bytes(a ^ b for a, b in zip(protected, stream))


def _handoff(challenge_id, pairing_code):
    return {
        "contract_version": HANDOFF_CONTRACT_VERSION,
        "pairing_code": pairing_code,
        "correlation_ref": "pairref.3140",
        "challenge_id": challenge_id,
    }


class ResidentProcess3140Test(unittest.TestCase):
    def test_handoff_envelope_requires_a_bounded_challenge_id(self) -> None:
        for bad in ("", "not json", "[1,2,3]"):
            with self.assertRaises(ContractError):
                read_handoff(bad)
        # No challenge id: the process must not be able to mint one instead.
        with self.assertRaises(ContractError):
            read_handoff(json.dumps({
                "contract_version": HANDOFF_CONTRACT_VERSION,
                "pairing_code": "0123456789abcdef0123456789abcdef",
                "correlation_ref": "r",
            }))
        parsed = read_handoff(json.dumps({
            "contract_version": HANDOFF_CONTRACT_VERSION,
            "pairing_code": "0123456789abcdef0123456789abcdef",
            "correlation_ref": "r",
            "challenge_id": "challenge.1",
        }))
        self.assertEqual(parsed["challenge_id"], "challenge.1")

    def test_redeem_uses_the_authority_that_issued_the_challenge(self) -> None:
        broker = _SharedBroker()
        challenge_id, pairing_code = broker.web_issues()
        entry = BrokerEntry(
            device_id=DEVICE_ID, authority_ref=AUTHORITY_REF, request_port=broker
        )
        acks: list[dict] = []
        with tempfile.TemporaryDirectory() as base_dir:
            redeemed = redeem_handoff(
                _handoff(challenge_id, pairing_code),
                entry=entry,
                base_dir=base_dir,
                now=BASE + timedelta(seconds=1),
                protected_data=_ProtectedDataPort(),
                emit=acks.append,
            )
        self.assertEqual(redeemed["redeem_count"], 1)
        self.assertEqual(redeemed["binding"].state.value, "paired_offline")
        self.assertIn("v1/broker/pairings/redeem", broker.audit)
        # Item 4: ownership holds, so the acknowledgement fires exactly once.
        self.assertEqual(len(acks), 1)

    def test_a_replayed_handoff_is_refused_and_never_acknowledged(self) -> None:
        """Item 5: a replay must not produce ownership, so no ACK, so the
        main process keeps its one-shot armed."""

        broker = _SharedBroker()
        challenge_id, pairing_code = broker.web_issues()
        entry = BrokerEntry(
            device_id=DEVICE_ID, authority_ref=AUTHORITY_REF, request_port=broker
        )
        with tempfile.TemporaryDirectory() as base_dir:
            redeem_handoff(
                _handoff(challenge_id, pairing_code), entry=entry, base_dir=base_dir,
                now=BASE + timedelta(seconds=1), protected_data=_ProtectedDataPort(),
            )
            acks: list[dict] = []
            with self.assertRaises(ContractError):
                redeem_handoff(
                    _handoff(challenge_id, pairing_code), entry=entry,
                    base_dir=base_dir, now=BASE + timedelta(seconds=2),
                    protected_data=_ProtectedDataPort(), emit=acks.append,
                )
        self.assertEqual(acks, [], "a replay must never be acknowledged")

    def test_a_code_from_another_authority_cannot_be_redeemed(self) -> None:
        broker = _SharedBroker()
        _foreign_challenge, foreign_code = _SharedBroker(nonce_start=0xF0000).web_issues()
        entry = BrokerEntry(
            device_id=DEVICE_ID, authority_ref=AUTHORITY_REF, request_port=broker
        )
        with tempfile.TemporaryDirectory() as base_dir:
            with self.assertRaises(ContractError):
                redeem_handoff(
                    _handoff("challenge.foreign", foreign_code), entry=entry,
                    base_dir=base_dir, now=BASE + timedelta(seconds=1),
                    protected_data=_ProtectedDataPort(),
                )

    def test_acknowledgement_is_secret_free_and_correlated(self) -> None:
        handoff = {
            "contract_version": HANDOFF_CONTRACT_VERSION,
            "pairing_code": "0123456789abcdef0123456789abcdef",
            "correlation_ref": "r",
            "challenge_id": "challenge.1",
        }
        old, buffer = sys.stdout, io.StringIO()
        try:
            sys.stdout = buffer
            acknowledge_handoff(handoff)
        finally:
            sys.stdout = old
        line = buffer.getvalue()
        self.assertNotIn(handoff["pairing_code"], line)
        payload = json.loads(line.strip())
        self.assertEqual(payload["contract_version"], ACK_CONTRACT_VERSION)
        self.assertEqual(
            payload["handoff_marker"], handoff_delivery_marker(handoff["pairing_code"])
        )

    def test_no_configured_broker_means_refusal_not_authority(self) -> None:
        for key in (
            "PADIEM_AGENT_DEVICE_ID",
            "PADIEM_AGENT_AUTHORITY_REF",
            "PADIEM_AGENT_REQUEST_PORT",
        ):
            os.environ.pop(key, None)
        self.assertIsNone(BrokerEntry.from_environment())
        with self.assertRaises(ContractError):
            BrokerEntry(device_id="", authority_ref=AUTHORITY_REF, request_port=object())

    def test_host_composition_fails_closed_without_the_trusted_probe(self) -> None:
        """Item 6: no P01 product pass is claimed before #3148."""

        broker = _SharedBroker()
        challenge_id, pairing_code = broker.web_issues()
        entry = BrokerEntry(
            device_id=DEVICE_ID, authority_ref=AUTHORITY_REF, request_port=broker
        )
        with tempfile.TemporaryDirectory() as base_dir:
            redeemed = redeem_handoff(
                _handoff(challenge_id, pairing_code), entry=entry, base_dir=base_dir,
                now=BASE + timedelta(seconds=1), protected_data=_ProtectedDataPort(),
            )
            with self.assertRaises(ContractError) as refused:
                build_resident_host(redeemed, entry=entry)
        self.assertIn("worktree-state probe", str(refused.exception))

        # With the trusted ports injected the same composition succeeds, which is
        # what proves the refusal above is the seam's rule and not a dead end.
        from kagent.local_agent_permissions import default_device_permission_profile
        from kagent.local_agent import (
            LocalAgentDeviceProfile,
            LocalAgentPlatform,
            LocalRoot,
        )

        device = LocalAgentDeviceProfile(
            device_id=DEVICE_ID,
            workspace_ref="workspace.1",
            platform=LocalAgentPlatform.WINDOWS,
            roots=(LocalRoot(root_ref="root.3140", windows_path="C:/ProgramData/Padiem/runner"),),
        )
        with tempfile.TemporaryDirectory() as base_dir:
            host = build_resident_host(
                redeemed,
                entry=entry,
                authorization_port=P01LocalPermissionWindowsExecutionAuthorizationPort(
                    permission_profile=default_device_permission_profile(device=device)
                ),
                worktree_state_port=DeterministicWorktreeStatePort(dirty=False),
            )
        self.assertIsNotNone(host)

    def test_process_declares_no_authority(self) -> None:
        self.assertFalse(RESIDENT_PROCESS_CONTRACT["pairing_authority_implemented"])
        self.assertFalse(RESIDENT_PROCESS_CONTRACT["broker_authority_implemented"])
        self.assertFalse(RESIDENT_PROCESS_CONTRACT["challenge_reissued"])
        self.assertEqual(RESIDENT_PROCESS_CONTRACT["second_resident_host"], 0)
        self.assertEqual(RESIDENT_PROCESS_CONTRACT["public_inbound_port"], 0)
        self.assertFalse(RESIDENT_PROCESS_CONTRACT["pairing_code_persisted"])


if __name__ == "__main__":
    unittest.main()
