"""Compatibility import for the canonical, installable pending-PC Broker ledger.

The authoritative implementation lives in padiem_control_plane.pending_pc_link
so B62 installed-Python CI, Worker source and broker tests import the same
VerifiedPendingPc/DurablePendingPcLink classes. No secondary state/authority.
This file remains a source-compatible root entry for existing review scripts.
"""
from padiem_control_plane.pending_pc_link import (  # noqa: F401
    PENDING_PC_LINK_SCHEMA_INSTALLED_BY_DEFAULT,
    PENDING_PC_LINK_HTTP_ROUTE_MOUNTED,
    PENDING_PC_LINK_PRODUCTION_ENABLED,
    MIGRATION_ID,
    MAX_OFFER_TTL_SECONDS,
    MAX_UNEXPIRED_OFFERS,
    VerifiedPendingPc,
    DurablePendingPcLink,
    install_pending_pc_link_schema,
)
