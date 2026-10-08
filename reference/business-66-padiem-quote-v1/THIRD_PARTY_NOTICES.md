# Third-Party Notices — business-66-padiem-quote-v1

This business reference contains third-party material requiring attribution.
It is recorded here rather than in a root-level file because the material is served only
by this app.

## skerishKang/global-classroom — the interview voice engine (reused unmodified)

The B66 microphone feature does not implement speech recognition. It ships the interview
engine that Global Classroom runs in production, copied without a single edited line.

```text
UPSTREAM_REPO=skerishKang/global-classroom
UPSTREAM_SHA=299c8e7830f6e4aa0c5202ca5591f240487c5c38
UPSTREAM_PATH_HOOK=hooks/useInterviewLive.ts
UPSTREAM_PATH_UTILS=utils/audioUtils.ts, utils/interviewTranslationSessions.ts, utils/interviewTranslationRouter.ts
LOCAL_COPY=./voice-interview/upstream/   (same relative layout, so no import line was touched)
ADAPTATION_TYPE=UNMODIFIED_VERBATIM_COPY
DEPLOYED_COMPARISON=https://7-global-classroom.netlify.app/assets/index-BhOzGF71.js
DEPLOYED_COMPARISON_RESULT=10/10 engine fingerprints matched this source (model ids,
                           PCM mime, /api/live-token, browser-fallback copy,
                           silenceDurationMs, custom vocabulary); 3 negative probes absent
LOCALLY_WRITTEN_FOR_THIS=bridge.mjs only — the React mount seam
```

Features of the upstream module that B66 deliberately does **not** enable — switched off by
constructor arguments, never by editing upstream code:

```text
translation      = off (translationTargets: []) → no Live Translate session, no extra token
language detect  = not wired → the engine's own languageCode is the only source
Groq fallback    = refused → the mount stops the session if the engine reports that backend,
                   and B66 registers no /api/transcribe route
```

Updating this engine means re-copying from upstream and re-running the build, not patching
a local fork. `tests/voice-reuse-bundle.test.cjs` fails when a vendored file stops
matching the hash recorded in `voice-interview/PROVENANCE.json`.

## @google/genai — Google (Apache License 2.0)

```text
UPSTREAM_PACKAGE=@google/genai
UPSTREAM_VERSION=2.24.0        (the version Global Classroom resolves)
UPSTREAM_REGISTRY=https://registry.npmjs.org/@google/genai/-/genai-2.24.0.tgz
UPSTREAM_REPO=googleapis/js-genai
UPSTREAM_LICENSE=Apache-2.0
LOCAL_LICENSE_COPY=./voice-interview/licenses/google-genai.APACHE-2.0.txt
```

## react / react-dom — Meta (MIT)

```text
UPSTREAM_PACKAGE=react, react-dom
UPSTREAM_VERSION=19.2.3        (the version Global Classroom renders with)
UPSTREAM_LICENSE=MIT
LOCAL_LICENSE_COPY=./voice-interview/licenses/react.MIT.txt, ./voice-interview/licenses/react-dom.MIT.txt
```

`react-dom/client` exists only because the reused engine is a React hook. The rest of B66
stays a classic-script page with no framework and no build step of its own.

## p-retry (MIT) and retry (MIT)

Static dependencies of the SDK entry, inlined by the bundler.

```text
UPSTREAM_PACKAGE=p-retry  UPSTREAM_VERSION=4.6.2  UPSTREAM_LICENSE=MIT
LOCAL_LICENSE_COPY=./voice-interview/licenses/p-retry.MIT.txt
UPSTREAM_PACKAGE=retry    UPSTREAM_VERSION=0.13.1 UPSTREAM_LICENSE=MIT
LOCAL_LICENSE_COPY=./voice-interview/licenses/retry.LICENSE.txt
```

## The shipped artifact

```text
BUILT_BY=./voice-interview/build-voice-interview.mjs
         (esbuild 0.25.12 — the pin this repository already uses in
          apps/padiem-desktop-shell; locked npm ci --ignore-scripts; no network; no CDN)
ARTIFACT=./vendor/b66-voice-interview-299c8e78.js
ARTIFACT_SHA256=7e32c50951bb301cc705d2a236ded493aa4a1bb4c553806e4a92216c760c20b6
ARTIFACT_BYTES=600424
REPRODUCIBILITY=node voice-interview/build-voice-interview.mjs --check, run in CI: the
                rebuild must be byte-identical and the vendored files must still match
LOADED=lazily, on the first microphone press; no framework code loads at page view
SAME_ORIGIN=YES   EXTERNAL_CDN=NO
```

## What stayed B66's own

The quote generator, login/session handling, the quote conversation, the existing auth,
quota and permission boundaries, and the PDF paths are untouched by this lane.
`voice-gemini.js` remains B66's server-side mint and keeps the verified-session gate and
the pinned mint host; it is additionally exposed at `/api/live-token` so the reused engine
needs no edit.
