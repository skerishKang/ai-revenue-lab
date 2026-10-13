"""#4139 explicit operator-only Windows WSS pairing adapter.

Wires existing REAL WSS client to existing canonical Windows DPAPI store.
No second credential authority, no passwords, no browser cookies, no HTTP
credential fallback, no new Broker. Production CLI stays blocked by default.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .device_wss_enrollment import DeviceSessionRefused

_REVIEW_OPERATOR_ENV = "PADIEM_CONNECTOR_OPERATOR_WSS_ACCEPTANCE"
_REVIEW_OPERATOR_VALUE = "isolated-operator-acceptance-4139"
_CANONICAL_CREDENTIAL_DIR_ENV = "PADIEM_AGENT_CREDENTIAL_DIR"


def operator_review_admitted() -> bool:
    """No file state, remote network or arbitrary client-supplied URL."""
    return (
        os.name == "nt"
        and os.environ.get(_REVIEW_OPERATOR_ENV) == _REVIEW_OPERATOR_VALUE
        and bool(os.environ.get(_CANONICAL_CREDENTIAL_DIR_ENV))
    )


async def enroll_via_operator_wss_review(
    *, enrollment: Any, challenge_id: str, pairing_code: str,
) -> Any:
    """One-shot verified WSS -> canonical DPAPI -> source-shared device record.

    The canonical kagent credential dir MUST be selected by the existing Agent
    deployment. Never guess a second credential storage path.
    """
    if not operator_review_admitted():
        raise DeviceSessionRefused("operator_wss_acceptance_not_configured")
    configured = os.environ.get(_CANONICAL_CREDENTIAL_DIR_ENV, "")
    root = Path(configured).expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise DeviceSessionRefused("canonical_protected_store_unavailable")
    try:
        from kagent.local_agent_secure_transport import (
            ProtectedFileDeviceCredentialStore,
            WindowsDpapiProtectedDataPort,
        )
        from .credential_install import LocalStoreCredentialReceiver
        from .review_wss_transport import run_review_only_wss_pairing
        # Reuse the *same* existing protected store as the kagent Resident.
        store = ProtectedFileDeviceCredentialStore(
            base_dir=root, protected_data=WindowsDpapiProtectedDataPort(),
        )
        receiver = LocalStoreCredentialReceiver(store=store)
    except (ImportError, RuntimeError, ValueError, OSError) as exc:
        raise DeviceSessionRefused("canonical_protected_store_unavailable") from exc
    return await run_review_only_wss_pairing(
        enrollment=enrollment, receiver=receiver,
        challenge_id=challenge_id, pairing_code=pairing_code,
        source_test_authorized=True,
    )
