"""Root compatibility wrapper for the installed canonical Broker private RPC.

The authoritative default-OFF implementation is packaged at
padiem_control_plane.broker_pending_pc_private_rpc. This wrapper remains
importable by the existing Broker Worker runtime entrypoint.
"""
from padiem_control_plane.broker_pending_pc_private_rpc import (  # noqa: F401
    CanonicalBrokerPendingPcLiveRPC,
    BrokerPendingPcPrivateRefused,
    _PRIVATE_METHODS_PRODUCTION_ENABLED,
    _OWNER_RPC_MOUNTED,
    _PC_WSS_SAME_BROKER_DO_MOUNTED,
)
