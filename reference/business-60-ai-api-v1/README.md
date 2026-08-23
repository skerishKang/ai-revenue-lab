# Business 60 · AI API — Cinematic Anchor v1

Issue: #652  
Parent registration: #650 / Draft PR #651  
Evidence lane: `VISUAL_DIRECTION` + practical discovery/retention surface  
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
14. the protagonist's spoken command becomes a live waveform;
15. the waveform contracts into extracted intent tokens;
16. intent tokens physically assemble into an INTENT → ACCESS → MODEL → API route graph;
17. the route graph dissolves into floating code strips;
18. code strips collapse into a single constructed API object;
19. the constructed object yields to the `AI API` identity;
20. the cinematic world dissolves into a practical access-discovery product surface.

Motion/product layers are isolated so each pass can be reviewed or removed independently:

- `cinematic-v2.css/js` = contact/world/gesture/inertia system;
- `cinematic-v3.css/js` = physical foreground hand contact + post-connect spatial-control hand;
- `cinematic-v4.css/js` = API-to-body charge, neural current and CODE/VISION/VOICE split-world transition;
- `cinematic-v5.css/js` = spoken waveform → intent extraction → route graph → code strips → constructed API object;
- `product-v6.css/js` = post-cinematic `NOW / EXPIRING / MODELS / ACCESS` discovery surface;
- `data/access-signals.js` = current official-source access catalog used by v6;
- `product-v7.css/js` = local SAVE / WATCHLIST / CHANGES retention layer;
- `data/signal-history.js` = append-only-style history baseline for truth-preserving change tracking.

## Cinematic timing contract

```text
0.00–0.27   distant protagonist → camera approach
0.235–0.445 physical hand / API contact window
0.345–0.545 API tether → body charge
0.49–0.73   eye / vision activation
0.625–0.815 CODE / VISION / VOICE split-world transition
0.715–0.915 physical spatial-control hand + draggable/throwable surfaces
0.785–0.820 voice waveform / listening
0.820–0.850 spoken intent extraction
0.850–0.885 INTENT → ACCESS → MODEL → API route assembly
0.885–0.925 route → code-strip construction
0.925–0.955 code → constructed API object
0.955+       AI API identity → information handoff
```

`CONNECT` remains a hard interaction gate.

## Post-cinematic product surface

```text
NOW       = currently usable verified free/credit/access paths
EXPIRING  = only offers with a primary-source-confirmed expiry date
MODELS    = model/access rows with context, price/access summary
ACCESS    = grouped API / gateway / playground / router / cloud paths
WATCHLIST = locally saved access signals in the current browser
CHANGES   = baseline + later verified before→after history events
```

### V7 retention behavior

- `SAVE` is available on current access cards;
- saved ids are persisted in `localStorage` under `b60.ai-api.watchlist.v1`;
- if browser storage is blocked/corrupt, the discovery UI stays alive and the watchlist degrades to session-only behavior;
- `WATCHLIST` is deliberately local-only at this phase: no auth/account/database has been introduced;
- the browser records a last-visit timestamp only for future “since your last visit” UX; it is not sent anywhere;
- `CHANGES` reads `data/signal-history.js` and distinguishes baseline/pending records from actual verified change events.

### Truth boundary for history

2026-08-23 is the first B60 access-catalog snapshot. V7 does **not** fabricate yesterday-vs-today changes.

Current history types:

```text
FIRST_SEEN               = initial baseline capture, not a change
PENDING_CLAIM_RECORDED   = an unverified promotion claim was recorded separately
PRICE_CHANGED            = reserved for future verified before→after price change
FREE_TIER_CHANGED        = reserved for future verified free-allocation change
EXPIRES_AT_CHANGED       = reserved for future verified expiry change
ACCESS_CHANGED           = reserved for future verified access-method change
```

Only events with a real prior snapshot can become `CHANGED` in the UI.

## Initial official-source catalog

Captured on 2026-08-23:

- Vercel AI Gateway / GLM 5.2 — free users who have not made a payment get $5 credits every 30 days; GLM 5.2 model id `zai/glm-5.2`, 1M context;
- Google Gemini Developer API — official Free tier with limited eligible-model access, free input/output tokens and AI Studio access;
- Cloudflare Workers AI — 10,000 neurons/day free allocation;
- Groq API — official Free Plan with model-specific rate limits;
- OpenRouter — Free plan and `openrouter/free` free-model router.

The owner-reported `fx` free-through-2026-08-27 claim remains `PENDING_WEB_VERIFICATION`; the product does not fabricate an expiry countdown for it.

## Voice-build visual contract

```text
VOICE → INTENT → ACCESS ROUTE → MODEL → CODE → CONSTRUCTED API
```

The sequence explains what API access enables; it does not mean B60 itself executes provider calls.

## Gesture asset boundary

`assets/gesture-touch.webp` is a cropped/optimized derivative of an existing LoveTree storyboard hand-only shot labelled `Touch the feeling`. No new B60 image was generated for these passes. Different-person S10/F01 visual assets remain excluded from runtime.

## Product boundary

```text
B60 = discover / verify / compare / explain access
B14 = execute / route / meter / observe model calls
```

No provider calls, API-key storage, auth, database, model execution, billing, or B14 runtime code are present.

## Information truth boundary

Verified facts are shown as `VERIFIED_OFFICIAL_WEB`. Promotion/end-date claims without captured primary evidence stay visibly pending. `EXPIRING` intentionally shows no verified expiry when none exists rather than guessing a deadline. `CHANGES` likewise refuses to invent historical deltas without a prior verified snapshot.

## Run locally

```bash
python -m http.server 4173
```

Then open `http://127.0.0.1:4173/`.

## Verification boundary

Static source review covers local script/style wiring, source-confidence markers, isolated diff scope, interaction ownership, and storage-failure fallback. Independent rendered browser visual QA is still required before direction lock.

## Review status

```text
ANCHOR_REVIEW_READY = pending owner review
ANCHOR_DIRECTION_LOCKED = no
ARCHETYPE_SYSTEM_PASS = no
FULL_EXPANSION_ALLOWED = no
BACKEND = none
PROVIDER_CALLS = 0
AUTH = none
WATCHLIST_STORAGE = browser-local only
CHANGE_HISTORY = baseline only until a later verified snapshot exists
```
