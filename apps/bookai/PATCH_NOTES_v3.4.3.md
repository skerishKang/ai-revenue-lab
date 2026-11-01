# StoryMemory v3.4.3 — SM-084 Precision Pack Runtime

## Scope
- Serializable `storymemory-precision-pack-1.0` JSON artifacts for Knowledge, Harness, Search, and Companion Packs.
- Pack compatibility gates by source fingerprint/revision/language/locator scheme.
- Attach/detach lifecycle and `PRECISION_READY` state.
- Pack aliases/search hints feed lexical-first retrieval.
- Pack knowledge evidence is source-locator validated.
- JSON Harness Packs can supply controlled soft policy only.

## Trust boundary
- A Marketplace-style JSON Pack cannot self-declare itself `VERIFIED`.
- `CURATED`, `EXPERT`, or `OFFICIAL` effective trust requires trusted host/registry attestation through `packVerifier`.
- `VERIFIED` answer provenance additionally requires Pack evidence whose locator resolves against the active Source.
- Pack hard-rule override attempts for Trust Mode, spoiler/future visibility, or workbook answer reveal are blocked.

## Measured QA
- Query `헬렌 처음 어디서 나왔지?`: baseline lexical retrieval misses the Source spelling `헬레네`; attached demo Pack adds `헬레네/Helen` hints and restores exact locator `odyssey:book:04:s1:row:002`; detach restores baseline.
- Compatibility negative gates: wrong fingerprint, stale revision, bad artifact fingerprint, and missing compatibility identity all blocked.
- Existing regression suite: 11/11 PASS.
- Static content regression vs v3.4.2: 192 files, changed 0 / missing 0 / extra 0.

## Non-claims
- No Marketplace registry, search/discovery service, payment, entitlement, settlement, rating, or public sharing is implemented in SM-084.
- Demo Odyssey Pack is private QA data, not a production Marketplace listing or independently verified public asset.
- `artifactFingerprint` is a lightweight runtime identity/integrity check, not a cryptographic signature or publisher-authenticity proof.
- `packVerifier` is a runtime contract hook; a live remote registry verification service is not yet implemented.
- Marketplace JSON Packs do not execute arbitrary code. Harness behavior is restricted to controlled configuration keys.
- Persistent Pack installation state and account entitlement are not implemented in this stage.
- Mixed-Source Pack UI is deferred to SM-087.
- Neon, Cloudflare, BI Portal, DNS, and Odyssey Book21+ knowledge are unchanged.
