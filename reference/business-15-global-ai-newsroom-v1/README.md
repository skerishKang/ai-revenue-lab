# Proposed Business 15 · Global AI Newsroom

Phase 1 visual UI reference for **Global AI Newsroom / 글로벌 AI 뉴스룸**.

## Status

- Product status: proposed
- Phase: Phase 1 visual UI only
- Submission state: `UI_REVIEW_READY`
- UX: not approved
- Backend: frozen
- Scenario: explicitly synthetic; no live news ingestion or real organisation claims

## Visual direction

**Verification Atlas / 검증 아틀라스** — a map-led editorial operations table where country and specialist desks converge around one evidence-linked story dossier.

## Review states

1. Global Desk / 글로벌 데스크
2. Signal Intake / 신호 수집
3. Story Dossier / 스토리 도시에
4. Verification Room / 검증실
5. Edition Sheet / 발행 원고
6. Shift Handoff / 교대 인계
7. Mobile Briefing / 모바일 브리핑

Review controls only switch static visual states and replay the signature motion. They do not define approved UX.

## Run locally

```bash
python -m http.server 4173 --directory reference/business-15-global-ai-newsroom-v1
```

Open `http://127.0.0.1:4173/`.

## Version

All authored CSS and JavaScript references use:

```text
global-ai-newsroom-20260728-1
```

## Scope boundary

No crawler, RSS, social ingestion, WebSocket, authentication, database, persistence, LLM/fact-check API, publishing, analytics, notification, payment, or provider-routing feature is implemented.
