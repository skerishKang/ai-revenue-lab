"""Customer PC first-run: reuse canonical WSS offer and DPAPI binding stores.

The existing signed owner button creates the server intent; the PC presents
only an ephemeral possession proof on the pinned outbound WSS. This connector
never claims approval from login/browser data or self-asserted device identity.
No user code, device ID field, operator flag, or second account authority.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

from .device_wss_enrollment import (
    DeviceSessionRefused, canonical_binding_store,
)
from .credential_install import LocalStoreCredentialReceiver
from .pending_pc_offer import run_pending_pc_offer_and_enroll
from .review_wss_transport import open_review_only_wss_socket, VerifiedReviewTls


def protected_credential_directory(state_dir: Path) -> Path:
    """One pinned per-user protected store shared with the Resident."""
    root = state_dir.expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise DeviceSessionRefused("canonical_protected_store_unavailable")
    target = root / "credentials"
    if target.is_symlink():
        raise DeviceSessionRefused("canonical_protected_store_unavailable")
    return target


def _open_owner_approval_page(url: str) -> None:
    """Use the existing signed-in PADIEM browser for this one-use PC offer."""
    import webbrowser

    if not webbrowser.open(url, new=2):
        raise DeviceSessionRefused("pc_offer_owner_browser_unavailable")

async def enroll_customer_pending_offer(*, enrollment: Any) -> Any:
    """Attempt a SINGLE live PC offer and normal canonical credential commit.

    Until LOCAL1 mounts its server-side verified-intent matcher, the server will
    decline the WSS, and nothing is enrolled. This client deliberately does
    not open an additional approval page or forge an approval reply.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise DeviceSessionRefused("customer_bundle_required")
    package = Path(sys._MEIPASS)
    if not (package / "kagent" / "local_agent_resident_process.py").is_file():
        raise DeviceSessionRefused("canonical_agent_source_unavailable")
    sys.path.insert(0, str(package))
    from kagent.local_agent_secure_transport import (
        ProtectedFileDeviceCredentialStore, WindowsDpapiProtectedDataPort,
    )

    root = protected_credential_directory(Path(enrollment.state_dir))
    root.mkdir(parents=True, exist_ok=True)
    protected = WindowsDpapiProtectedDataPort()
    receiver = LocalStoreCredentialReceiver(store=ProtectedFileDeviceCredentialStore(
        base_dir=root, protected_data=protected,
    ))
    bindings = canonical_binding_store(base_dir=str(root), protected_data=protected)
    # Reuse the same TLS-verified, fixed-host, no-redirect socket and one-shot
    # enrollment/ACK. No operator environment option or caller supplied URL.
    async with open_review_only_wss_socket(
        source_test_authorized=True, acceptance=False,
    ) as socket:
        return await run_pending_pc_offer_and_enroll(
            socket=socket, trusted_tls=VerifiedReviewTls(), enrollment=enrollment,
            receiver=receiver, binding_store=bindings,
            owner_approval_open=_open_owner_approval_page,
        )
