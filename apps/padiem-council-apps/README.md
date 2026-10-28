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
  S3 작성 시점(2026-10-29)에는 **세 파일 모두** 다르다 — S2 가 JS 를 바꾸었으나 운영은 여전히
  S1 이전본이다. `main` = `d941fb33a`, 운영 = 그 이전 배포.

## 편집기 3종 스킨 (#6065 S3, 2026-10-29)

시안 편집기의 두 표면을 운영에 옮겼다. DOM 구조·엔드포인트·요청 본문은 그대로이고 변경은 CSS 한 파일이다.

| 요소 | 시안 어휘 | S3 전 운영 | S3 후 운영 |
| --- | --- | --- | --- |
| 정보 묶음 | `.pa-meta` 패널 | border + 반지름 10, padding 12, gap 10 | 반지름 14, `padding: clamp(14px,1.8vw,20px)`, gap 12 |
| 레이블 | 12px / .04em / muted | 14px 기본 색 | 시안과 동일 |
| 입력 | 44h · `10px 12px` · 15px | 44h · `8px 10px` · inherit | 시안과 동일(반지름 14) |
| 텍스트에리아 | `min-height: 92` · `resize: vertical` | 88 · 지정 없음 | 시안과 동일 |
| 1차 동작 | `.pa-draft` 알약 · 700 | 반지름 10 · 650 | `border-radius: 999px` · 700 · `10px 20px` |
| 2차 동작 | `.pa-back` 헤어라인 알약 | 반지름 10 | `council-save`·`council-actions button` 알약 |
| 문서 표면 | `.pa-paper` — 두께 있는 여백 + 그림자, 안의 텍스트는 테두리 없는 종이(16.5px/1.85) | 테두리 있는 입력 상자 160px | 시안과 동일(최소 `clamp(320px,54svh,620px)`) |
| 편집 레이아웃 | `.pa-editor-grid` — 정보 320 + 문서 나머지, ≤900 은 1열 | 1열(폼 886px) | ≥900 에서 `340px / 1fr` 2열 |

- 2열은 **오른쪽에 내용이 있을 때만** 열린다(`.council-card-body:has(...)`). 결과가 아직 없는 SNS에서
  빈 열이 생기지 않는다. `:has()` 미지원 브라우저는 규칙이 통째로 무시되어 지금의 1열로 남는다.
- 포커스 신호: 시안대로 문서 텍스트에리아의 아웃라인을 지우는 대신 `.council-result:focus-within`
  테두리를 accent 로 밝힌다. 전역 `:focus-visible` 링은 유지.
- 32셀(로그인 전후 × 320/390/768/1440 × 4화면) 가로 넘침 0·가림 0. 1440 실측 열 `340px 532px`,
  폼 340, 결과·목록 x=631. 768/390/320 은 1열 유지(폼 706/332/262).
- AI·저장 무변경 A/B: speech/sns/meeting@kr, speech@fr, meeting@us 5케이스에서
  `/api/chat`·`/api/projects/p1/files` 요청 본문과 렌더 결과가 main 과 동일.
  kr 은 `country` 없음, fr/us 는 두 요청 모두 코드 수록, SNS 사진 구성은 `application/json` 유지.
- 계약 테스트 7건 신규(`test_6065_s3_editor_skin.py`), 변형 10종 검출. 78 passed.
- 근거 캡처: `docs/6065/s3-editor-1440-before-after.png`, `docs/6065/s3-editor-390-before-after.png`

## 로그인 게이트·기록 목록 표면 (#6065 S4, 2026-10-29)

시안에는 로그인 화면도 기록 목록도 없다. 그래서 **새로 지되 시안의 표면 어휘를 썼다**
(정보 패널 `.pa-meta` 의 반지름·여백, 헤어라인 구분 `.pa-strip li + li`, 알약형 보조 동작 `.pa-back`).
변경은 `council-app.css` 한 파일 — DOM을 만드는 JS·마크업은 diff에조차 없다.

| 요소 | S3까지 운영 | S4 후 (실측) |
| --- | --- | --- |
| 로그인 패널 | 반지름 16 · padding 16 | 반지름 14 · `clamp(14px,1.8vw,20px)` → 1440에서 20px |
| 로그인 제목 | 고정 17px | `clamp(17px,1.39vw,20px)` / −0.02em → 1440에서 20px |
| 저장 목록·기록 보관함 | **표면 없음**(반지름 0, 테두리 0, padding 0) — 맨 `<ul>` | 패널(반지름 14 · 테두리 1px · padding 20px · surface) |
| 목록 행 | 행마다 테두리 회색 박스 | 행은 테두리 없는 본문(600체, padding `8px 0`), 행 사이에 헤어라인 1px(첫 행은 0) |
| Google 로그인 | 반지름 10 · 650 · `0 14px` | 알약 999px · 600 · `9px 16px`, 높이 45.6px |
| 사진 구성 상자 | 반지름 10 · padding 12 | 반지름 14 · `clamp(14px,1.8vw,20px)` |

- 실패 시에도 열리지 않는 게이트 확인: 로그아웃에서 `#councilAuthPanel` 표시 + `.council-form` **1개**(로그인 폼)만 존재, 도구 3종 빌더 미첨부. 자격증명 제출은 `POST /api/auth/password/login` 하나만 호출하고, 서버가 세션을 확인하지 않으면 패널이 열린 채 실패 문구를 띄우고 빌더는 계속 0개. Google 링크는 `return_to=%2Fapps%2Fcouncil%2F` 유지.
- 데이터 핸들링 A/B(main vs 이 브랜치, 6케이스): speech/sns/meeting@kr, speech@fr, meeting@us, 그리고 로그아웃 로그인 시도 — `/api/chat`·`/api/projects/p1/files` 요청 본문과 렌더 결과가 **전 케이스 동등**. kr은 `country` 필드 없음, fr/us는 두 요청 모두 코드 수록.
- 32셀(전후 × 320/390/768/1440 × 4화면) 가로 넘침 0·가림 0.
- 계약 테스트 6건 신규(`test_6065_s4_auth_archive.py`), 변형 12종 검출. 84 passed.
- 정정 기록: 첫 배합 치환에서 본문이 같은 두 규칙(보관함 행 / 저장 행)을 하나로 묶어 한쪽에 잘못 적용했다. 되돌린 뒤 **선택자 기준으로 규칙을 통째 치환**해 다시 적용했고, 계산된 스타일을 브라우저에서 재확인했다. 또 참고 선택 칩에 걸었던 `border-radius: 999px`는 공유 44px 하한 블록(10px)에 항상 지므로 선언 자체를 없앴다.
- 근거 캡처: `docs/6065/s4-sign-in-1440-before-after.png`,
  `docs/6065/s4-record-list-1440-before-after.png`, `docs/6065/s4-record-list-320-before-after.png`

## 배포 특정·라이브 검증 규칙 (#6065 S5, 2026-10-29)

S5는 코드 단계가 아니라 **배포 단계**다. 운영 릴리스는 릴리스 오너(LOCAL0/CENTRAL) 권한이고, 여기는
검증 도구만 추가한다 — `tools/council_s5_live_verify.py`는 읽기 전용(로그인·생성·저장을 하지 않는다).
운영 화면을 고친 diff는 이 PR에 없다.

**운영이 실제로 서빙 중인 커밋을 특정했다.** `DRIFT`만으로는 "뭔가 다르다"일 뿐이라, 서빙 바이트를
git blob으로 `main` 이력과 대조해 세 애셋이 모두 일치하는 가장 최근 커밋을 돌려준다.

배포 전 기준선 (2026-10-29, `main` = `b884ab7b9`):

| 확인 | 실측 |
| --- | --- |
| 서빙 커밋 | `71a74dee2` (#6082, 2026-10-28 21:00 +0900) — main이 **26커밋** 앞 |
| 배포 근거 | `B62 Production Code Deploy Gate` run `40684361588` (2026-10-28T12:00:43Z, success) |
| index.html | 5733b (cf-injected 367b) → `9026d1cd…` vs main `754318cb…` = DRIFT |
| council-app.css | 14873b → `43793ed8…` vs main `5606458…` = DRIFT |
| council-app.js | 70711b → `cabb44af…` vs main `8711a15…` = DRIFT |
| 라이브 마커 | S0만 라이브 (320/390/768 `flex-wrap: wrap`, 1440 `nowrap`, 브랜드 16px·28px 마크, 카드 아이콘 없음, 필드 8px, 인증 패널 16px) |
| 라이브 지오메트리 | 320/390/768/1440 가로 넘침 0 · 오버플로 요소 0 · 44px 미만 0 · 언어 4종 · 로그아웃에서 로그인 패널 표시 |

즉 **S1–S4는 병합됐지만 운영에 없었다. `LIVE_VERIFIED=NO`.** 그리고 릴리스 오너(LOCAL0/CENTRAL)가
같은 날 current main을 배포했다 — 이 레인이 배포한 것이 아니다.

배포 후 재측정 (`B62 Production Code Deploy Gate` run `40786832140` success,
deployed SHA `9430f3993`, cloud version `302b33f6-0c28-4b22-a16a-f2d1c7acdea8`):

| 확인 | 실측 |
| --- | --- |
| 서빙 커밋 | `9430f3993` — main과 **0커밋 차이**, 세 애셋 전부 `MATCH` |
| 라이브 마커 | S0(≤900 wrap) + S1(stroke 마크 30px, 16.5px/−0.165px) + S2(30px 아이콘 열) + S3(필드 14px) + S4(인증 패널 14px) 전부 운영 화면에서 확인 |
| 지오메트리 | 320/390/768/1440 가로 넘침 0 · 오버플로 요소 0 · 44px 미만 0, `countries=kr,us,uk,fr`, 로그아웃에서 로그인 패널 표시 |
| 판정 | `DEPLOYED_TO_MAIN_BYTES=YES S1_S4_MARKERS=YES GEOMETRY_CLEAN=YES` → **`LIVE_VERIFIED=YES` (로그아웃 표면)** |

미검증으로 남기는 것: **로그인 후** 편집기 3종 × 4폭, 실서비스 KR/US/UK/FR 생성, 저장·재진입, SNS 사진
순서, 활동집, 복사/TXT, 키보드 포커스(S5 3–4단계). 인증 테스트 계정과 유료 모델 호출·실 파일 기록 동의가
별도로 필요하다. 5단계의 "기존 사용자 문서 보존"은 현재 *이번 배포에 저장 쓰기 없었다*
(`D1_SCHEMA_QUERY=READ_ONLY`, `D1_IDENTIFIER_OUTPUT=0`, `B62_D1_PLAN_APPLY=0`)와 배포 전 게이트 실측
`project_files=14`까지만 근거이고, 재측정은 같은 인증 읽기가 필요하다.
- 화면 근거(운영 재촬영): `docs/6065/s5-live-home-1440.png`, `s5-live-home-390.png`,
  `s5-live-tooltap-1440.png`, `s5-live-tooltap-390.png` — stroke 표장·아이콘 열(22×2 규칙선)·알약형
  동작·패널 표면이 운영에서 실제로 렌더되고, 390에서 한글이 단어 경계로 줄바꿈한다. 로그아웃에서 카드
  `열기`를 눌러도 `.council-form`은 **1개(로그인 폼)** 그대로 — fail-closed 게이트가 운영에서 유지된다.

readback이 거짓말하는 다섯 가지 경우를 각각 막았고, 변형 테스트로 확인했다:

1. 빈 응답은 절대 MATCH가 될 수 없다 — 빈 본문 두 개는 해시가 같으므로 해시 비교 전에 비어있지 않음을 본다.
2. 서빙 HTML은 소스 HTML과 **처음부터 같을 수 없다** — Cloudflare가 웹 애널리틱스 `<script>` 하나를 삽입한다(실측 366바이트, 자기 줄을 갖고 오므로 줄바꿈까지 367). 정규화 패턴은 태그+그 줄바꿈만 지우고 **앞줄 줄바꿈은 절대 먹지 않는다** — 앞 `\s*`로 썼을 때 완전 일치 배포가 영구 1바이트 부족으로 DRIFT났다.
3. drift는 보고가 아니라 **특정**으로 바꿔준다 (`SERVING=<sha>`).
4. skip 링크는 포커스 전까지 `left:-9999px`에 주차돼 있다 — 이를 오버플로/터치 집계에 넣으면 깨끗한 화면이 영원히 실패한다.
5. 마커 하니스는 `#councilAuthPanel`에서 `hidden`이 벗겨지는 상태를 기다린다(고정 sleep이 아님) — 700ms sleep은 `/api/auth/status`와 경주해서, 아무 문제없는 화면에서 390만 "로그인 패널 숨음"으로 보고했다.

변형 검출(각 변형은 하나만 적용한 뒤 스냅샷과 바이트 비교로 되돌렸다): beacon이 앞 줄바꿈까지 먹음 → 1건 실패, beacon 뒤 줄바꿈을 지우지 않음 → 2건 실패, 빈 응답 분기 삭제 → 1건 실패, skip 제외 삭제 → 1건 실패, settle 대기 삭제 → 1건 실패, settle sleep을 500ms 초과로 늘림 → 1건 실패.
**부하가 걸리지 않는 두 개는 감추지 않는다.** MATCH에서 `length_equal` 조건을 빼도 초록이다 — 전체 SHA-256 비교가 이미 바이트 길이까지 함께 보장하므로, CENTRAL이 요구한 "빈 응답 오검출 금지"를 두 번째 독립 진술로 명시적으로 남긴 것이다. 또 오버플로 루프의 skip 제외 `continue`는 오늘의 DOM에서 값이 안 변한다 — 같은 루프 조건에 `!parked(el)`가 이미 왼쪽 주차를 걸러내고 있기 때문이다. 터치 루프 쪽 `continue`는 실제 화면에서 부하가 걸린다(44px 미만 집계 1 → 0, 4폭 모두).
- 계약 테스트 8건 신규(`test_6065_s5_readback_rules.py`) — `readback()` 자체를 합성 응답으로 구동한다(도구 소스를 grep하는 테스트는 가드를 꺼도 통과하므로). 92 passed.

## 실행

```bash
python -m pip install -e 'apps/padiem-council-apps[dev]'
python -m pytest apps/padiem-council-apps/tests -q
node --check apps/padiem-council-apps/static/council-app.js
python -m app.cli --host 127.0.0.1 --port 8791   # apps/padiem-council-apps에서
```
