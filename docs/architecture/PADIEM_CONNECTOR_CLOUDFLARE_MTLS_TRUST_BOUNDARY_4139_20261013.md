# #4139 Connector ingress mTLS trust boundary — source review (2026-10-13 KST)

**Status:** SOURCE-ONLY NEGATIVE GATE · Connector OFF · no client certificate issued · no Worker mount · no Cloudflare production configuration changed.

## Deployment facts vs source assumptions

Actual deployed B62 read-only audit run [38408484009](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38408484009) found PADIEM Chat's Identity Service Binding present and the private Broker Service Binding absent. Broker State and Broker Edge Worker settings were readable with the expected Durable Object/Service binding *names*, but **no actual deployed RPC build provenance** was attested. The state Worker's callable Python `Default` methods are checked by the source AST only.

The source-only `connector_gateway_tls_ingress_source_review.py` is a conservative test port, not a production TLS adapter or a device identity assertion. It requires:
- Exact request URL and ASGI WSS path/scheme and no query or path ambiguity.
- Cloudflare Worker **incoming runtime Request.cf.tlsClientAuth** values: `certPresented == "1"`, `certVerified == "SUCCESS"`, `certRevoked == "0"`.
- A canonical 64-character lowercase SHA-256 client certificate fingerprint matched to an independently operator-approved bounded pinset.
- No cookies, Origin/Authorization, client-certificate forwarding headers or synthetic `X-Forwarded-Proto`, `CF-Visitor`, `CF-TLS-Client-Auth` headers accepted as authority.
- An explicitly injected, source-review-only verifier object; a missing operator pinset returns denial.

Cloudflare documents `request.cf.tlsClientAuth.certVerified` as a **string** and warns that a certificate can be valid yet revoked. A mere `request.url.scheme == "https"` only proves protocol representation and does NOT verify the PC's identity, TLS peer, trusted Cloudflare incoming request or approved enrollment.

References:
- https://developers.cloudflare.com/ssl/client-certificates/client-certificate-variables/
- https://developers.cloudflare.com/ssl/client-certificates/
- https://developers.cloudflare.com/workers/runtime-apis/request/
- https://developers.cloudflare.com/workers/languages/python/basics/

## Critical shared-host operation constraint

`chat.padiem.net` serves the ordinary B62 Chat user experience. Hostname-wide mandatory client mTLS cannot be turned on solely for Connector without an impact assessment for ordinary Chat users. Route/path-specific enforcement or an isolated connector hostname is a separate, operator-reviewed infrastructure design, **not a default change introduced here**. No public hostname, WAF rule, Access policy, DNS or client-certificate issuance is performed.

A synthetic `request.cf` object in unit tests is forgeable and is **not live Cloudflare edge evidence**. Before production admission:
1. Resolve the approved ingress segregation/enforcement strategy and its effect on B62 Chat sessions.
2. Prove actual Cloudflare client-certificate enrollment/rotation/revocation and hostname/path protection under authorized operator configuration. The client certificate identifier must remain separate from the owner pairing code; neither alone authorizes a customer PC.
3. Verify the exact running Worker runtime receives `request.cf.tlsClientAuth` from a real inbound request; ensure no `new Request(..., {cf: ...})` or untrusted forwarding can substitute.
4. Prove negative **real** handshakes: absent cert, invalid cert, revoked cert, wrong device pin, wrong/encoded path, mismatched Origin; all refused before Identity/Broker or credential redemption.
5. Prove positive authenticated WSS from a consented, registered test device in **nonproduction** with DPAPI protected-store ACK and the existing single redemption owner; compare broker durable record and device scope.
6. Only then review served-version provenance, rollback, production binding preservation and enablement flags individually. Connector routes, issuance, credential delivery and PC command permissions stay OFF until these checks pass.

Release state: `TLS_EDGE_ATTESTED=NO; DEPLOYED_BROKER_RPC_PROVEN=NO; WINDOWS_TWO_PC_E2E=NO; CONNECTOR_LIVE=OFF; READY/MERGE=NO`.

This is a technical trust boundary, not a revision of customer governance or a new business authorization.
