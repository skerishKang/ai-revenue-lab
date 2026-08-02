# Business 54 · Korean AI Code Agent

개인 개발자를 위한 한국어 우선 AI 코드 에이전트의 경쟁형 coded demo입니다.

## Product position

```text
Business 54 · Korean AI Code Agent
→ personal developer workbench
→ consumes Business 14 · Korean AI Platform
→ Business 14 Router Core selects or falls back across external, domestic and local models
```

이 작업공간은 과거 Business 54 · AI Model Router를 계승하는 독립 라우터 제품이 아닙니다. 모델 접근·Provider·사용량·라우팅은 Business 14가 소유하며, Business 54는 저장소 작업 경험을 소유합니다.

## Demo journey

```text
한국어 작업 요청
→ 저장소 탐색
→ 계획
→ Business 14 모델 경로
→ 제한된 수정 미리보기
→ 합성 테스트 실패
→ 수정
→ 테스트 통과
→ diff 검토
→ 사용자 승인·거절·재작업
```

## Run

정적 파일이므로 로컬 HTTP 서버에서 여십시오.

```bash
cd reference/business-54-korean-ai-code-agent-v1
python -m http.server 4173
```

그다음 `http://127.0.0.1:4173/`을 엽니다.

## Validate

```bash
python tests/validate.py
node --check scripts/app.js
```

## Runtime boundary

- deterministic synthetic repository only;
- no live model call;
- no real file or shell access;
- no Git mutation;
- no API key, account, storage, billing or analytics;
- no external runtime asset or request;
- no OpenCode source reuse in this Phase.

## Current state

```text
COMPETITIVE_DEMO_REVIEW_READY
WEB_IMPLEMENTED
LOCAL_INDEPENDENT_VALIDATION_PENDING
BUSINESS_14_DEPENDENCY_EXPLICIT
SYNTHETIC_ONLY
PR_OPEN_DRAFT_UNMERGED
DO_NOT_MERGE
```
