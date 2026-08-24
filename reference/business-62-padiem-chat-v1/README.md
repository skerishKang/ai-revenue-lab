# Business 62 — Padiem Chat / 파디엠 챗

Status: `PHASE_1_ANCHOR_IMPLEMENTATION`

Parent product decision: GitHub Issue #713

## Product promise

> 파디엠 홈페이지에서 누구나 설명 없이 바로 질문하고, 검색하고, 파일을 올리고, 필요한 결과를 얻을 수 있는 파디엠의 기본 AI.

The primary user is an ordinary Korean user, including a parent-generation user who should not need to know model/provider terminology.

## Current evidence question

Can a non-technical user understand the first screen and start a useful-looking chat without any onboarding explanation?

## Phase 1 scope

This workspace is a deterministic frontend review slice only.

Implemented review states:

- `?state=home`
- `?state=chat`
- `?state=search`
- `?state=attachment`
- `?state=error`
- mobile uses the same states through responsive CSS

The default experience also supports deterministic local interactions:

- compose/send a prompt;
- click starter prompts;
- enable a web-search visual state;
- attach/remove a synthetic file chip;
- view a synthetic answer and source-card pattern;
- exercise an error/retry pattern;
- open/close the mobile sidebar.

## Truth boundary

No model, provider, search engine, file service, account, database or API is connected in this Phase 1 reference.

Every assistant response is labeled `데모 응답`, and the composer notes that this is a pre-runtime UX preview.

## Architectural boundary

```text
B62 Padiem Chat
= consumer-facing conversation / projects / UX

B14 Korean AI Platform
= model access / provider routing / execution infrastructure

B60 AI API
= free/API/provider discovery and verification
```

Do not duplicate B14 execution adapters inside B62.

## Local review

From this directory:

```bash
python -m http.server 8762
```

Then open:

```text
http://127.0.0.1:8762/
http://127.0.0.1:8762/?state=chat
http://127.0.0.1:8762/?state=search
http://127.0.0.1:8762/?state=attachment
http://127.0.0.1:8762/?state=error
```

Static contract test:

```bash
node --test tests/static-contract.test.cjs
```

## Next gate

Required before any runtime work:

1. desktop rendered review;
2. 390px mobile rendered review;
3. owner anchor direction verdict;
4. only after that, define the B62 → B14 live chat handoff.

No Production deployment is authorized by this workspace alone.
