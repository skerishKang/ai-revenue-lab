# Business 60 · AI API — Cinematic Anchor v1

Issue: #652  
Parent registration: #650 / Draft PR #651  
Evidence lane: `VISUAL_DIRECTION` + minimal information handoff  
Target gate: `ANCHOR_REVIEW_READY`

## Evidence question

Can AI API discovery begin as an interactive science-fiction film and still land in a precise, source-forward information surface without becoming a generic SaaS directory?

## Current anchor

The prototype follows one continuous narrative axis:

1. a lone woman in a planetary / deep-space environment;
2. camera approach;
3. a floating API access state is discovered;
4. deliberate `CONNECT` activation;
5. contact ripple + world-scale flash + short camera impulse;
6. continuing neural/electric flow;
7. eye/vision interface activation;
8. CODE / VISION / VOICE capability worlds emerge;
9. pointer/touch-responsive spatial AI surfaces;
10. surfaces can be thrown with inertial gesture motion;
11. spoken intent becomes routed code;
12. cinematic world dissolves into a practical deal/source view.

The second motion pass is isolated in `cinematic-v2.css` and `cinematic-v2.js` so it can be reviewed or removed without rewriting the base anchor.

## Motion reference boundary

LoveTree's existing `Supernova` benchmark work was consulted for camera/edit grammar. Its S10 reference describes a ~0.625s forward hand gesture toward the lens. The separate-person S10 image is **not** copied into this runtime because doing so would break protagonist continuity.

Adopted motion ideas:

- contact should feel like a brief physical beat, not a normal button click;
- foreground-to-lens gesture energy;
- flash/impact transition;
- rapid world-state changes while the protagonist stays the narrative axis;
- physical-feeling spatial UI motion and inertia.

Existing F01 `touched` / `talk` expression assets were also inspected, but are not used in runtime because their face does not match the current protagonist closely enough.

The protagonist assets actually used here are existing LoveTree/owner-created materials, optimized for this review surface. No new generated imagery is introduced by this prototype.

## Product boundary

This is B60 discovery/verification UI only.

```text
B60 = discover / verify / compare / explain access
B14 = execute / route / meter / observe model calls
```

No provider calls, API-key storage, auth, database, model execution, billing, or B14 runtime code are present.

## Information truth boundary

The first content object is Vercel / GLM 5.2.

Facts rendered as verified come from Vercel's official GLM 5.2 AI Gateway page and official `vercel-labs/fx` source. The owner-reported `fx` free-through-2026-08-27 promotion remains visibly separated as `PENDING_WEB_VERIFICATION` until the exact promotion has a captured primary source.

## Run locally

Serve this directory over a static HTTP server, for example:

```bash
python -m http.server 4173
```

Then open `http://127.0.0.1:4173/`.

## Verification boundary

Static verification covers JS syntax, local asset/script/style references, source-confidence markers, and isolated diff scope.

Independent rendered browser visual QA is still required. Owner review is required before any visual-direction lock.

## Review status

```text
ANCHOR_REVIEW_READY = pending owner review
ANCHOR_DIRECTION_LOCKED = no
ARCHETYPE_SYSTEM_PASS = no
FULL_EXPANSION_ALLOWED = no
BACKEND = none
PROVIDER_CALLS = 0
```
