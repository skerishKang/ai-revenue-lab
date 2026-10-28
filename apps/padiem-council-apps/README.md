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

## 모바일 헤더 계측 (#6065 S0, 2026-10-28)

`origin/main`의 세 정적 파일(라이브 바이트와 sha256 동일함을 먼저 확인)을 Chromium(140)에서
계측했다. 상태 2종(로그인 전/후) × 폭 4종(320/390/768/1440) × 화면 3종 = 24셀. `/api/chat`은
로컬 canned 응답으로 받아 모델 호출은 없다.

수정 전 수치는 **#6075가 44px 하한을 먼저 고친 뒤의 main**을 기준이다.

| 항목 | 수정 전 (main) | 수정 후 |
| --- | --- | --- |
| 320px 가로 넘침 | **30px** (actions 우측 x=350.1, 로그인 단추 화면 밖) | 0 |
| 상태 배지 "로그인 필요" | 34×114px — 세로 6줄 | 85.5×30.8px 한 줄 |
| 서비스명 | 71.3×51.2px — 2줄 | 118.2×25.6px 한 줄 |
| "콘텐츠 언어" 라벨 | 130×95.9px — 세로로 쌓임 | 177.6×44px 한 줄 |
| 로그인 단추 | 42×64.4px — "로그/인" 2줄 | 65.9×44px 한 줄 |
| 390px 배지 | 47.4×72.4px — 3줄 | 85.5×30.8px 한 줄 |
| 헤더 높이 | 320: 135 / 390: 116.9 | 320: 153 / 390: 101 (768·1440은 65·69로 불변) |

- 이 레인의 변경은 `@media (max-width: 900px)` 안에서 헤더와 actions 그룹을 감싸고 항목별
  `white-space: nowrap`을 건 것이다. 언어 `<select>`의 44px와 활동집 체크박스의 24px는
  **#6075가 이미 반영한 것**이고, 이 레인은 같은 값을 다시 선언하지 않도록 기본 규칙의
  `min-height: 32px` 잔여 선언만 지웠다(렌더 높이 44px 불변, 실측 확인).
- 근거 캡처: `docs/6065/mobile-header-before-after.png`
- 고정 계약: `tests/test_6065_mobile_header_contract.py` (변형 6종 모두 해당 테스트에서 검출)
- 디자인 연결의 단계별 계약: `docs/architecture/PADIEM_COUNCIL_UI_DESIGN_INTEGRATION_20261028.md`

## 글로벌 디자인 헤더 스킨 (#6065 S1, 2026-10-28)

시안 헤더의 어휘를 운영 헤더에 옮겼다. `council-app.js`는 **바이트 단위로 무변경**이므로
프롬프트·payload·저장·인증 경로는 이 PR의 대상이 아니다(58→64 테스트에 기존 계약 포함 통과).

| 속성 | 시안(1440) | S1 전 운영 | S1 후 운영 |
| --- | --- | --- | --- |
| 바 padding / gap | `12px 69.84px` / `17.28px` | `12px 20px` / `12px` | `12px 69.84px` / `17.28px` |
| 표장 | 30×30 stroke SVG, 배경·반지름 없음 | 28×28 채운 타일 + "P" | 30×30 stroke SVG, `currentColor` |
| 브랜드 글자 | 16.5px / 700 / -0.01em / lh 1.2 | 16px / 700 / normal / lh 1.6 | 시안과 동일 |
| 열린 도구 표시 | 카드 밖 2px 링(`.pa-work.is-open`) | 안쪽 3px 막대 | 밖 2px 링 + offset 2px |
| 헤더 높이 | 69.2 | 69 | 69 |

- 320/390/768/1440 × 로그인 전후 × 4화면 = 32셀 가로 넘침 0·가림 0, 활성 카드 링은
  전 폭에서 뷰포트 안(320 실측: 카드 14..306, 링 10..310).
- ≤767에서 표장 좌측 끝(14px)이 본문 열 좌측 끝(14px)과 맞는다. 데스크톱에서 헤더는
  시안처럼 전폭 유동 거터, 본문은 중앙 920px 열이다 — 시안도 같은 관계다(표장 69.8 / 카드 271.9).
- **정정 기록**: 시안은 Pretendard를 자체 호스팅하므로 1440에서 118.1px로 렌더된다.
  이 앱은 `@font-face`가 없어 같은 문자열이 127.7px(폴백)로 렌더된다(캔버스 폭 차분 실측).
  S1은 폰트를 추가하지 않는다는 결정에 따라 **글자 크기·자간은 맞췄고 서체는 못 맞췄다**.
  서체 일치는 자산 결정(§6-1)과 함께 다룬다.
- 5스타일(`data-style`)과 시안 테마 키(`padiem-parliament-theme`)는 운영에 노출하지 않는다 —
  이를 테스트로 고정(`test_the_five_styles_stay_internal`).
- 근거 캡처: `docs/6065/s1-header-1440-before-after.png`,
  `docs/6065/s1-header-320-before-after.png`, `docs/6065/s1-active-tool-1440-before-after.png`

## 카드 골격·문서 목록 터치 영역 (#6065 S2, 2026-10-29)

시안 카드 `.pa-work`의 골격을 운영 카드에 옮기고, 아카이브 목록의 누르는 면을 44px로 벌렸다.
신규 이미지·폰트·테마는 0이고 표장은 모두 인라인 SVG다.

| 항목 | 시안(1440) | S2 전 운영 | S2 후 운영 |
| --- | --- | --- | --- |
| 아이콘 칸 | 30×30 슬롯 + 26×26 stroke SVG | 없음 | 30×30(x=277) + 26×26 |
| 아이콘 아래 규칙선 | 22×2 | 없음 | 22×2, 색은 `--council-border` |
| 카드 제목 | `clamp(17px, 1.39vw, 20px)` / −0.02em | 고정 17px / normal | 17px(≤768) · 20px(1440) / −0.4px |
| 본문 열 | 아이콘 + 텍스트 2열 | 1열 | `30px minmax(0,1fr)` 2열, 편집기는 `1 / -1` |
| 활동집 체크박스 | 시안에 목록 없음 | 상자 24×24가 유일한 표적 | 상자 24×24 + **라벨 44×44** |
| 본문 바로가기 링크 | — | 포커스 92.8×25.6 | 포커스 116.8×**44** |

- 44px 최소 누름 면 실측: 라벨 44×44 / 상자 24×24 / 기록 열기 단추 280×44(긴 이름 280×62.8) —
  320·390·768·1440 동일. 라벨 좌측에서 5px 안쪽을 눌러도 상자가 선택됐다(False→True, 4폭 전부).
- AI 3종·저장·국가 필터 무변경 증명: `main`과 이 브랜치를 같은 동작으로 5케이스
  (speech/sns/meeting@kr, speech@fr, meeting@us) A/B — `/api/chat`과
  `/api/projects/p1/files` 요청 본문·렌더 결과·alert 수가 **전 케이스 동등**.
  kr 은 `country` 필드 없음(현행 바이트 유지), fr/us 는 두 요청 모두 코드를 싣는다.
  SNS 사진 구성 파일도 기존대로 `application/json` 으로 저장된다.
- 아이콘 때문에 본문 열이 42px 좁아져 390px에서 설명이 단어 중간('준비합/니다')으로 잘렸다.
  카드 제목·설명에 `word-break: keep-all`을 걸어 어절 경계로만 끊기게 했다(320에서 3줄로 늘어남).
- 32셀(로그인 전후 × 4폭 × 4화면) 가로 넘침 0·가림 0·잘림 0.
- 근거 캡처: `docs/6065/s2-card-frame-1440-before-after.png`,
  `docs/6065/s2-card-frame-390-before-after.png`, `docs/6065/s2-archive-1440-before-after.png`
- 기준선 정정: 이 문단을 작성할 때 운영 `/apps/council/` 의 index.html·council-app.css 는
  `main`과 **다르다**(S1 병합 후 재배포 전). council-app.js 는 동일.

## 실행

```bash
python -m pip install -e 'apps/padiem-council-apps[dev]'
python -m pytest apps/padiem-council-apps/tests -q
node --check apps/padiem-council-apps/static/council-app.js
python -m app.cli --host 127.0.0.1 --port 8791   # apps/padiem-council-apps에서
```
