# PADIEM 의원3종 독립 앱 (padiem-council-apps)

PADIEM 의원3종(축사·인사말 / SNS 홍보 / 회의정리·활동집)을 Chat/Claw 화면과
별도의 사용자 진입점으로 제공하는 독립 앱 기반이다. 세 기능은 각각 독립 모듈이며
(`static/council-app.js`의 `speech` / `sns` / `meeting`), 임미란 의원
홈페이지(`apps/padiem-chat/static/councillor/`)·의원3종·PADIEM Chat/Claw는
서로 다른 진입점을 유지한다.

## 제품 구성

| 모듈 | 기능 | 원본 계약 |
| --- | --- | --- |
| `speech` | 축사·인사말 초안 작성 | util-menu.js `buildPrompt` 템플릿 이식 |
| `sns` | SNS 홍보 콘텐츠(블로그/페이스북/인스타그램) 초안 | util-menu.js SNS `gen` 템플릿 이식 |
| `meeting` | 회의정리·활동 기록·책/활동집 초안 | util-menu.js 회의/활동집 템플릿 이식 |

## 재사용한 기존 PADIEM 계약 (신규 제작 없음)

- **AI 실행**: `POST /api/chat` — 기존 공용 채팅 경로(B14 모델 라우터,
  모델 정책, UsageGate, 검증된 세션). 요청 본문은 기존 util 계약과 동일한
  `{messages, mode:"auto", tier}`이며 티어 선택 규칙도 동일하다.
- **저장**: `GET|POST /api/projects`, `GET|POST /api/projects/{pid}/files`,
  파일 상세 `GET /api/projects/{pid}/files/{fileId}` — 기존 프로젝트 파일
  저장 계약. 이 앱은 새 테이블·마이그레이션·D1·R2를 만들지 않는다.
- **인증**: 세션 쿠키(`credentials: "include"`)와 `GET /api/auth/status`.
  인증 확인이 실패하면 도구를 열지 않는다(fail-closed). 인증 검증을
  우회하지 않는다.

## Chat/Claw 운영 변경 없음

이 앱은 `apps/padiem-chat/**`의 어떤 파일도 수정하지 않았다. 라우트 등록,
`app_factory.py`, `worker.py`, `wrangler.toml` 변경 0건이므로 Chat/Claw의
배포 번들과 실행 경계가 변하지 않는다. 이 앱 자체는 자기 완결 정적
진입점(자체 pyproject·테스트·CI)이며 `padiem_ai_core` 등 저장소 공용
패키지를 import하지 않는다.

## 캘린더 의도분류와의 충돌 방지

공용 `/api/chat`은 네이티브 캘린더 의도분류를 먼저 돌린다. 이 앱은 기존
util과 동일하게 `timezone`·`calendar_turn_id`를 보내지 않고 `{messages,
mode, tier}`만 보내므로, 캘린더 게이트의 추가 필드 요구에 걸리지 않는다.
기능 식별자(제품 scope) 도입은 아래 "미연결" 항목의 후속 작업으로 분리했다.

## 미연결 상태 (정상 동작으로 표시하지 않는 항목)

- **독립 Worker·D1·도메인 배포**: 이번 PR은 코드·테스트 기반이다. 별도
  Worker/도메인 배포는 `same_origin_guard` 계약과 Control Plane 제품
  허용목록을 검증한 뒤 별도 작업으로 진행한다.
- **Business 번호**: 신규 Business 번호는 임의로 확정하지 않았다.
  `BUSINESS_REGISTRY.md` 등록 절차가 필요한 미확정 항목이다.
- **제품 식별자(product_scope)**: 이 앱의 호출은 현재 util 계약과 동일하게
  공용 `/api/chat`에 제품 scope 없이 들어간다. `KNOWN_PRODUCT_SCOPES`·
  `dispatch_preinstruction` 등록이 선행되는 별도 후속 작업이다.
- **SNS 사진 저장 연결**: SNS 모듈은 텍스트 초안 계약만 사용한다. 사진
  구성·로스터 계약(#5728, LOCAL 1 PR #5768)은 LOCAL 1 소유이므로 이번
  변경은 건드리지 않았다. 병합 후 어댑터로 연결할 자리는 `sns` 모듈 상단
  주석과 이 README가 경계를 정의한다.
- **실서비스 검증**: 위 배포가 이루어지지 않았으므로 운영 도메인에서의
  라이브 생성·저장 검증은 아직이다. 이번 PR의 검증은 자체 테스트와 기존
  util3 테스트 무변경 증명이다.

## 실행

```bash
python -m pip install -e 'apps/padiem-council-apps[dev]'
python -m pytest apps/padiem-council-apps/tests -q
node --check apps/padiem-council-apps/static/council-app.js
python -m app.cli --host 127.0.0.1 --port 8791   # apps/padiem-council-apps에서
```
