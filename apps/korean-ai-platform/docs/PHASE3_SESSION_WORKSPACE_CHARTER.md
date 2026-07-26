# Phase 3: Korean-First Session Workspace Pilot

## Product Objective

Phase 1 validated that a single BYOK gateway can call an external provider.
Phase 2 extended that to multiple providers with deterministic model routing.

Phase 3 delivers a **Korean-first browser workspace** where non-technical users can
select a model, enter their Provider API key, and carry on a multi-turn conversation
— all without storing keys, prompts, or responses on the server.

> A Korean user opens `/workspace`, selects a model, enters their key once,
> and chats. Keys live only in JS memory. Reloading the page clears everything.

## Korean-First Language

Canonical policy: `docs/BUSINESS14_LANGUAGE_POLICY.md`

Behaviour:
- Default: `ko-KR`
- Unknown/empty locale → `ko-KR`
- Invalid locale → `ko-KR`
- User explicitly switches to `en` → English where available
- Missing English translation → Korean fallback
- Technical identifiers, Provider names, model IDs remain in English

## In Scope

- `/workspace` page with Korean-first UI
- Model selection from Phase 2 registry (or legacy single-provider)
- Provider API key via password input, held in JS memory only
- Multi-turn conversation: messages accumulate in JS memory
- `POST /workspace/api/chat` proxy to Phase 2 chat completions
- Phase 3 `locale.py` i18n module (ko-KR primary, en optional)
- XSS-safe rendering: `textContent`, no `innerHTML` for user/assistant content
- Key isolation: one model → one provider → one key
- Cost truthfulness: `확인 불가` (unknown), never `0원`
- Phase 0, 1, 2 compatibility

## Session-Only Contract

| Item | Persistence | Cleared On |
|------|-------------|------------|
| Messages | JS memory only | Reload, New Chat |
| Provider API Key | JS memory only | Reload, explicit Clear Key |
| Locale preference | Cookie (`locale_preference`) | Never (user preference) |

## API Reuse

The workspace does NOT introduce a new chat completions endpoint.
All conversation requests go through the existing:

```
POST /api/pilot/v1/chat/completions
```

via the `POST /workspace/api/chat` proxy, which:
1. Extracts and validates the provider key from `X-Business14-Provider-Key`
2. Validates the request body
3. Routes via `resolve_route()`
4. Calls the provider adapter with fake-transport support

## Non-Goals

- User accounts, authentication, or multi-tenant isolation
- Persistent conversation storage (DB, file, server session)
- Persistent API key storage (localStorage, sessionStorage, cookies)
- Streaming or tool calling
- Billing or credit sales
- Production SLA
- End-to-end encryption
- Image/file upload
- Email/password auth
- Social login

## Relation to Prior Phases

| Phase | Focus | Status |
|-------|-------|--------|
| 0 | UI concept & 8-model catalog | Preserved |
| 1 | Single BYOK Gateway | Preserved |
| 2 | Multi-provider routing | Preserved (used by workspace) |
| 3 | Korean session workspace | **This phase** |

## Known Limitations

- No server-side conversation persistence (page reload loses chat)
- No streaming or real-time token display
- DNS rebinding protection not implemented
- Mobile 390px overflow not fully verified in automated tests
- Browser verification deferred (environment-limited)
