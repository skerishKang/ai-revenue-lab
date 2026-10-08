# Third-Party Notices — business-66-padiem-quote-v1

This business reference contains third-party material requiring attribution.
It is recorded here rather than in a root-level file because the material is
served only by this app.

## @google/genai — Google (Apache License 2.0)

```text
UPSTREAM_PACKAGE=@google/genai
UPSTREAM_VERSION=2.24.0
UPSTREAM_REGISTRY=https://registry.npmjs.org/@google/genai/-/genai-2.24.0.tgz
UPSTREAM_REPO=googleapis/js-genai
UPSTREAM_LICENSE=Apache-2.0
LOCAL_LICENSE_COPY=./voice-sdk/licenses/google-genai.APACHE-2.0.txt
ADAPTATION_TYPE=UNMODIFIED_UPSTREAM_BUILD_OUTPUT
BUILT_BY=./voice-sdk/build-voice-sdk.mjs
ARTIFACT=./vendor/genai-live-2.24.0.js
ARTIFACT_SHA256=18fb1456b794228b2202b94c8fea109997aab5517cc14cf33944acd90468e520
ARTIFACT_BYTES=905666
```

The artifact is produced from the unmodified upstream browser entry
(`@google/genai/web`) by a locked, offline esbuild bundle. No upstream source
line is edited. `voice-sdk/PROVENANCE.json` carries the same hash and is
verified in CI by rebuilding and byte-comparing (`node voice-sdk/build-voice-sdk.mjs --check`).

Purpose: the Gemini Live audio-in / transcription-out session used by the
`#easyComposer` microphone (#3404). Nothing is loaded at page view; the browser
reaches the bundle with a lazy dynamic import only after the user presses the
microphone button.

## p-retry — Sindre Sorhus (MIT) and retry (MIT)

Both are static dependencies of the upstream SDK entry and are inlined into the
same artifact by the bundler.

```text
UPSTREAM_PACKAGE=p-retry
UPSTREAM_VERSION=4.6.2
UPSTREAM_LICENSE=MIT
LOCAL_LICENSE_COPY=./voice-sdk/licenses/p-retry.MIT.txt

UPSTREAM_PACKAGE=retry
UPSTREAM_VERSION=0.13.1
UPSTREAM_LICENSE=MIT
LOCAL_LICENSE_COPY=./voice-sdk/licenses/retry.LICENSE.txt
```

## Design reference (no code or runtime dependency)

```text
REFERENCE_REPO=skerishKang/global-classroom
REFERENCE_SHA=299c8e7830f6e4aa0c5202ca5591f240487c5c38
RELATIONSHIP=PORTED_ALGORITHMS_ONLY
RUNTIME_DEPENDENCY=NO
```

`mergeLiveTranscriptChunk`, the `float32ToInt16` / `arrayBufferToBase64`
helpers, the microphone and `AudioContext` lifecycle, the silent warm-up chunk,
and the browser `SpeechRecognition` restart behaviour are ported from that
project's hooks. B66 does not read, import, or build against that repository at
run time; only the pinned `@google/genai` package above is shipped.
