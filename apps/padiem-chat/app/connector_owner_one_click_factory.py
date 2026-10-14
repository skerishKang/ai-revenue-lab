"""#4139 per-request B54 owner -> canonical Broker private pending-PC composer.

Construct ONLY after the existing signed B54 owner+origin+CSRF verification.
The server, not browser JSON, injects the canonical Identity, issuing Host,
and the preexisting canonical Broker private Service Binding.

Default OFF. Neither creates any new account/session grant nor deploys or
mounts a public endpoint. A broker DO lacking a live same-DO WSS refuses.
"""
from __future__ import annotations

from typing import Any
from padiem_control_plane.auth_sessions import AuthSessionSnapshot

from .connector_one_click_approval import OneClickOwnerApproval
from .connector_pending_pc_owner_rpc import (
    CanonicalBrokerOwnerPendingPcPort,
    OwnerPcPrivateRpcDenied,
)

ONE_CLICK_OWNER_FACTORY_PRODUCTION_ENABLED = False


class VerifiedOwnerOneClickFactory:
    def __init__(self, *, identity: Any, host: Any, broker_binding: Any) -> None:
        if not callable(getattr(identity, "grant_connector_enrollment_consent", None)):
            raise ValueError("canonical Identity consent authority missing")
        if not callable(getattr(host, "issue", None)):
            raise ValueError("canonical issuing host missing")
        if any(not callable(getattr(broker_binding, key, None)) for key in (
            "reserve_pending_pc_link", "deliver_pending_pc_link",
        )):
            raise ValueError("canonical Broker owner private RPC missing")
        self._identity=identity
        self._host=host
        self._binding=broker_binding

    def for_verified_owner(self, *, signed_owner: AuthSessionSnapshot) -> OneClickOwnerApproval:
        # Exact AuthSessionSnapshot required by the private Broker adapter.
        # The HTTP route has ALREADY verified product owner and exact origin.
        scoped = CanonicalBrokerOwnerPendingPcPort(
            signed_owner=signed_owner,
            canonical_broker_binding=self._binding,
        )
        return OneClickOwnerApproval(
            identity=self._identity, host=self._host,
            pc_rendezvous=scoped,
        )
