# Business 14 · Korean AI Platform — Visual Upgrade v2

Status: **Competitive demo · Draft visual reference**

Authority: Issue #378

## Product promise

여러 AI 회사를 각각 찾아다니지 않고, 하나의 한국어 화면에서 모델을 발견하고 Provider 키를 연결하고 직접 시험한 뒤 하나의 OpenAI-compatible endpoint로 사용할 수 있습니다.

## Evidence goal

```text
VISUAL_DESIRABILITY
INVESTOR_STORY
COMPETITIVE_DEMO
```

## What this reference changes

The current canonical app contains valuable runtime work, but its interface is fragmented across Provider Home, Playground and Workspace and visually reads as an operator console.

This reference tests a personal-first replacement:

```text
시작
→ 목적 또는 모델 선택
→ Provider 키 연결
→ Route Trace 확인
→ 첫 요청 실행
→ endpoint와 코드 복사
```

Top-level navigation is reduced to:

```text
시작 · 모델 · 활동 · 개발자
```

## Visual concept

**Model Switchboard / 나의 AI 연결판**

Requests visibly travel through a restrained route line from the user's intent to an eligible model and Provider. The route itself is the primary product visualization rather than a wall of dashboard cards.

## Demo states

- Start / first request
- Model explorer
- Model detail and integrated playground
- Provider key connection
- Automatic route decision
- No-safe-route recovery
- Personal activity
- Mobile navigation and focused sheets

## Runtime boundary

This workspace is deterministic frontend evidence.

```text
real Provider call: no
real secret storage: no
real authentication: no
real billing: no
real Router Core: no
canonical app mutation: no
```

Simulated behavior is documented here instead of repeated across every screen.

## Local review

Serve through localhost; do not review with `file://`.

```bash
cd reference/business-14-korean-ai-platform-v2
python -m http.server 8140
```

Open `http://127.0.0.1:8140/`.

## Files

- `PRODUCT_CONTRACT.md`
- `REFERENCE_BOARD.md`
- `REFERENCE_NOTES.md`
- `IMAGE_SOURCES.md`
- `MOTION_SPEC.md`
- `index.html`
- `styles/main.css`
- `scripts/app.js`
- `tests/validate.py`

## Non-actions

No merge, deployment, Router backend implementation or Business 54 TUI implementation is authorized by this reference.