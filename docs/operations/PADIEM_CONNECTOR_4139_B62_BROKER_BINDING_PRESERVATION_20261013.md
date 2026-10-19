# PADIEM Connector #4139 — B62 production binding preservation evidence (2026-10-13 KST)

Status: **READ-ONLY STRUCTURAL PASS / NO PRODUCTION RELEASE APPROVAL**  
Tracking: [Draft PR #4572](https://github.com/skerishKang/ai-revenue-lab/pull/4572), [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139), [Windows E2E #3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099).

## Observed Cloudflare settings (GET only)

On exact prior head `792105e2d4f7a2b0602129e7bdca79faf0a30f4e`, [B62 mock deploy preflight run 38406500285](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38406500285) reported `CONNECTOR_LIVE_BINDING_AUDIT=PASS_READONLY` and `CONNECTOR_BROKER_PRESERVATION=PASS_READONLY` with `PRODUCTION_MUTATION=0`.

The redacted live snapshot contained 43 existing bindings: 5 Service Bindings, 1 D1, 1 R2, 1 assets binding, 20 plain-text vars, 10 secret-text binding **names**, 4 Secrets Store bindings and 1 additional version-metadata/Browser category binding. Neither secret values nor full Cloudflare API responses were printed. This count is point-in-time evidence, NOT a perpetual deployment inventory. A new GET is required before any release.

PADIEM Chat already has `IDENTITY_AUTHORITY_SERVICE` → `padiem-control-plane-identity`. It does **not** have `LOCAL_AGENT_BROKER_AUTHORITY_SERVICE`. The additive candidate targets `padiem-local-agent-broker-state` and changes no other reconstructed TOML sections or other Service Bindings.

The repository `apps/padiem-chat/wrangler.toml` remains a **mock/default-OFF** declaration and is NOT a replayable representation of production bindings. A direct redeploy using only that file risks losing D1, R2, Identity, other services or runtime state.

## Why the target is Broker State (not Broker Edge)

`packages/padiem-control-plane/wrangler.local-agent-broker.jsonc` declares `padiem-local-agent-broker-state` with main `local_agent_broker_worker.py` and the `LOCAL_AGENT_BROKER_STATE` Durable Object. The state Worker's `Default(WorkerEntrypoint)` delegates canonical private enrollment and gateway bootstrap RPCs to its Durable Object; `CanonicalBrokerPairingRPC` supplies the implementation. The separate Edge Worker config delegates to State but is not the selected private canonical RPC service.

`.github/scripts/b62_connector_broker_additive_preflight.py` now verifies the state Worker name, main module, private RPC declarations and their `self._stub()` forwarding paths using parsed source AST. A corresponding mutation test rejects wrong Edge targets, removed RPC implementations or wrong forwarding. **Static source checking does not establish that Cloudflare has deployed the same source revision.**

## Additive release and recovery gate (not yet authorized)

1. **Pre-change read-only snapshot:** Re-read the actual B62 Worker settings and active deployment/version. Confirm all supported binding names, types, and targets, all previously existing secrets by **name only**, live custom domain, and one 100% served version. Re-run `candidate_preservation` against that fresh snapshot; `HOLD` must fail CI.
2. **Source and authority:** Independently attest the exact deployed Broker State Worker revision, its callable private RPC behavior, paired Identity authority and operator-controlled feature flags. Source-only AST proof and HTTP GET presence are insufficient. Keep Connector public gateway OFF.
3. **Bounded mutation:** Only a separately reviewed manual release may generate the B62 production candidate **from the fresh live settings** with `attach_connector_broker_service=True`. The expected diff is precisely one new `[[services]]` binding: `LOCAL_AGENT_BROKER_AUTHORITY_SERVICE` → `padiem-local-agent-broker-state`. No plain-text variable, D1, R2, assets, existing service, Secrets Store, secret-text name or custom-domain changes. This Draft PR does not wire a production apply option.
4. **Before mutation:** Pin and record the exact prior **served production version ID** and B62 settings inventory. Require exact current-main deployment gates, environment protection and rollback eligibility. Abort on drift/unsupported bindings/ambiguous served version or any concurrent mutation. The existing manual production workflow is `.github/workflows/b62-production-code-deploy-gate.yml`; do not bypass it with a direct `wrangler.toml` deploy.
5. **After an independently approved release:** Read back the **served version** and settings; require same 43 original bindings and exactly one new Broker Service Binding (or refreshed counts if legitimate documented drift occurred), preserve secret-name set, and verify private connectivity and production health. A settings-plane success alone never proves secret survival or working authenticated RPC.
6. **Rollback:** On any mismatch, restore the previously recorded served version using the existing guarded `rollback_production_code` flow and `previous_version_id`; then re-read the active deployment, its **served secret names**, all bindings, and core Chat smoke. If rollback cannot be proven, stop and escalate rather than making another blind deployment.

## Release blockers retained

- Exact deployed Broker State RPC revision and trusted TLS ingress provenance unproven.
- Production Identity + Broker device authorization contract and nonproduction authenticated WSS E2E remain to be established.
- Actual two-Windows-PC pairing, DPAPI ACK, restart/reconnect and revocation tests in #3099 outstanding.
- Connector gateway/PC permissions/public routes stay **OFF**. No Ready/Merge/production transition is implied by source-only or read-only CI.
- No user-device credential, registry, DPAPI, Cloudflare binding, Worker version, or production secret was modified by this evidence exercise.
