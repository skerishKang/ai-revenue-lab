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
  모델 정책, UsageGate, 검증된 세션). 요청 본문은 PR #5916이 정한 util
  실행 경계 계약과 동일한 `{messages, mode:"auto", tier, util}`이며,
  도구별 식별자(`"speech"`/`"sns"`/`"meeting"`)를 선언한다. 이 선언이
  공용 네이티브 캘린더 분기(2차 분류 포함)를 건너뛰게 하므로, 회의 원문에
  `확인`·`추가`·`일정`이 포함되어도 캘린더 확인 응답이 아닌 생성 결과를
  받는다. 서버는 알 수 없는 scope를 모델 호출 전에 거부한다. 식별자는
  신원·티어·권한·도구 범위를 부여하지 않는 라우팅 라벨이다.
- **저장**: `GET|POST /api/projects`, `GET|POST /api/projects/{pid}/files`,
  파일 상세 `GET /api/projects/{pid}/files/{fileId}` — 기존 프로젝트 파일
  저장 계약. 이 앱은 새 테이블·마이그레이션·D1·R2를 만들지 않는다.
- **인증**: 세션 쿠키(`credentials: "include"`)와 `GET /api/auth/status`.
  인증 확인이 실패하면 도구를 열지 않는다(fail-closed). 인증 검증을
  우회하지 않는다. 미로그인 방문자는 이 화면에서 로그인한다 — 기존
  `POST /api/auth/password/login` 자격 계약과 (`서버가 허용할 때`) Google
  링크를 쓰며, PADIEM Chat 홈페이지로 이동시키지 않는다(#5942). Google
  왕복이 끝난 뒤의 복귀 지점은 이 Worker가 서명된 상태값의 허용 목록으로만
  정한다(`app/auth.py` `OAUTH_RETURN_TARGETS`).

## Chat/Claw 운영 변경 없음

이 앱은 `apps/padiem-chat/**`의 어떤 파일도 수정하지 않았다. 라우트 등록,
`app_factory.py`, `worker.py`, `wrangler.toml` 변경 0건이므로 Chat/Claw의
배포 번들과 실행 경계가 변하지 않는다. 이 앱 자체는 자기 완결 정적
진입점(자체 pyproject·테스트·CI)이며 `padiem_ai_core` 등 저장소 공용
패키지를 import하지 않는다.

## 캘린더 의도분류와의 충돌 방지

공용 `/api/chat`은 네이티브 캘린더 의도분류를 먼저 돌린다. 이 앱은 PR
#5916 계약대로 도구별 `util` 식별자를 요청에 실어 보내며,
`timezone`·`calendar_turn_id`는 보내지 않는다. 유효한 식별자 선언은
캘린더 분기 전체(2차 분류 포함)를 건너뛰게 한다. 회의 원문에 캘린더
어휘(`확인`/`추가`/`일정`)가 있을 때도 캘린더 clarify가 아닌 생성이
돌아오는 행위 테스트(`calendar_words` 하네스 시나리오)로 고정했다.

## 미연결 상태 (정상 동작으로 표시하지 않는 항목)

- **독립 도메인에서의 인증·API 연결**: 현재 이 앱의 API 호출은 같은
  오리진의 기존 PADIEM 백엔드를 전제로 한다. 독립 도메인에서 브라우저가
  공용 API + `credentials:include`로 직접 호출하는 구성은 same-origin
  가드(Origin 검증)에 걸려 동작하지 않는다. 별도 도메인 제품은 자체
  Worker 라우트 경유 또는 B62 service binding/auth bridge 구현이
  선행되어야 하며, 그 전까지 독립 도메인의 인증·API는 **미연결** 상태다
  (로컬 단독 실행에서는 앱 안 로그인 폼만 뜨고, 백엔드가 없어 인증 확인과
  제출은 실패한다 — fail-closed 상태가 그대로 보장된다). 이번 PR 범위에서
  Worker 분리·배포는 하지 않는다.
- **Business 번호**: 신규 Business 번호는 임의로 확정하지 않았다.
  `BUSINESS_REGISTRY.md` 등록 절차가 필요한 미확정 항목이다.
- **SNS 사진 저장 연결**: SNS 모듈은 텍스트 초안 계약만 사용한다. 사진
  구성·로스터 계약(#5728)은 LOCAL 1 소유이며 이미 main에 병합되었다
  (PR #5924 포함). 이 앱은 그 코드를 복사하지 않았고, 병합된 계약을
  어댑터로 연결하는 것은 별도 후속 작업이다(sns 모듈 상단 주석이 자리를
  정의한다).
- **제품 식별자(product_scope)**: 요청은 #5916의 `util` 라우팅 라벨을
  사용한다(신원·티어·권한 부여 없음). `KNOWN_PRODUCT_SCOPES` 등 제품
  scope 체계 등록은 별도 후속 작업이다.
- **실서비스 검증**: 독립 도메인 배포가 이루어지지 않았으므로 운영
  도메인에서의 라이브 생성·저장 검증은 아직이다. 이번 PR의 검증은 자체
  테스트와 기존 util3 테스트 무변경 증명이다.

## 실행

```bash
python -m pip install -e 'apps/padiem-council-apps[dev]'
python -m pytest apps/padiem-council-apps/tests -q
node --check apps/padiem-council-apps/static/council-app.js
python -m app.cli --host 127.0.0.1 --port 8791   # apps/padiem-council-apps에서
```
