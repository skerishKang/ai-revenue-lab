# M2a caller-boundary note

The caller-facing `PinnedOutboundLocalAgentChannel` owns its trusted `OutboundTransportConfig` from construction time. Its `poll` and `acknowledge` methods intentionally expose no `config`, `endpoint`, or `url` argument. The lower-level physical `OutboundLocalAgentTransportPort` receives that pinned configuration internally.

Credential rotation changes the exact pinned binding generation/fingerprint, so a stale channel fails closed and must be rebuilt from fresh trusted binding state.
