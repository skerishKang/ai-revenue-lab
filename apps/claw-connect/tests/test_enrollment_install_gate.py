"""#4139 LOCAL2 enrollment -> install gate invariants (composition level).

The transport and the protected-install confirmation are separate owners. These
tests pin the composition rules the CTO required:

* a server success receipt alone is never enough to claim installation;
* an install that cannot be confirmed raises instead of returning a soft value;
* no credential, token or pairing code is ever logged or printed by the two new
  modules.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect.credential_install import (  # noqa: E402
    RECOVERY_SECURITY_HOLD,
    CredentialInstallError,
    LocalStoreCredentialReceiver,
    UnconfiguredProtectedCredentialReceiver,
    plan_install_failure_recovery,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
NEW_MODULES = ("claw_connect/enrollment_http.py", "claw_connect/credential_install.py")


class _Binding:
    binding_ref = "binding-1"
    device_id = "pc_abc123"
    credential_generation = 2


def test_server_receipt_alone_never_confirms_installation():
    # With the central delivery channel unwired, the receiver cannot install, so
    # no confirmation exists and the PC must not be reported as enrolled.
    receiver = UnconfiguredProtectedCredentialReceiver()
    with pytest.raises(Exception):
        receiver.install_once(
            challenge_id="c1",
            device_id="pc_abc123",
            credential=b"raw",
            binding=_Binding(),
        )


def test_unconfirmed_install_raises_rather_than_soft_failing():
    class _BrokenStore:
        def save(self, *, binding, credential, now):
            raise RuntimeError("boom")

        def load(self, *, binding, now):
            raise AssertionError("readback must not run after a failed save")

    receiver = LocalStoreCredentialReceiver(store=_BrokenStore(), now_factory=lambda: NOW)
    with pytest.raises(CredentialInstallError):
        receiver.install_once(
            challenge_id="c1",
            device_id="pc_abc123",
            credential=b"raw",
            binding=_Binding(),
        )


def test_failed_install_without_confirmed_revocation_is_a_security_hold():
    # Composition rule for the gate above: an install that could not be
    # confirmed never turns into a retry of the same redeemed challenge.
    disposition = plan_install_failure_recovery(revocation_confirmed=None)
    assert disposition.action == RECOVERY_SECURITY_HOLD
    assert disposition.report_enrolled is False
    assert disposition.retry_same_challenge is False


def test_receiver_never_returns_a_negative_confirmation():
    # install_once either returns installed=True or raises; a caller can never
    # receive a falsy confirmation it might misread as success.
    source = (ROOT / "claw_connect" / "credential_install.py").read_text(encoding="utf-8")
    assert "installed=False" not in source


@pytest.mark.parametrize("relative", NEW_MODULES)
def test_new_modules_never_log_or_print_secrets(relative):
    source = (ROOT / relative).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    for forbidden in ("import logging", "print(", "logger.", "logging."):
        assert forbidden not in code, f"{relative} must not {forbidden}"
