# StoryMemory v3.4.10-rc1 — Browser Session Hydration Fix

- Candidate: `v3.4.10-rc1`
- Build: `sm093-browser-session-hydration-fix`
- Deployment: `DEFERRED_TO_BI_PORTAL`
- Baseline: `StoryMemory_CloudflarePreview_v3.4.9.zip`
- Baseline SHA256: `d7709086aff0a1a9045d80ad3fb241404397fea3c40aad26126d4984d7dd44ca`

## Runtime patch

The only runtime source change is the boot hydration call:

```js
restoreSessionFromUnifiedStore({navigate:false})
```

becomes:

```js
restoreSessionFromUnifiedStore({navigate:true})
```

This restores the persisted active screen after reload while preserving the existing exact-resume data and hydration persistence guard.

## Integrity scope

- `dist/content/**`: unchanged, missing `0`, extra `0`
- Existing runtime/public files changed: `dist/index.html` only
- Candidate metadata changed: `dist/version.json`
- No Bible WEB, Crime and Punishment, Pride and Prejudice, or Alice in Wonderland static readiness was added.
- Aeneid, Metamorphoses, Paradise Lost, and Divine Comedy remain static-runtime available; their direct UI exposure gap is retained as `CURRENT_STATIC_UI_EXPOSURE_GAP`.

## Release posture

Non-deployment release candidate only. No repository, production corpus, Neon, Cloudflare Portal/DNS, or deployment mutation.
