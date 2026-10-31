# Chat connector WSS parity work (2026-10-31)

On base dd348eeff the COM2 gateway rejected production's first
`pc_offer_begin` frame. The opt-in COM2 relay now forwards the frame to the
broker socket owner, rather than constructing another owner or store.
`test_com2_prod_wss_parity.py` sends the same synthetic first frame through
the production dispatch and COM2 route: both return the same challenge, with
the real `LivePcWssOffer` actor and a local SQLite adapter.

This first-frame test uses a transport double. It does not yet compare proof,
owner approval, credential/ACK, terminal result or close, and it does not
prove production parity or live device behavior. The relay is default off
(`PADIEM_COM2_PC_OFFER_RELAY_ENABLED`); enabling it requires the #6404
loopback broker socket endpoint and its durable replay protection. It sends a
new random request ID signed with the existing broker v1 service proof as the
GET body; the broker must verify and atomically consume it. The exact relay
contract and redirect/failure behavior need review before activation.
No Cloudflare Worker, live COM2 service or production state was changed.
