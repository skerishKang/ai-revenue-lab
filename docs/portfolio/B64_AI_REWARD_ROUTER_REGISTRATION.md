# B64 · AI Reward Router — Business Registration / Renumbering Record

Status: proposed registration pending reviewed PR

Authority: #987, with BI deployment boundary #778

## Identity

```text
BUSINESS_ID = B64
STABLE_SLUG = ai-reward-router
PRODUCT_NAME = AI Reward Router / AI Earning Router
PREVIOUS_PROVISIONAL_ID = B21
LIFECYCLE = incubation
DEPLOYMENT = DEFERRED_TO_BI_PORTAL
PORTAL_TARGET_ROUTE = /b64/
```

## Why B64

The Reward Router work pack was created after Business 21 had already been assigned to Founder Strategy Letter / 대표 전략 편지. B21 therefore remains unchanged.

Fresh sequential preflight at #987 creation found:

```text
B61 = StoryMemory (#673)
B62 = Padiem Chat (#713 and follow-up work)
B63 = Korean Clinical AI Egress Control Plane (#731)
B64 = no competing Business claim found before #987
```

The later-created conflicting product therefore moves forward to B64 instead of taking an older numbering gap.

## Number-collision precedent

> First established/canonical assignment keeps its Business number. A later-created conflicting Business moves to the next sequential unassigned Business number.

For future Businesses, propose/reserve a Business number before creating a numbered workspace or document pack.

## Product boundary

B64 is an AI earning/reward routing product for Korean-resident users. It normalizes domestic and global earning opportunities and constructs time/eligibility-aware routes across app-tech, offerwall missions, surveys, user tests, AI/data work and online side-work.

Key separation:

```text
TODAY ROUTE = immediately actionable eligible inventory
INCOME PIPELINE = application/qualification-dependent work
```

Reward runtime state where partner integration supports it:

```text
PENDING -> CONFIRMED -> REVERSED
```

Affiliate/business economics remain separate from user recommendation score.

## Current source / document migration

The Reward Router-owned working source and documents are being renumbered from B21/b21 to B64/b64 under #987. This does not authorize rewriting any Founder Strategy Letter source or history.

Google Drive source-document folder retains its Drive ID while its title and owned child-document identifiers are renumbered to B64.

The current implementation package has no canonical GitHub product source directory in this repository yet; do not invent or duplicate one solely to satisfy the Portal layout.

## Portal / deployment boundary

Per #778:

```text
NEW_CLOUDFLARE_PAGES_PROJECT = NO
EXISTING_PAGES_DELETE_RENAME_REPURPOSE = NO
DNS_CUSTOM_DOMAIN_CHANGE = NO
apps/padiem-lab/** = NO CHANGE
PORTAL_BUILD_OR_WORKFLOW = NO CHANGE
DEPLOYMENT = DEFERRED_TO_BI_PORTAL
```

After registration is accepted, the Portal owner may aggregate the canonical B64 source at build time to `/b64/` without making the generated Portal artifact the source of truth.

## Runtime handoff

```text
PUBLIC_ENTRY_FILE = public/index.html
RUNTIME = Node-compatible HTTP runtime
STORAGE = transaction-safe persistent store required for production
IDENTITY = trusted authenticated user identity required for live money
CALLBACKS = signed partner postbacks + idempotent transaction handling
```

Current dynamic runtime paths are root-relative and will require a Portal-owned runtime adapter/proxy or a separately authorized B64 base-path adaptation before full `/b64/` runtime integration.

## Registration acceptance

- [ ] B21 Founder Strategy Letter remains unchanged.
- [ ] Reward Router-owned source/document identifiers use B64.
- [ ] Previous provisional alias B21 is recorded only as migration history.
- [ ] No B61/B62/B63 identity is reused.
- [ ] No older intentional gap is recycled.
- [ ] Registry/manifest review accepts B64 before treating it as canonical.
- [ ] No Cloudflare/DNS/Portal deployment mutation is performed by this registration work.

Refs #987 #778 #673 #713 #731
