# Product contract

## Identity

```text
Business: 54
Stable slug: korean-ai-code-agent
English: Korean AI Code Agent
Korean: 한국형 AI 코드 에이전트
Primary market: personal developers
Platform dependency: Business 14 · Korean AI Platform
```

## Product promise

저장소를 열고 한국어로 작업을 설명하면 에이전트가 계획·검색·수정·테스트·오류 복구를 수행하고, 사용자는 적용 전 diff와 근거를 직접 확인한다.

## Ownership boundary

### Business 54 owns

- repository and task experience;
- Plan / Build / Review modes;
- context and affected-file presentation;
- bounded edit preview;
- command and test evidence;
- failure, correction and retry journey;
- diff review and user acceptance;
- foreground permission UX;
- Korean-first personal developer interface.

### Business 14 owns

- external, domestic and local model access;
- Provider adapters and health;
- BYOK and future platform keys;
- model catalog;
- usage and cost visibility;
- Router Core selection, constraints and fallback;
- no-safe-route result.

Business 54 must not create a second Provider registry, billing system or independent model-router brand.

## Deterministic demo case

```text
Repository: seonbi-notes — synthetic
Task: 저장 버튼을 누른 뒤 성공 메시지가 두 번 표시되는 오류를 수정해줘.
Affected files:
- src/save-note.js
- tests/save-note.test.js
Initial result: duplicate success event
First test: 1 failed / 7 passed
Correction: remove duplicate dispatch and retain one announcement
Final test: 8 passed
```

## Modes

### Plan

- inspect synthetic repository;
- identify affected files;
- explain plan;
- no mutation claim.

### Build

- preview bounded edits;
- show approved synthetic test command;
- expose one deterministic failure;
- apply deterministic correction;
- show passing evidence.

### Review

- show final diff;
- show route and test evidence;
- accept, reject or request another pass.

## Route contract

The demo exposes:

- automatic Business 14 route;
- manual route choice;
- local-first preference;
- explicit external fallback toggle;
- Plan and Build model identities;
- synthetic usage estimate;
- no-safe-route state.

No route is live in this Phase.

## Permission contract

Display read, write, command, network and Git permissions separately.

Initial demo policy:

```text
read: allowed for synthetic repository
write: preview only
command: deterministic simulation only
network: denied
Git push/merge/deploy: denied
```

Never describe this Phase as sandboxed execution.

## Acceptance

The demo passes product review only when a first-time reviewer can complete the full task journey and correctly state:

1. Business 54 is the coding-agent application;
2. Business 14 supplies models and routing;
3. the first market is individual developers;
4. all repository, model and test behavior in this Phase is synthetic;
5. final application remains a user decision.
