# Third-party notices — PADIEM Designer

## CopilotKit / OpenIntelligentUI

- Project: <https://github.com/CopilotKit/OpenIntelligentUI>
- Pinned commit: `8391a94c1c3939c679e40ddd7bfc08a9ef690e70`
- Upstream branch at pin: `main`
- License: MIT

The upstream repository is MIT licensed. This app reuses its **generative-UI
contract** and the assembly rules of its standalone document builder. The
reused contract, in this app's own terms:

| Upstream element | Where the upstream keeps it | What this app reuses |
|---|---|---|
| the tool name `generateSandboxedUi` | the CopilotKit runtime, declared to the model | the same tool name, in `app/model_route.py` |
| the parameter order `initialHeight`, `placeholderMessages`, `css`, `html`, `jsFunctions`, `jsExpressions` | the upstream system prompt | the same order, in `app/model_route.py` and `app/designer_prompt.py` |
| the activity content shape (`css`, `html`, `jsFunctions`, `jsExpressions`, `initialHeight`, `placeholderMessages`) | `apps/app/src/components/generative-ui/open-generative-ui/schema.ts` | the same channel names, in `app/contracts.py` |
| the standalone document assembly: generated CSS in its own style block, generated function declarations in one classic script at the top level, generated expressions joined into one async IIFE, and the closing-tag guards | `apps/app/src/components/generative-ui/export-utils.ts` (`assembleStandaloneHtmlFromActivity`, `escapeScriptClose`, `escapeStyleClose`) | the same rules, in `app/sandbox.py` |
| the sandbox rules (no same-origin access, no style or script block in the html channel, behaviour in the function and expression channels) and the interaction-quality rules | `apps/agent/src/prompt.py` | the same rules, in `app/designer_prompt.py` |
| the `Websandbox.connection.remote.sendPrompt` bridge the upstream prompt tells the model to call | the upstream websandbox rail | the same bridge name, in `app/sandbox.py`, forwarded to this app instead of being a no-op |

The MIT license text of the upstream project is reproduced in the pinned
checkout at `LICENSE`. Upstream source files are **not** vendored into this
repository; the contract and the rules are reimplemented against the pinned
commit, and this file records what was taken.

### PADIEM's own additions

The following are this app's work and are not upstream's:

* the PADIEM bridge that captures the generated UI's control values and reports
  them to the app, and the `window.sendPrompt` helper;
* the theme variables the generated CSS refers to;
* the PADIEM model-route interface, the B62 session reuse and the tenant
  separation;
* the interactive preview page and its client.

## PADIEM repositories reused

| Repository | What is reused | How |
|---|---|---|
| `apps/padiem-chat` | the signed `padiem_session` cookie contract and its verification | the B62 `auth` module is loaded from its own path and asked to verify the cookie; the cookie shape is not re-implemented |
| `packages/padiem-ai-core` | nothing is required by the Designer today | the app is independent of Core so it can run as a development preview |

## Python and JavaScript runtime dependencies

The app depends on `starlette`, `httpx` and `uvicorn` at runtime, and on
`pytest` and `playwright` for its tests. Those are ordinary PyPI packages with
their own licenses and are not vendored here.
