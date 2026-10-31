# Chat connector WSS differential finding (2026-10-31)

Source base dd348eeff. The test `apps/padiem-chat/tests/test_com2_prod_wss_parity.py`
passes the same synthetic PC `pc_offer_begin` frame to actual production
`maybe_dispatch_connector_gateway` and the COM2 `create_com2_gateway`
entrypoints. The production Service Binding is a double delivering the frame
to the real `LivePcWssOffer` class with a real local SQLite adapter. COM2
uses the actual edge verifier and Starlette TestClient; no real CF runtime,
network tunnel, production data or device is used.

| Input | Production path | COM2 host path |
|---|---|---|
| pc_offer_begin, synthetic valid key | Production dispatch hands off to Broker private PC-offer socket; actual actor emits pc_offer_challenge | COM2 opens the gateway socket, then closes 1011 because it expects a different first frame, `begin` |

The response 101 is simulated by the Service Binding double. The test proves
a protocol divergence, not live Worker behavior or successful enrollment.
A full same-flow comparison cannot pass the first frame until the COM2 broker
PC-offer route and secure host routing are implemented. Production also checks
its configured public URL, release gates, and Worker TLS metadata; COM2 uses
its own default-off gateway, signed edge proof and durable replay database.
Those transport checks differ by design but require explicit parity review.
Do not switch the production PC connector to this COM2 path on this evidence.
