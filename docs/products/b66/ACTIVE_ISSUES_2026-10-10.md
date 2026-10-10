# B66 활성 이슈·PR·담당 현황 — 2026-10-10

> **성격:** CENTRAL CTO의 시점별 작업 현황표. 기능 요구사항의 법적/기술적 권위는 각 이슈와 [B66 README](README.md), [SOURCE_TEMPLATE_FIDELITY.md](SOURCE_TEMPLATE_FIDELITY.md)에 있다. 상태가 바뀌면 실시간 GitHub 상태를 우선한다.
>
> **조사 기준:** 2026-10-10 KST, 저장소 `skerishKang/ai-revenue-lab`, 작업 시작 main `b55b634c7f17e5581cfc9ea26da57eea43453f10`.
> **범위:** 현재 대화에서 검토한 B66 원본 양식/견적 기능과 직접 연결된 B14·Claw 이슈. 저장소의 *모든* OPEN 이슈를 포괄한 대장이 아니다.
> **상태 최신화 (2026-10-10 KST):** 스냅샷 `main=52b05ae4623fb211c32d31fe286d8e483803330f`; **B66 Pages Production** 승인된 수동 [run #38006616259](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38006616259) 및 사후 계약 검사 **SUCCESS**. OAuth 콜백 수정 [#4073](https://github.com/skerishKang/ai-revenue-lab/pull/4073) 포함. 독립 로그인/Drive 고객 E2E는 **NOT_TESTED**; [#4074](https://github.com/skerishKang/ai-revenue-lab/pull/4074)는 중복으로 CLOSED/UNMERGED. [**첫 고객 인수 기준·릴리스 증거**](CGI_FIRST_CUSTOMER_MVP_CHECKPOINT_2026-10-10.md) 및 [#4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076)이 최우선 현재 상태를 정의한다. LOCAL1=#3839 Sol 다중 페이지, LOCAL2=#4076 통합, LOCAL3=#3871 Drive. 병합된 #4069 공유 Core / #3998 B66 모델 UX와 미완료 #3906 사용자 실전달 수용을 구분한다.
> **기존 점검 기록:** 이전 main `7f9b89eaf10c`에서의 담당 배분은 역사적 스냅샷이다. 현재 운영·병합 상태는 위 항목을 우선한다.

## 최신 CGI 첫 고객 MVP — 배포 완료와 인수 미완료 구분

| 축 | 현재 | 다음 인수 증거·담당 |
|---|---|---|
| 기존 1차 인수 #3521 | **CLOSED** (기존 제한 범위) | 재오픈 금지; 새로운 최종 고객 인수 [#4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076) **OPEN** |
| OAuth Pages 소스 | #4073 **MERGED** · #4074 중복 **CLOSED/UNMERGED** | 실제 Google 브라우저에서 새 Production 로그인 검증: LOCAL3 |
| B66 Pages Production | **SUCCESS**, 정확 SHA `52b05ae4623f`, run **#38006616259** | 정적 UI·로그인 상태 API 200은 실제 로그인 성공과 별개 |
| Sol 1~3품목 | 기존 v1 인증 유지 | 새 배포 실제 고객 QuoteCore/PDF: LOCAL2 |
| Sol 4+품목 | [#4001](https://github.com/skerishKang/ai-revenue-lab/pull/4001)/[#4010](https://github.com/skerishKang/ai-revenue-lab/pull/4010) Draft, **v2 미인증** | 표 세로선·합계 격자·다중 페이지 수정+독립 시각 검토: LOCAL1 |
| D1/Google Drive 재열기 | 계정별 D1 실 E2E는 미확정; Drive 이전 버전 부분 실측 | D1: LOCAL2. Drive 실제 취소·승인·계정 격리: LOCAL3 |
| B14 추론 수준 | B66 #3998 및 공유 Core #4069 **MERGED** | 모델·SSE·정확한 공급자 계약 실전달: LOCAL2 #3906. LOCAL6 #3988 숨은 기본값 별도 |
| 최종 고객 인수 | **NOT_READY** | #4076의 새 Production 실제 인수 시나리오·4+ Sol v2 승인 후 재판정 |

> 완료의 정의는 **소스 병합 ≠ CI PASS ≠ Production 배포 ≠ 실제 고객 E2E ≠ Sol PDF 인증**이다. 이 표는 아래 과거 점검 설명을 최신 근거로 보정하며, 이번 갱신으로 배포·테스트를 다시 실행하지 않는다.

## 확정된 제품·개발 경계

1. **현재 김범신 CGI 최종 PDF는 기존 Sol 6.1에서 출발한, 인증된 동일 양식/렌더러만 사용한다.** 1–3개 품목 단일 A4가 현재 독립 검증된 Sol 네이티브 범위다. 4개 이상은 [#3839](https://github.com/skerishKang/ai-revenue-lab/issues/3839)에서 그 **동일한 Sol 구현**을 확장·재인증한다. GLM 5.3의 비교본, 임의 HTML/브라우저 인쇄 양식 또는 모델 생성 PDF는 CGI 최종본의 대체 경로가 아니다.
2. [#3542](https://github.com/skerishKang/ai-revenue-lab/issues/3542): **신규로 승인된 고객 양식의 최초 분석·초기 양식 엔지니어링을 당분간 Sol 6.1로 수행**한다. 범용 자동분석기 구축 자체는 보류한다. 최초 분석으로 나온 `ANALYZED` 후보는 PDF 재현·인증([#3595](https://github.com/skerishKang/ai-revenue-lab/issues/3595)) 없이 반복 실행할 수 없다. 현재 CGI 원본을 다시 분석할 필요는 없다.
3. 견적 생성마다 Sol/B14에 PDF를 다시 그리라고 호출하지 않는다. 완전한 구조화 입력은 모델 호출 없이 진행하고, 자유문장 입력의 **새 사실 추출**만 사용자가 명시적으로 선택한 B14 모델이 맡는다. **QuoteCore만 금액·세금을 계산**하며 승인된 코드가 결정적으로 PDF를 만든다. 사용자 모델 임의 교체/자동 fallback 없음.
4. [#3586](https://github.com/skerishKang/ai-revenue-lab/issues/3586)의 **재사용 양식 등록**은 XLSX 현재 허용, XLS/HWP 거부, HWPX 추후 검토. 반면 [#3884](https://github.com/skerishKang/ai-revenue-lab/issues/3884)의 **고객 원본 비공개 보관** 및 일반 PDF/DOCX/이미지 **견적 사실 추출**은 별도 형식 정책이다. 보관에 성공했다고 양식 인증이 되는 것은 아니다.
5. 소스 병합, 모의/오프라인 테스트, 브라우저 Live 검증, Production 배포는 **별개의 완료 게이트**다. 검증 안 된 항목은 OPEN/NOT_VERIFIED로 표시한다. 과거 성공 사례를 다른 템플릿, 더 큰 행 수, 다른 계정 또는 새 서빙 버전의 증거로 전용하지 않는다.

## B66 주요 이슈 현황 (상단 최신 릴리스 표 참조)

| 이슈 | 상태/우선순위 | 실제 담당·진행 증거 | 남은 수용 기준 / 다음 행동 |
|---|---|---|---|
| [#3180](https://github.com/skerishKang/ai-revenue-lab/issues/3180) Saved Quote Skill EPIC | **OPEN** (상위) | CENTRAL/B66 종합; 현행 제품 계약 유지 | 원본 온보딩·인증·반복 생성의 통합 고객 여정 증명 후 종료 |
| [#3186](https://github.com/skerishKang/ai-revenue-lab/issues/3186) 새 견적서 만들기 | **OPEN · P1** | 자동/직접/맡기기 3경로 정의; CGI는 지원·직접형 우선 | 계정에 승인 Skill 연결해 반복 생성 실제 검증; 자동 분석을 현재 MVP 필수조건으로 승격하지 않음 |
| [#3405](https://github.com/skerishKang/ai-revenue-lab/issues/3405) D1 최근 견적 | **OPEN · P1** | 계정별 D1 이력 기반 소스 존재, 기존 브라우저 로컬 캐시 유지 | 실제 로그인/재로그인·다른 브라우저 복원·계정 A/B 격리·히스토리 에러 조건 검증; Drive가 이를 대체하지 않음 |
| [#3542](https://github.com/skerishKang/ai-revenue-lab/issues/3542) 최초 원본 분석 | **OPEN · 범용 자동화 보류** | **임시 분석 모델 Sol 6.1 (Owner 확정)**. 기존 CGI 원본 분석 완료 | 두 번째 고객 양식 필요 시 승인된 최초 온보딩에서 Sol 수동/보조 분석; 일반 자동분석기 신규 개발은 수행하지 않음 |
| [#3586](https://github.com/skerishKang/ai-revenue-lab/issues/3586) 등록 형식 | **OPEN · P0** | [PR #3963](https://github.com/skerishKang/ai-revenue-lab/pull/3963) **MERGED**, 로컬 B66 43/43와 CI 8/8; UI·모듈 XLSX 전용 사전검증 | 인증된 **실서버** XLSX 접수, 실제 형식/본문 검사, 원본 무결성 확인; #3884 서버/스토리지 준비와 연결 |
| [#3595](https://github.com/skerishKang/ai-revenue-lab/issues/3595) 원본 재현·인증 | **OPEN · P0** | 기존 CGI Sol 1–3행 기준 인증·1행 변이 테스트 근거 보존 | 다른 고객의 **실질적으로 독립된 두 번째 양식** 재현·변이·시각·자산 인증; CGI 4+행은 #3839에서 별도 재인증 |
| [#3708](https://github.com/skerishKang/ai-revenue-lab/issues/3708) 대형 컴파일러 | **OPEN · P2 · DEFERRED** | 외부 Modal/Oracle/GCP 실행 위치 **미선정** | 실제 두 번째 고객 수요/원본 보관·분석 근거 생길 때 계약, 비용·시간 실측 후 재개; CGI 인도 장애가 아님 |
| [#3839](https://github.com/skerishKang/ai-revenue-lab/issues/3839) Sol 다중 페이지 | **OPEN · LOCAL1** | [Draft #4001](https://github.com/skerishKang/ai-revenue-lab/pull/4001) `c8a7cf24`, [Draft #4010](https://github.com/skerishKang/ai-revenue-lab/pull/4010) `a163f11d`, **미병합·v2 미인증**. 오른쪽 외곽선 실 PDF 196페이지 부분 벡터 PASS만 확보 | 중간페이지 내부 세로선·마지막 합계 격자 시각 HOLD 수정, 1–3 v1 바이트/원본 보존, 4+ Sol v2 독립 인증·실 E2E 전 고객 제한 해제 금지 |
| [#3871](https://github.com/skerishKang/ai-revenue-lab/issues/3871) 고객 Google Drive | **OPEN · LOCAL3** | [#4029](https://github.com/skerishKang/ai-revenue-lab/pull/4029) 초안 승인창, [#4073](https://github.com/skerishKang/ai-revenue-lab/pull/4073) OAuth 콜백 **MERGED**. 새 Production [#38006616259](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38006616259) **SUCCESS**. 중복 #4074 CLOSED/UNMERGED | **새 배포 실제 로그인은 아직 NOT_TESTED**, 내용 있는 초안의 불러오기 취소/승인, JSON+PDF, 다른 계정·브라우저·폰의 LIVE E2E 필요. 이전 버전 Drive 부분 실측을 전체 완료로 주장 금지 |
| [#3884](https://github.com/skerishKang/ai-revenue-lab/issues/3884) 고객 비공개 원본 | **OPEN · 중점 선행 의존성** | 기존 **별도 로컬 브랜치** `b66-template-custody-3884` / [Draft #3925](https://github.com/skerishKang/ai-revenue-lab/pull/3925); **로컬 번호는 GitHub 근거로 미확정** | HTTP 원문 크기 상한(파싱 전), OOXML 구조 안전성, R2 orphan 삭제실패 대응, D1 owner 분리 및 원본 SHA-256 복원, 버전/삭제/보유정책, 실제 cross-browser E2E. 현재 PR 미병합 |
| [#3906](https://github.com/skerishKang/ai-revenue-lab/issues/3906) 모델별 추론 수준 | **OPEN · LOCAL2** | B66 UI/어댑터 [#3998](https://github.com/skerishKang/ai-revenue-lab/pull/3998) **MERGED**, 공유 Core opt-in [#4069](https://github.com/skerishKang/ai-revenue-lab/pull/4069) **MERGED** `fcf168f3`. Exact-head CI 완료; 유료 Provider 실제 응답을 증명한 것은 아님 | B66 실제 로그인 어댑터→Core→B14 일반/SSE 전달, 정확한 모델 ID·생략·미지원 fail-closed·quota, 비기본 추론 수준 활성화 승인 별도 |
| [#4028](https://github.com/skerishKang/ai-revenue-lab/issues/4028) B66 테스트 구조 정리 | **CLOSED · CENTRAL** | PR #4030/#4031/#4032/#4034/#4038/#4040/#4041 모두 병합. B66 JS 테스트 파일 **56개 자동 발견/실행**; 제품 JS 36개 문법 검사; static mega-test 1,315→457줄 | 구조 정리 재개 금지, 전역 워크플로 fanout·B62 browser QA 선택 최적화는 #3989 LOCAL2 담당 |
| [#3916](https://github.com/skerishKang/ai-revenue-lab/issues/3916) 근삿값 확인 | **CLOSED** | 기존 안전성 작업 종료 상태 확인 | 새 실제 회귀 증거 없으면 재오픈하지 않음 |

### #3839의 테스트 결과는 이렇게 구분

- **기존 Sol 인증:** 1–3행 단일 A4 패키지 재현과 QuoteCore 근거 있음.
- **LOCAL1 최신 제출물:** Sol 6.1 기반 1~500품목 11종 테스트 증거를 보존한다. PR #4001 right border 수정본과 v2 후보의 4품목 이상 실제 PDF **196페이지의 오른쪽 외곽선 4분절 연속성을 CENTRAL이 독립 확인**했다. 다만 총합계 부분의 불필요한 세로선과 비최종 품목 아래 조기 종료 열선은 LOCAL1에 재작업 지시한 **시각 HOLD** 대상이다. [중앙 검토](https://github.com/skerishKang/ai-revenue-lab/issues/3839#issuecomment-6090226174). 정식 4+품목 v2 인증·고객 실사용 E2E는 아직 미완료.
- **이전 별도 로컬 프로토타입:** PyMuPDF 테스트가 통과해도, **GLM53 기반 PDF/manifest**를 재사용했다면 Owner가 정한 Sol-native 인증을 충족하지 못함.
- **#3855:** 테스트에 쓰인 예시 지오메트리(예: 180pt 이름 열)를 실제 Sol 인증 치수로 간주하지 않는다.
- **#3965:** LOCAL2의 데이터 경로 **source-only 계약·테스트 PR이 22 PASS/1 SKIP 후 MERGED**(`f296df9b87aab9e60153358d62fe71e3e43fdfa1`). D1 개별 스냅샷 101개 보존과 상위 입력 허용 100개의 차이를 검증하되, 이 병합은 **실제 Sol PDF 4+행 고객 인수/E2E를 증명하지 않는다.**

## 인접 프로젝트 경계 — B14, Claw, Web

| 이슈 | 현황 및 담당 | B66 작업과의 경계 |
|---|---|---|
| [#3977](https://github.com/skerishKang/ai-revenue-lab/issues/3977) B14 공식 모델 파라미터 | **OPEN · 공유 Core #4069 MERGED, #3988 Draft 별도** | LOCAL1 [#4069](https://github.com/skerishKang/ai-revenue-lab/pull/4069) 공유 Core/B66 native reasoning 전달 **MERGED** `fcf168f3`; [#3988](https://github.com/skerishKang/ai-revenue-lab/pull/3988) 샘플링/출력·숨은 `temperature=0.2` 제거 미병합 | LOCAL2 #3906 B66 실 E2E, #3988 담당자의 별도 head 검증·병합·Provider 실증 전 #3977 종료 불가 |
| [#3566](https://github.com/skerishKang/ai-revenue-lab/issues/3566) B54/Claw post-A7 502 | **OPEN; 최근 진단 담당 LOCAL3, 마지막 지시 STOP/STANDBY**. B14-상위 제공자 rate-limit 출처 및 안정적 최종 답변 미입증 | 모델 라우팅/Claw 정상답변 문제. B66 Sol PDF 재현 문제와 혼합하지 않음 |
| [#3382](https://github.com/skerishKang/ai-revenue-lab/issues/3382), [#3523](https://github.com/skerishKang/ai-revenue-lab/issues/3523) Claw Golden Path | **OPEN; CENTRAL 총괄** | Engine/Claw의 실제 로그인→AI 답변 E2E 별도 종료 기준 |
| [#3385](https://github.com/skerishKang/ai-revenue-lab/issues/3385) TinyFish Search/Fetch | **CLOSED · 신규 B66 업무 아님**. [PR #3950](https://github.com/skerishKang/ai-revenue-lab/pull/3950)·[#3957](https://github.com/skerishKang/ai-revenue-lab/pull/3957)·[#3975](https://github.com/skerishKang/ai-revenue-lab/pull/3975) MERGED. 별도 오래된 [Draft #3386](https://github.com/skerishKang/ai-revenue-lab/pull/3386)의 Core-검색 소스는 병합됐다고 간주하지 않고 폐기/보존 판단 대기 | TinyFish 기본·Daum 제한적 fallback의 **현재 소스 결정**과 실제 운영 설정/실검색 근거는 구분; B66 견적 생성, 고객 Drive·비공개 원본 권한과 혼합 금지 |
| [#3989](https://github.com/skerishKang/ai-revenue-lab/issues/3989) GitHub Actions fanout | **OPEN · LOCAL2 B66 범위 완료 / CENTRAL 전체 총괄** | [PR #4046](https://github.com/skerishKang/ai-revenue-lab/pull/4046) MERGED (`aaf44a785`); B66 전용 변경의 B62 browser QA lane 계획 **15→0**, 정적 감사 3개 workflow→1개/3 job; 56개 B66 JS 검사 보존. Engine/LL [#4051](https://github.com/skerishKang/ai-revenue-lab/pull/4051) 별도 완료 | 실제 after PR의 runner/wall 측정, B62 Chat 전체 CI 약 473초, Required Check/Cloudflare inventory·Core/mixed 검증 **미완료**. [운영 근거](../../operations/CI_3989_B66_B62_QA_SCOPE_2026-10-10.md) |

## 다음 단계 — 소유자·병렬 진행

> **2026-10-10 고객 인수 실행 순서:** (1) LOCAL3 #3871 — 이미 배포된 #4073 코드로 운영 OAuth 재로그인 및 Drive 취소/승인; (2) LOCAL2 #4076 — 이미 배포된 B66에서 1~3품목 Guided/Free-form/미완성 후속질문·D1 실증; (3) LOCAL1 #3839 — 기존 Sol 6.1 소스에서 4+/다중 페이지 시각 오류를 수정·신규 인증 후보 제출; (4) CENTRAL — Sol v2 승인 후 고객 인수 범위 판단. **#3977 공유 Core는 #4069 병합 완료**, 아래 이전 메모의 “신규 구현 시작” 단계는 과거 상태다. [단일 인수표](CGI_FIRST_CUSTOMER_MVP_CHECKPOINT_2026-10-10.md) 참조.

### 이전 배정 참고 기록 (현재 완료된 항목은 다시 구현하지 않음)


1. **LOCAL1 (#3839 Sol):** Draft #4001 오른쪽 외곽선 수정은 보존하고 연속 페이지 내부 열선·최종 합계 격자를 보정, 1–3 인증 해시 불변/4+벡터·래스터 회귀/중앙 직접 시각 검토 → v2 재인증 후보 검토. Draft #4010/인증/Production 수정 금지.
2. **LOCAL1 (#3977 Core):** **별도 최신 main worktree**에서 구 `9ec0e049` Core 실험은 참고만 하고, 충돌하는 Draft #3988은 현 상태 보존. 내부 optional native parameters → B14 외부 top-level `reasoning_effort`와 provider-default omission을 단일 B14 capability authority로 완성·정확한 HEAD CI. #3839 source/worktree 교차 변경 금지.
3. **LOCAL2 (#3906 B66):** #3998 소스는 MERGED. #3977 LOCAL1 공유 Core 인수 이후 B66→B62/Core→B14 일반/스트리밍 E2E를 검증한다. **#3989 B66 전용 CI 정밀 범위는 PR #4046 병합으로 완료**했고, 나머지 전역 CI/required-check 작업은 CENTRAL이 별도 추적한다.
4. **LOCAL3 (#3871):** #4029 포함 Production [#37997944674](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37997944674) 성공 후 실제 브라우저에서 초안 보존 확인창 취소/승인 검증. 다른 브라우저·두 번째 계정·late-callback·휴대전화는 증거 전까지 NOT_TESTED.
5. **#3884 원본 보관 기존 브랜치 소유 로컬:** Draft #3925와 운영 보안 경계를 독립 유지(새 담당 임의 중복 배정 금지).
6. **CENTRAL:** #3977 공유 파일 PR 겹침·일반/SSE 테스트·권위·병합 심사, #3989 전역 워크플로 Required Check 총괄, Sol v2 시각·인증 승인 게이트 유지. #3542/#3708 범용 자동 컴파일러는 Owner 재개 요청 전 보류.

## 중복·통폐합 판정 (2026-10-10)

- **통합 관리, 이슈 자체 유지:** [#3180](https://github.com/skerishKang/ai-revenue-lab/issues/3180) 제품 Epic 아래 #3839(Sol 품목 확대), #3595(별도 원본 인증), #3884(고객 원본 custody), #3871(선택적 Google Drive), #3405(D1 이력)를 연결하되 **완료 증거와 소유권이 달라 일괄 종료·기능 병합하지 않는다**.
- **B14 계약 중복 개발 금지:** #3977 남은 Core opt-in은 LOCAL1 (이전 LOCAL6의 PR #3984 native 소스 병합은 사실 유지), #3906 B66 UX/어댑터는 LOCAL2 (PR #3998 MERGED), #2676은 별도 모델 성능 재평가, #3554는 실제 응답 E2E, #2698은 미승인 Auto Router 보류. 사용자의 정확한 모델 선택을 자동 대체하지 않는다.
- **Claw 상위·원인 분리:** #3523은 Production Golden Path 총괄, #3382는 로그인→실제 답변 사용자 E2E, #3566은 B14 post-A7 502 원인, #3930은 SSE 실시간 화면. 하나가 소스 병합됐다는 이유로 전체 종료 금지.
- **보류 유지:** #3542 최초 새 원본 분석과 #3595 인증은 독립 단계. #3708 외부 대형 컴파일러와 #3736 Modal PDF standby는 **실제 신규 고객 요구 전 활성 개발 제외**, 필요 시 Owner가 한 번에 재검토하되 무증거로 지금 병합·종료하지 않는다.
- **오래된 Draft 관리:** 현재 열린 PR 다수 중 #3597(B14 과거 provider max-token/UI), #3914(Agnes 진단), #3386(Core TinyFish), #3855(Sol 계획기), #3830/#3835(StepFun 평가)는 최신 merged #3984/#3975·#3839 실제 엔진과 계약·파일 충돌 가능성이 있다. **별도 존치 사유와 최신 main 재기반 검증 없이 병합 금지**. 역사적 증거가 필요한 PR은 Draft/보류로 보존하고, 겹치는 코드를 이미 구현했다는 사실만으로 자동 폐기하지 않는다.

## 종료 규칙 및 원본 보호

- 이슈 종료: **기능 코드 + 정확한 HEAD CI + 승인된 수용 E2E + 기존 기능 회귀 + 운영 배포 상태**를 이슈별로 따로 증명한다. Source-only 이슈라면 범위를 명시하고, 실서비스 수용이 남아 있다면 OPEN 유지.
- 공개 표준 CGI `reference/b66-public-standard-templates/cgi/v1`과 고객 비공개 원본(R2/D1)은 별개의 저장소·권한이다. 비공개 원본/로고/인장·실계정·토큰은 공개 Git/검증 로그에 게시하지 않는다.
- 다른 LOCAL의 브랜치/작업 폴더/담당 소유권을 임의 침범하지 않는다. Production, 시크릿/OAuth, 과금 서비스 호출, 데이터 마이그레이션은 별도 게이트다.
