# Padiem Chat — Business 62 Runtime

Padiem Chat is Padiem's Korean-first, general-user AI front door.

## Boundary

```text
Browser / API
→ Padiem Chat product boundary
→ Padiem AI Core ExecutionRuntime / StreamingExecutionRuntime
→ Business 14
→ selected provider / model
```

Padiem Chat owns the consumer-facing chat, continuity, Projects, bounded user-reference context, TaskMode semantics and product-profile state. B62 TaskModes are lightweight product presets, not reusable/installable Core Skills. Padiem AI Core owns the product-neutral execution request/result, streaming, normalized error and reusable evidence/runtime contracts. Business 14 owns provider adapters, provider keys, model catalogs, exact routing and upstream transport.

The B62 `LOW` / `MEDIUM` / `HIGH` product profiles are currently **UNASSIGNED** and Provider/model selection remains deferred. An unassigned product profile must not be documented or treated as a pretend executable Provider/model route.

## Source readiness is not Production activation

Repository code, browser controls and public readiness fields describe what B62 can support when the required bindings/configuration exist. They do **not** prove that a Production deployment has those capabilities activated.

The browser uses existing public status endpoints only as a visibility projection:

```text
/health
├─ web_tools_ready
├─ deep_research_ready
├─ auth_configured / history_store_bound
├─ projects_code_ready
├─ project_files_code_ready / project_file_store_bound
└─ saved_outputs_code_ready / saved_output_store_bound

/api/auth/status
├─ ready
├─ authenticated
├─ history_ready
└─ project_files_ready
```

Unavailable primary controls fail closed hidden. Available controls may remain visible while temporarily disabled/busy. This browser capability projection is presentation state only; it is not execution, ownership, approval or routing authority.

A capability is Production-active only when the deployed Worker has the required runtime mode, service/binding/configuration and server-side readiness. Source presence alone is insufficient.

## Runtime modes

### Mock (default)

```bash
PADIEM_CHAT_RUNTIME_MODE=mock \
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Mock mode makes zero upstream model calls and returns bounded preview copy.

### Business 14

```bash
PADIEM_CHAT_RUNTIME_MODE=b14 \
PADIEM_CHAT_B14_BASE_URL=https://<approved-b14-host> \
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

The browser never supplies a provider key or an upstream URL. For ordinary text completion and streaming, B62 converts its product-owned TaskMode state into a product-neutral Core `AgentProfile` + `ExecutionRequest`, then executes through Core `ExecutionRuntime` / `StreamingExecutionRuntime`. Core owns the reusable execution boundary and invokes Business 14 beneath that boundary.

B62 ordinary text does **not** currently use Business 14 `b14/auto` as an active routing decision. The historical `stream_text_auto` method name is a compatibility entrypoint: B62 resolves its own product policy first, and Provider/model assignment remains deferred until the relevant authority explicitly assigns it.

### Bounded image execution through Core

The former B62 low-level multimodal exception is closed by #1068. A single validated image-bearing request is converted by B62 into product-neutral Core inputs and executed through:

```text
B62 ImageAttachment + product TaskMode state
→ MultimodalExecutionRequest
→ MultimodalExecutionRuntime
→ B14MultimodalChatRequest
→ Business 14
```

B62 still owns attachment UX, the `ImageAttachment` product type, the image-capability fail-closed decision, and Korean user-facing errors. Core owns system-instruction composition, normalized model/routing policy, high-level multimodal execution metadata and safe execution errors. The existing low-level Core/B14 multimodal validator remains the single image payload validator.

This boundary does **not** assign an image-capable Provider/model. While the current product profile is unassigned or does not prove image capability, live image completion still fails closed before Business 14/provider dispatch.

## Attachments and document boundary

The browser-visible ephemeral composer attachment contract is defined by `static/attachment-capabilities.js`. It is intentionally bounded and separate from persistent Project files:

```text
Images:           JPEG / PNG / WebP, one attachment per request, up to 4 MiB
Text documents:   TXT / Markdown / CSV / JSON, one attachment per request,
                  UTF-8 text only, up to 96 KiB / 40,000 characters
Binary documents: PDF / DOCX / PPTX / XLSX, one attachment per request,
                  raw binary payload up to 2 MiB
```

Text-document content is wrapped as **untrusted reference data** inside the server-owned additional system context. It cannot select a provider, endpoint or model, and the full document text is not returned in public response metadata or written into ordinary conversation history.

PDF, DOCX, PPTX and XLSX are supported as ephemeral composer attachments through the existing completed `/api/chat` attachment contract. The browser validates the bounded raw file and sends base64 to the existing B62 server parser; the frontend does not reimplement document extraction, Core semantics, provider routing or a synthetic attachment-streaming bridge. Binary attachment content is request-scoped and is not persisted in ordinary conversation history.

Project files are a distinct persistence capability. They remain validated UTF-8 text files only; composer support for PDF/DOCX/PPTX/XLSX does **not** imply persistent binary Project-file support.

## Streaming versus completed transport

Transport choice is explicit and must not be inferred from the visual message lifecycle:

```text
attachment-free ordinary chat
→ browser requestStreaming(...)
→ /api/chat/stream (SSE)

attachment-bearing composer request
→ browser requestCompleted(...)
→ /api/chat (JSON completion)

orchestration-capable authenticated request
→ browser checks /api/orchestration/status
→ server /api/orchestration when applicable
→ otherwise ordinary /api/chat/stream
```

Attachment-bearing requests do not create a synthetic attachment SSE bridge. The browser message lifecycle may render a completed response into the same conversation UI, but that does not change the underlying transport contract.

The browser `chat-transport.js` remains network-oriented. Conversation/request epoch, selected attachment state and rendered message lifecycle remain app-owned rather than becoming transport authority.

## Theme and locale URL authority

Theme and locale are URL-authoritative browser presentation state. They are not persisted in `localStorage`, `sessionStorage` or cookies.

Current theme contract:

```text
?theme=light
?theme=dark
?theme=cinematic
?theme=padiem-home
?theme=padiem-glass
```

If `theme` is absent or invalid, the current default/fallback is `padiem-glass`. Glass supports `?glass=female|male`, with `female` as the fallback variant. During active chat, Padiem Glass switches from cinematic home behavior to the calmer `reading` presentation state; this is visual state only.

Current locale contract:

```text
?lang=ko
?lang=en
```

If `lang` is absent or invalid, the fallback is Korean (`ko`). Changing language updates the URL with `history.replaceState`; browser storage is not an authority. Static controls and existing dynamic controls are localized from the same locale state, while capability-dependent controls remain hidden when unavailable.

## Auth, history, Projects and Saved Outputs

Authentication defaults off. When Google OAuth and the D1 binding are actually provisioned, B62 supports:

```text
signed-in user
├─ recent conversations
├─ Projects
│  ├─ persistent project instructions
│  ├─ project-owned chats
│  └─ bounded project text files
├─ Saved Outputs / 저장한 답변
└─ signed HttpOnly session
```

Project text files use the same D1 binding as history and store validated UTF-8 text only. Current limits are 12 files per project, 40,000 characters per file and 160,000 stored characters per project. Original binary files and base64 payloads are not persisted.

Saved Outputs persist only user-selected assistant answer text. Current limits are 200 outputs per user, 100 characters per title and 32,000 characters per saved answer. List responses expose title/provenance/timestamps but not the stored answer body; full content is returned only from the owner-scoped detail endpoint.

Every completed assistant answer may be copied or downloaded locally as UTF-8 `.txt`. The `저장` action and Saved Outputs sidebar are exposed only when authenticated D1 persistence is actually available. Saved Outputs are **not automatically injected into future chats, Projects or model context**. Saving an answer is therefore a library action, not hidden memory.

Project/file/output access is owner-scoped server-side. Browser-supplied project, conversation, file or output identifiers never bypass ownership checks. Project instructions and file content are subordinate to Core security/tool rules and do not change Business 14 routing authority.

Voice/STT/TTS, image generation and PDF/DOCX/PPTX export are not claimed by this runtime. They remain deferred until a real, separately reviewed execution contract exists.

## Orchestration and approval bridge ownership

The browser may discover orchestration readiness through `/api/orchestration/status` and use product UI to present an approval pause. That UI is a projection/interaction surface, not approval authority.

In the Cloudflare Worker composition, `worker.py` installs orchestration routes with `install_orchestration_routes(...)` and builds the bridge from server-side Worker bindings. The canonical-subject bridge resolves the Shared Control Plane subject for Engine requests while preserving B62's product-local `usr_*` owner key for B62 history/snapshot ownership.

```text
Browser
→ B62 orchestration presentation + resume/cancel intent
→ B62 server orchestration routes/bridge
→ Padiem AI Engine / Core execution contract
→ Shared Control Plane identity/approval authority where required
→ Business 14 routing/provider boundary
```

The browser does not mint approval evidence, canonical subject identity, provider selection or tool execution authority. B62 must not reimplement Core/Engine/Control Plane shared semantics inside frontend state.

## Cloudflare Python Worker package

`worker.py` is the Cloudflare Worker entrypoint and `wrangler.toml` deliberately defaults the deployment to:

```text
PADIEM_CHAT_RUNTIME_MODE=mock
```

The deployed Worker creates the Starlette app from immutable Worker bindings through `settings_from_worker_bindings(self.env)`. It does not depend on browser-provided upstream configuration and it does not define an OpenRouter/provider-key binding.

The Worker composes optional D1 stores, the fixed B14 service binding transport and orchestration routes only from server-side bindings. Base application source can therefore contain Projects, Saved Outputs, orchestration and other code while a particular deployment still reports those capabilities unavailable.

Server-owned runtime configuration includes B14/web/auth settings, while the optional D1 binding name is:

```text
PADIEM_CHAT_DB
```

No fake D1 database ID is committed to `wrangler.toml`. Without the actual binding, persistence-dependent capabilities remain unavailable rather than falling back to in-memory production state.

`b14` mode without a valid B14 URL fails closed instead of silently falling back to mock. Production live-AI readiness additionally depends on the server-owned abuse/quota gate; source code or `b14` mode alone is not sufficient.

All responses receive `nosniff`, `DENY` frame policy and `no-referrer`; API, auth and health responses additionally receive `Cache-Control: no-store`.

## Public-release boundary

A deployed Worker is not automatically a public live-AI release. Anonymous live-provider access requires a separate abuse/cost gate with Cloudflare-side rate limiting or equivalent globally reliable controls, quota/spend limits and an emergency disable path. A per-isolate Python counter must not be treated as the public security boundary.

Production auth/history/Projects/project files/Saved Outputs also require the real D1 migrations and Google OAuth configuration. Repository code readiness is not a claim that those production resources are active.

## B62 boundary declaration (#1224)

```text
CURRENT_B62_SKILL_CLASSIFIED_AS_TASK_MODE = YES
REUSABLE_SKILL_AUTHORITY = P01_CORE
B62_TOOL_EXECUTION_AUTHORITY = NO
B62_TOOL_PRESENTATION_ONLY = TARGET
EVIDENCE_AUTHORITY_DUPLICATION = REDUCED_OR_EXPLICIT_COMPATIBILITY_ONLY
GROUNDING_NEW_SHARED_SEMANTICS = P01_ONLY
B14_ROUTING_REIMPLEMENTED = NO
CONTROL_PLANE_TRUTH_REIMPLEMENTED = NO
PRODUCTION_MUTATION = NO
```

B62 `TaskMode` values are product presets only. Tool execution, approval, auth, resource limits, handler registration, side-effect authorization and reusable Skill authority remain outside this product boundary. `grounding.py` is a compatibility adapter over Core grounding/evidence contracts; it must not introduce new shared orchestration semantics.

## Tests

```bash
python -m pytest -q
```

The test suite is deterministic and uses `httpx.MockTransport`; no provider network call is required.
