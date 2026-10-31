# COM2 identity relay: upstream limitation

CTO selected Cloudflare DO as the sole identity writer. The COM2 8802 entry
requires `com2_identity_do_proxy:create_authority` and refuses startup when
a local database path is configured. It signs HTTPS requests with the existing
v1 service-proof contract; the upstream address and existing secret file must
be configured separately. It never generates a key.

Local tests exercise all 23 methods against a synthetic HTTP server. This does
not demonstrate that Cloudflare currently exposes all those methods over HTTPS.
`identity_authority_worker.py:34-44` allows only nine methods in the
authenticated HTTPS ingress; the three connector methods and the requested
eleven additional methods exist on its private Service Binding, but are **not**
in the HTTPS allowlist. Its configured public fetch route is not established
by this change. Consequently, those 14 methods will fail closed until an
authorized private upstream/transport exposing them is provided. Do not enable
this relay or retire the existing identity path on fake-server test evidence.

No Cloudflare Worker, deployed service, live key or production state is changed
here. The authority RPC surface, exposure and per-caller authorization need a
separately reviewed solution respecting the current no-Cloudflare-change
instruction. Existing signed inbound clients retain the loopback ingress proof.
