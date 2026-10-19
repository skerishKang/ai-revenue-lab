"""#4139 Windows operator-only WSS enrollment against the existing Agent.

The installed Connector pins the existing kagent source in resident.json. Its
normal Python interpreter is not guaranteed to have kagent on sys.path, so
explicitly resolve this ONE pinned Agent before opening any WSS socket or DPAPI
store. This is not an Agent installer, credential authority or production gate.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from typing import Any

from .device_wss_enrollment import (
    DeviceSessionRefused, _CANONICAL_CREDENTIAL_DIR_ENV, canonical_binding_store,
)

_REVIEW_OPERATOR_ENV = "PADIEM_CONNECTOR_OPERATOR_WSS_ACCEPTANCE"
_REVIEW_OPERATOR_VALUE = "isolated-operator-acceptance-4139"
_TARGET_ENV = "PADIEM_CONNECTOR_OPERATOR_WSS_TARGET"
_ACCEPTANCE_HOST = "connector-acceptance.padiem.net"
_NORMAL_HOST = "chat.padiem.net"


def operator_review_target_host() -> str:
    """Host is an explicit fixed policy pin, never an arbitrary CLI URL."""
    selected = os.environ.get(_TARGET_ENV, _NORMAL_HOST)
    if selected not in (_NORMAL_HOST, _ACCEPTANCE_HOST):
        raise DeviceSessionRefused("unreviewed_operator_wss_host")
    return selected



def operator_review_admitted() -> bool:
    """Only explicit one-shot Windows operator acceptance can open real WSS."""
    return (
        os.name == "nt"
        and os.environ.get(_REVIEW_OPERATOR_ENV) == _REVIEW_OPERATOR_VALUE
        and bool(os.environ.get(_CANONICAL_CREDENTIAL_DIR_ENV))
    )


def _admit_existing_agent_package(*, state_dir: Path) -> None:
    """Admit the sole installer-pinned kagent package, never guess a checkout."""
    from .agent_preflight import _canonical_source, agent_preflight
    from .resident_path import resident_src_root

    try:
        selected = resident_src_root(state_dir=state_dir)
        if selected is None:
            if agent_preflight(state_dir=state_dir)["agent_ready"] is not True:
                raise ValueError("canonical Agent not installed")
            return

        source = Path(selected).expanduser()
        if not source.is_absolute() or not _canonical_source(source):
            raise ValueError("canonical Agent source invalid")
        root = source.resolve(strict=True)
        intended = (root / "kagent").resolve(strict=True)
        # A separate installed Python package may be earlier on sys.path.
        # Prefer the explicit installer pin, but NEVER replace an already
        # imported foreign module in this process.
        loaded = sys.modules.get("kagent")
        if loaded is not None:
            locations = getattr(loaded, "__path__", ())
            if not locations or not all(
                Path(location).resolve() == intended for location in locations
            ):
                raise ValueError("loaded Agent conflicts with installer pin")
        else:
            if str(root) in sys.path:
                sys.path.remove(str(root))
            sys.path.insert(0, str(root))
            importlib.invalidate_caches()
            found = importlib.util.find_spec("kagent")
            if found is None or not found.submodule_search_locations:
                raise ValueError("pinned canonical Agent could not be loaded")
            if not all(
                Path(location).resolve() == intended
                for location in found.submodule_search_locations
            ):
                raise ValueError("pinned canonical Agent resolved to another package")
    except (OSError, ValueError, ImportError, RuntimeError, TypeError) as exc:
        raise DeviceSessionRefused("canonical_agent_source_unavailable") from exc


async def enroll_via_operator_wss_review(
    *, enrollment: Any, challenge_id: str, pairing_code: str,
) -> Any:
    """Verified WSS → existing Windows DPAPI store → one local device record."""
    if not operator_review_admitted():
        raise DeviceSessionRefused("operator_wss_acceptance_not_configured")

    configured = os.environ.get(_CANONICAL_CREDENTIAL_DIR_ENV, "")
    root = Path(configured).expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise DeviceSessionRefused("canonical_protected_store_unavailable")

    # installed resident.json determines the sole Agent package. The same
    # PADIEM_AGENT_CREDENTIAL_DIR is already the canonical Resident's
    # credential-store directory; do not mint an alternative storage root.
    target_host = operator_review_target_host()
    _admit_existing_agent_package(state_dir=enrollment.state_dir)
    try:
        from kagent.local_agent_secure_transport import (
            ProtectedFileDeviceCredentialStore,
            WindowsDpapiProtectedDataPort,
        )
        from .credential_install import LocalStoreCredentialReceiver
        from .review_wss_transport import run_review_only_wss_pairing

        protection = WindowsDpapiProtectedDataPort()
        store = ProtectedFileDeviceCredentialStore(
            base_dir=root, protected_data=protection,
        )
        receiver = LocalStoreCredentialReceiver(store=store)
        # The SAME canonical binding store, on the SAME canonical credential
        # directory and the SAME current-user DPAPI port: the enrollment makes
        # the binding durable there before publishing, so the Resident's own
        # resume path finds it after a restart without a new pairing code.
        binding_store = canonical_binding_store(
            base_dir=configured, protected_data=protection,
        )
    except (ImportError, RuntimeError, ValueError, OSError) as exc:
        raise DeviceSessionRefused("canonical_protected_store_unavailable") from exc

    return await run_review_only_wss_pairing(
        enrollment=enrollment,
        receiver=receiver,
        challenge_id=challenge_id,
        pairing_code=pairing_code,
        source_test_authorized=True,
        acceptance=(target_host == _ACCEPTANCE_HOST),
        binding_store=binding_store,
    )


async def enroll_via_pending_pc_offer(*, enrollment: Any) -> Any:
    """Verified WSS offer → owner approval → SAME socket/auto enrollment.

    Reuses the reviewed one-click composition: the PC proves possession of a
    fresh ephemeral key, the owner approval page opens with a public ref only,
    and the Broker delivers challenge/code on the SAME socket so enrollment
    continues without typed codes. No challenge, code, device id, cookie, or
    credential ever travels on argv, URL, disk, or logs.
    """
    if not operator_review_admitted():
        raise DeviceSessionRefused("operator_wss_acceptance_not_configured")

    configured = os.environ.get(_CANONICAL_CREDENTIAL_DIR_ENV, "")
    root = Path(configured).expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise DeviceSessionRefused("canonical_protected_store_unavailable")

    target_host = operator_review_target_host()
    _admit_existing_agent_package(state_dir=enrollment.state_dir)
    try:
        from kagent.local_agent_secure_transport import (
            ProtectedFileDeviceCredentialStore,
            WindowsDpapiProtectedDataPort,
        )
        from .credential_install import LocalStoreCredentialReceiver
        from .review_wss_transport import run_review_only_one_click_pc_link

        protection = WindowsDpapiProtectedDataPort()
        store = ProtectedFileDeviceCredentialStore(
            base_dir=root, protected_data=protection,
        )
        receiver = LocalStoreCredentialReceiver(store=store)
        binding_store = canonical_binding_store(
            base_dir=configured, protected_data=protection,
        )
    except (ImportError, RuntimeError, ValueError, OSError) as exc:
        raise DeviceSessionRefused("canonical_protected_store_unavailable") from exc

    import webbrowser

    return await run_review_only_one_click_pc_link(
        enrollment=enrollment,
        receiver=receiver,
        owner_approval_open=webbrowser.open,
        source_test_authorized=True,
        acceptance=(target_host == _ACCEPTANCE_HOST),
        binding_store=binding_store,
    )
