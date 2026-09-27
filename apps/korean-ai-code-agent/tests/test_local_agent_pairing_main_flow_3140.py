"""#3140 — the runner-side main flow.

The entry point composes existing machinery only: the #3095 pairing runner, the
#3014 resident host, the P01-approved Windows executor and the #3080 broker and
pairing authorities. These tests prove the composition reaches the canonical
session/poll path, redeems exactly once, and adds no second authority.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import tempfile
import unittest

from kagent.contracts import ContractError
from kagent.windows_local_executor import DeterministicWorktreeStatePort
from kagent.local_agent_pairing_main_flow import (
    HANDOFF_CONTRACT_VERSION,
    issue_code,
    main,
    read_handoff,
    run,
)


class _DeterministicProtectedDataPort:
    """CI-only protection port so the composition runs off-Windows too.

    The deployed shape is Windows DPAPI and is what the Windows evidence run
    uses; this double is a real, reversible, deterministic round trip so the
    *composition* — redeem once, session, heartbeat, poll, host ONLINE — is
    proven on every OS the repo tests on. It is not a second credential store:
    `ProtectedFileDeviceCredentialStore` still owns the file and the binding
    entropy.
    """

    @staticmethod
    def _keystream(entropy: bytes, length: int) -> bytes:
        stream = b""
        block = 0
        while len(stream) < length:
            stream += hashlib.sha256(entropy + block.to_bytes(4, "big")).digest()
            block += 1
        return stream[:length]

    def protect(self, credential: bytes, *, entropy: bytes) -> bytes:
        keystream = self._keystream(entropy, len(credential))
        return bytes(a ^ b for a, b in zip(credential, keystream))

    def unprotect(self, protected: bytes, *, entropy: bytes) -> bytes:
        keystream = self._keystream(entropy, len(protected))
        return bytes(a ^ b for a, b in zip(protected, keystream))


NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


class PairingMainFlow3140Test(unittest.TestCase):
    def test_handoff_line_is_bounded_and_fails_closed(self) -> None:
        with self.assertRaises(ContractError):
            read_handoff("")
        with self.assertRaises(ContractError):
            read_handoff("not json")
        with self.assertRaises(ContractError):
            read_handoff(json.dumps([1, 2, 3]))
        with self.assertRaises(ContractError):
            read_handoff(json.dumps({"contract_version": "other", "pairing_code": "a" * 32, "correlation_ref": "r"}))
        with self.assertRaises(ContractError):
            # A code the #3080 shape does not allow is refused before any wire.
            read_handoff(json.dumps({"contract_version": HANDOFF_CONTRACT_VERSION, "pairing_code": "XYZ", "correlation_ref": "r"}))
        with self.assertRaises(ContractError):
            read_handoff("x" * 5_000)
        accepted = read_handoff(
            json.dumps(
                {
                    "contract_version": HANDOFF_CONTRACT_VERSION,
                    "pairing_code": "0123456789abcdef0123456789abcdef",
                    "correlation_ref": "pairref.3140",
                }
            )
        )
        self.assertEqual(accepted["correlation_ref"], "pairref.3140")

    def test_a_code_this_broker_never_issued_is_refused(self) -> None:
        # The possession proof exists to stop exactly this: a code no issuance
        # produced must never reach redemption.
        with tempfile.TemporaryDirectory() as base_dir:
            with self.assertRaises(ContractError) as refused:
                run(
                    {
                        "contract_version": HANDOFF_CONTRACT_VERSION,
                        "pairing_code": "0123456789abcdef0123456789abcdef",
                        "correlation_ref": "pairref.3140",
                    },
                    base_dir=base_dir,
                    device_id="device.3140.runner",
                    now=NOW,
                )
        self.assertIn("issued", str(refused.exception))

    def test_main_flow_reaches_the_canonical_session_and_poll_path(self) -> None:
        code = issue_code(now=NOW)
        with tempfile.TemporaryDirectory() as base_dir:
            outcome = run(
                {
                    "contract_version": HANDOFF_CONTRACT_VERSION,
                    "pairing_code": code,
                    "correlation_ref": "pairref.3140",
                },
                base_dir=base_dir,
                device_id="device.3140.runner",
                now=NOW,
                protected_data=_DeterministicProtectedDataPort(),
                worktree_state_port=DeterministicWorktreeStatePort(dirty=False),
            )
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["redemption"], "paired_offline")
        self.assertEqual(outcome["redeem_count"], 1, "redemption must happen exactly once")
        self.assertEqual(outcome["host_state"], "ONLINE")
        self.assertEqual(outcome["host_final_state"], "STOPPED")
        for route in ("session", "heartbeat", "poll"):
            self.assertIn(route, outcome["wire_routes"])

    def test_main_flow_adds_no_authority_and_leaks_nothing(self) -> None:
        code = issue_code(now=NOW)
        with tempfile.TemporaryDirectory() as base_dir:
            outcome = run(
                {
                    "contract_version": HANDOFF_CONTRACT_VERSION,
                    "pairing_code": code,
                    "correlation_ref": "pairref.3140",
                },
                base_dir=base_dir,
                device_id="device.3140.runner",
                now=NOW,
                protected_data=_DeterministicProtectedDataPort(),
                worktree_state_port=DeterministicWorktreeStatePort(dirty=False),
            )
        self.assertEqual(outcome["second_pairing_authority"], 0)
        self.assertEqual(outcome["second_resident_host"], 0)
        self.assertEqual(outcome["second_execution_authority"], 0)
        self.assertEqual(outcome["public_inbound_port"], False)
        self.assertEqual(outcome["production_mutation"], False)
        self.assertEqual(outcome["pairing_code_logged"], False)
        self.assertEqual(outcome["pairing_code_persisted"], False)
        # The projection itself must not carry the code either.
        self.assertNotIn(code, json.dumps(outcome))

    def test_entry_point_refuses_a_malformed_handoff_without_running(self) -> None:
        import io
        import sys

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = io.StringIO("not a handoff\n")
            sys.stdout = io.StringIO()
            exit_code = main([])
            emitted = sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = original_stdin, original_stdout
        self.assertEqual(exit_code, 2)
        self.assertIn("handoff_refused", emitted)

    def test_product_entry_fails_closed_without_the_trusted_worktree_probe(self) -> None:
        """#3140 review item 4: the canonical P01 seam refuses an unconfigured
        executor, and it also refuses a missing worktree-state probe. The
        product has no real probe yet, so the composition must refuse rather
        than manufacture an executor that would have to be trusted later.
        """

        with tempfile.TemporaryDirectory() as base_dir:
            with self.assertRaises(ContractError) as refused:
                run(
                    {
                        "contract_version": HANDOFF_CONTRACT_VERSION,
                        "pairing_code": issue_code(now=NOW),
                        "correlation_ref": "pairref.3140",
                    },
                    base_dir=base_dir,
                    device_id="device.3140.runner",
                    now=NOW,
                    protected_data=_DeterministicProtectedDataPort(),
                    worktree_state_port=None,
                )
        self.assertIn("worktree-state probe", str(refused.exception))

    def test_issued_code_has_the_canonical_shape(self) -> None:
        code = issue_code(now=NOW)
        self.assertEqual(len(code), 32)
        self.assertTrue(all(character in "0123456789abcdef" for character in code))
        # Single-use is enforced by the challenge being consumed, not by the
        # code differing between issuances: this in-process issuer is
        # deterministic so a test is reproducible. #3095 already pins that a
        # consumed challenge cannot be redeemed again.


if __name__ == "__main__":
    unittest.main()
