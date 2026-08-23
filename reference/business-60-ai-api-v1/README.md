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
4. an existing LoveTree hand-only gesture enters from the protagonist side;
5. deliberate physical `CONNECT` contact;
6. contact ripple + world-scale flash + short camera impulse;
7. API-core energy visibly tethers into the body;
8. continuing neural/electric flow through the protagonist;
9. eye/vision interface activation;
10. the environment splits vertically into CODE / VISION / VOICE capability worlds;
11. the three worlds fold/collapse into the spatial-control scene;
12. the face-free hand returns as a physical spatial controller;
13. pointer/touch-responsive AI surfaces can be grabbed and thrown with inertia;
14. spoken intent becomes routed code;
15. the cinematic world dissolves into a practical deal/source view.

Motion layers are isolated so they can be reviewed or removed without rewriting the base anchor:

- `cinematic-v2.css/js` = contact/world/gesture/inertia system;
- `cinematic-v3.css/js` = physical foreground hand contact + post-connect spatial-control hand;
- `cinematic-v4.css/js` = API-to-body charge, neural current and CODE/VISION/VOICE split-world transition.

## Cinematic timing contract

The current scroll timeline is intentionally explicit so later visual revisions can tune one beat without rewriting the full sequence.

```text
0.00–0.27  distant protagonist → camera approach
0.235–0.445 physical hand / API contact window
0.345–0.545 API tether → body charge
0.49–0.73  eye / vision activation
0.625–0.815 CODE / VISION / VOICE split-world transition
0.715–0.915 physical spatial-control hand + draggable/throwable surfaces
0.80–0.94  voice → intent → code
0.90+      AI API identity → information handoff
```

`CONNECT` remains a hard interaction gate: the post-contact sequence does not become active until the user deliberately activates the access core.

## Gesture asset boundary

The physical contact/control layer does **not** introduce a newly generated B60 image. `assets/gesture-touch.webp` is a cropped/optimized derivative of an existing LoveTree storyboard hand-only shot labelled `Touch the feeling`.

Because the source contains no face, it can sell foreground touch/control without visibly swapping the protagonist. The hand is used only as a short foreground layer around API contact and spatial-control moments.

LoveTree's existing `Supernova` benchmark was also consulted for camera/edit grammar. Its S10 reference describes a ~0.625s forward hand gesture toward the lens. The separate-person S10 image is **not** copied into this runtime.

Existing F01 `touched` / `talk` expression assets were inspected, but are not used in runtime because their face does not match the current protagonist closely enough.

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
