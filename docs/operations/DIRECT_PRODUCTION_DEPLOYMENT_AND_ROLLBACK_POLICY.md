# Demo and Production Deployment and Recovery Policy

- Status: portfolio operating policy
- Owner: Web CTO under owner authority
- Intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`

## 1. Purpose

AI Revenue Lab uses two controlled deployment lanes because an investor/customer demo and a canonical operating product have different source-authority needs.

```text
Lane A — APPROVED_EXACT_HEAD_DEMO
Lane B — CANONICAL_PRODUCTION
```

Both lanes require explicit owner authorization, exact-source verification, dedicated targets, and real-environment acceptance.

## 2. Lane A — approved exact-head demo deployment

Use this lane for:

- competitive product demos;
- investor demos;
- bounded MVP demonstrations;
- UI or product-upgrade candidates that must be reviewed live before merge;
- dedicated Business demo sites.

The source may remain on an OPEN Draft PR.

Required execution:

```text
reviewed PR exact head
→ explicit owner deployment approval for that SHA and target
→ approved repository GitHub Actions workflow
→ exact SHA checkout and source isolation
→ dedicated Pages project or equivalent demo target
→ deployment metadata and public-byte verification
→ desktop/mobile/journey acceptance
```

The standard workflow may provision or replace a dedicated Business Pages project when its own authority gates pass.

Lane A does not authorize:

- PR Ready;
- merge;
- Issue closure;
- unrelated project mutation;
- backend expansion outside the approved scope;
- direct Dashboard, Wrangler, or ad hoc API deployment.

## 3. Lane B — canonical Production

Use this lane when the accepted product source should become the repository's canonical operating version.

For a Git-connected project:

```text
reviewed exact head
→ explicit merge and Production authorization
→ merge to the configured Production branch
→ automatic Git-connected Production deployment
→ Production acceptance
→ retain or merge a reviewed fix/revert PR
```

Operators observe and verify the automatic deployment. They do not create a second source deployment manually.

## 4. Choosing the lane

Choose Lane A when the main purpose is external review, demonstration, or comparison before canonical integration.

Choose Lane B when:

- the source is accepted as canonical;
- the product is intended to operate from the Production branch;
- repository integration is part of the decision;
- later source recovery should occur through normal reviewed mainline changes.

A successful Lane A deployment does not imply merge approval. A successful Lane B deployment does not imply business success.

## 5. Common authorization boundary

Deployment authorization remains separate from product, visual, MVP, backend, and commercial verdicts.

Before either lane, verify:

- repository and Business;
- source workspace;
- exact approved SHA;
- target project and hostname;
- deployment lane;
- relevant tests and review verdicts;
- current known-good target state;
- rollback or redeploy source;
- authentication and data boundary when applicable.

## 6. Dedicated target rule

Each Business uses its own approved target unless an explicit portfolio decision says otherwise.

A green deployment under an unrelated project is invalid evidence.

Automatic previews created by unrelated Git integrations are not valid Business deployment evidence.

## 7. Prohibited deployment methods

Unless the owner explicitly authorizes the exact exception, do not use:

- `wrangler pages deploy` or direct upload;
- Dashboard retry or manual upload;
- ad hoc API-created deployment;
- empty commits used only as triggers;
- unrelated Preview or staging substitution;
- promotion from an unreviewed environment;
- cancellation and replacement of an authoritative deployment with another path.

Lane A's approved GitHub Actions workflow is not an ad hoc manual deployment. It is the controlled exact-head demo lane.

## 8. Risk levels

### D0 — documentation

Validate links, scope, and rendering. Deployment is normally unnecessary.

### D1 — static demo or local assets

- exact-head review;
- desktop/mobile browser checks;
- asset and console checks;
- Lane A or Lane B according to the source-authority decision.

### D2 — frontend runtime or read-only API

- deterministic tests;
- network and schema checks;
- critical journey acceptance;
- known-good source recorded.

### D3 — backend, secrets, auth, or persistence

- runtime and failure tests;
- secret and authorization review;
- data-integrity checks;
- configuration and recovery evidence;
- primary journey acceptance.

### D4 — migration, billing, destructive data, or irreversible action

- separate owner authorization;
- recovery rehearsal;
- Preview or staging only when the approved Business contract requires it;
- destructive-operation and data-integrity review.

## 9. Lane A evidence

Record:

- reviewed PR and exact head;
- owner approval authority;
- workflow file and run ID;
- workflow conclusion;
- dedicated project name;
- deployment ID and URL;
- exact deployed source or public-byte hash;
- desktop and mobile evidence;
- console, network, and overflow results;
- unrelated project mutation audit;
- PR Draft/unmerged state;
- redeploy source if rollback is required.

Useful disposition:

```text
APPROVED_EXACT_HEAD_DEMO_DEPLOYED
PUBLIC_BYTES_VERIFIED
PRODUCTION_VISUAL_VERIFIED
PR_OPEN_DRAFT_UNMERGED
```

## 10. Lane B evidence

Record:

- reviewed PR head;
- resulting canonical branch SHA;
- Git-connected project and Production branch;
- automatic deployment ID and status;
- Production URL;
- previous known-good source and configuration;
- tests and CI;
- primary-journey Production acceptance;
- fix/revert requirement;
- final disposition.

Useful disposition:

```text
CANONICAL_PRODUCTION_DEPLOYMENT_VERIFIED
```

## 11. Acceptance

Verify the relevant subset of:

- source SHA or byte identity;
- TLS and hostname;
- root and critical routes;
- intended authentication boundary;
- required assets;
- API methods, headers, and schemas;
- desktop and mobile product journeys;
- console, page, CSP, and network failures;
- secret and private-data leakage;
- persistence, cache, and fallback behavior;
- product identity and benchmark-critical visual elements.

Root HTTP 200 alone is not acceptance.

## 12. Recovery

### Lane A

A broken demo is recovered by deploying a previously reviewed known-good exact head or an independently reviewed repair head through the approved workflow.

Do not merge merely to recover a demo.

### Lane B

A source failure is recovered through an expected-head-reviewed fix or revert PR merged to the Production branch, followed by automatic Git-connected deployment.

Configuration restoration may occur separately when configuration itself caused the failure.

## 13. Preview and staging

Preview and staging are not portfolio defaults.

Use them only when explicitly required for:

- destructive migration rehearsal;
- payment or billing verification;
- high-risk auth changes;
- regulated review;
- an external reviewer who must not access the selected demo or Production target.

A platform defect in Preview must not block an authorized Lane A dedicated demo or Lane B Production path.

## 14. API, CLI, and owner interaction

Connectors, API, and CLI are preferred for inspection, evidence collection, and explicitly authorized configuration.

Do not ask the owner to perform routine checks that authenticated tools can perform.

Before requesting an owner-only action:

1. verify it is genuinely required;
2. inspect the authoritative contract;
3. use exact names;
4. group the actions;
5. never request passwords, OTPs, cookies, private keys, or tokens in chat.

## 15. Relationship to product stages

The product-stage policy determines what is being built. This policy determines how the reviewed source is exposed.

```text
competitive or investor demo → normally Lane A
MVP candidate review → Lane A or Lane B
accepted operating product → normally Lane B
```

The owner may choose the lane based on the Business evidence goal.