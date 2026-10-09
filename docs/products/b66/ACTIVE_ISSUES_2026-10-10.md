# B66 활성 이슈·PR·담당 현황 — 2026-10-10

> **성격:** CENTRAL CTO의 시점별 작업 현황표. 기능 요구사항의 법적/기술적 권위는 각 이슈와 [B66 README](README.md), [SOURCE_TEMPLATE_FIDELITY.md](SOURCE_TEMPLATE_FIDELITY.md)에 있다. 상태가 바뀌면 실시간 GitHub 상태를 우선한다.
>
> **조사 기준:** 2026-10-10 KST, 저장소 `skerishKang/ai-revenue-lab`, 작업 시작 main `b55b634c7f17e5581cfc9ea26da57eea43453f10`.
> **범위:** 현재 대화에서 검토한 B66 원본 양식/견적 기능과 직접 연결된 B14·Claw 이슈. 저장소의 *모든* OPEN 이슈를 포괄한 대장이 아니다.
> **상태 최신화:** 2026-10-10 KST, main B14 PR #3984 반영 후; LOCAL1 #3839 래스터 재감사 / LOCAL3 #3871 Owner 직접 잔여 지시 / TinyFish #3385 CLOSED 기준으로 보정. 이 문서는 여전히 시점별 스냅샷이며 GitHub의 실시간 상태가 우선한다.

## 확정된 제품·개발 경계

1. **현재 김범신 CGI 최종 PDF는 기존 Sol 6.1에서 출발한, 인증된 동일 양식/렌더러만 사용한다.** 1–3개 품목 단일 A4가 현재 독립 검증된 Sol 네이티브 범위다. 4개 이상은 [#3839](https://github.com/skerishKang/ai-revenue-lab/issues/3839)에서 그 **동일한 Sol 구현**을 확장·재인증한다. GLM 5.3의 비교본, 임의 HTML/브라우저 인쇄 양식 또는 모델 생성 PDF는 CGI 최종본의 대체 경로가 아니다.
2. [#3542](https://github.com/skerishKang/ai-revenue-lab/issues/3542): **신규로 승인된 고객 양식의 최초 분석·초기 양식 엔지니어링을 당분간 Sol 6.1로 수행**한다. 범용 자동분석기 구축 자체는 보류한다. 최초 분석으로 나온 `ANALYZED` 후보는 PDF 재현·인증([#3595](https://github.com/skerishKang/ai-revenue-lab/issues/3595)) 없이 반복 실행할 수 없다. 현재 CGI 원본을 다시 분석할 필요는 없다.
3. 견적 생성마다 Sol/B14에 PDF를 다시 그리라고 호출하지 않는다. 완전한 구조화 입력은 모델 호출 없이 진행하고, 자유문장 입력의 **새 사실 추출**만 사용자가 명시적으로 선택한 B14 모델이 맡는다. **QuoteCore만 금액·세금을 계산**하며 승인된 코드가 결정적으로 PDF를 만든다. 사용자 모델 임의 교체/자동 fallback 없음.
4. [#3586](https://github.com/skerishKang/ai-revenue-lab/issues/3586)의 **재사용 양식 등록**은 XLSX 현재 허용, XLS/HWP 거부, HWPX 추후 검토. 반면 [#3884](https://github.com/skerishKang/ai-revenue-lab/issues/3884)의 **고객 원본 비공개 보관** 및 일반 PDF/DOCX/이미지 **견적 사실 추출**은 별도 형식 정책이다. 보관에 성공했다고 양식 인증이 되는 것은 아니다.
5. 소스 병합, 모의/오프라인 테스트, 브라우저 Live 검증, Production 배포는 **별개의 완료 게이트**다. 검증 안 된 항목은 OPEN/NOT_VERIFIED로 표시한다. 과거 성공 사례를 다른 템플릿, 더 큰 행 수, 다른 계정 또는 새 서빙 버전의 증거로 전용하지 않는다.

## B66 주요 이슈 현황

| 이슈 | 상태/우선순위 | 실제 담당·진행 증거 | 남은 수용 기준 / 다음 행동 |
|---|---|---|---|
| [#3180](https://github.com/skerishKang/ai-revenue-lab/issues/3180) Saved Quote Skill EPIC | **OPEN** (상위) | CENTRAL/B66 종합; 현행 제품 계약 유지 | 원본 온보딩·인증·반복 생성의 통합 고객 여정 증명 후 종료 |
| [#3186](https://github.com/skerishKang/ai-revenue-lab/issues/3186) 새 견적서 만들기 | **OPEN · P1** | 자동/직접/맡기기 3경로 정의; CGI는 지원·직접형 우선 | 계정에 승인 Skill 연결해 반복 생성 실제 검증; 자동 분석을 현재 MVP 필수조건으로 승격하지 않음 |
| [#3405](https://github.com/skerishKang/ai-revenue-lab/issues/3405) D1 최근 견적 | **OPEN · P1** | 계정별 D1 이력 기반 소스 존재, 기존 브라우저 로컬 캐시 유지 | 실제 로그인/재로그인·다른 브라우저 복원·계정 A/B 격리·히스토리 에러 조건 검증; Drive가 이를 대체하지 않음 |
| [#3542](https://github.com/skerishKang/ai-revenue-lab/issues/3542) 최초 원본 분석 | **OPEN · 범용 자동화 보류** | **임시 분석 모델 Sol 6.1 (Owner 확정)**. 기존 CGI 원본 분석 완료 | 두 번째 고객 양식 필요 시 승인된 최초 온보딩에서 Sol 수동/보조 분석; 일반 자동분석기 신규 개발은 수행하지 않음 |
| [#3586](https://github.com/skerishKang/ai-revenue-lab/issues/3586) 등록 형식 | **OPEN · P0** | [PR #3963](https://github.com/skerishKang/ai-revenue-lab/pull/3963) **MERGED**, 로컬 B66 43/43와 CI 8/8; UI·모듈 XLSX 전용 사전검증 | 인증된 **실서버** XLSX 접수, 실제 형식/본문 검사, 원본 무결성 확인; #3884 서버/스토리지 준비와 연결 |
| [#3595](https://github.com/skerishKang/ai-revenue-lab/issues/3595) 원본 재현·인증 | **OPEN · P0** | 기존 CGI Sol 1–3행 기준 인증·1행 변이 테스트 근거 보존 | 다른 고객의 **실질적으로 독립된 두 번째 양식** 재현·변이·시각·자산 인증; CGI 4+행은 #3839에서 별도 재인증 |
| [#3708](https://github.com/skerishKang/ai-revenue-lab/issues/3708) 대형 컴파일러 | **OPEN · P2 · DEFERRED** | 외부 Modal/Oracle/GCP 실행 위치 **미선정** | 실제 두 번째 고객 수요/원본 보관·분석 근거 생길 때 계약, 비용·시간 실측 후 재개; CGI 인도 장애가 아님 |
| [#3839](https://github.com/skerishKang/ai-revenue-lab/issues/3839) Sol 다중 페이지 | **OPEN · LOCAL1 시각 수정 / 인증 전** | LOCAL1의 기존 Sol 6.1 기반 다중 페이지 원형 1~500행 독립 스트레스 11/11 PASS; LOCAL2 데이터 보존 [PR #3965](https://github.com/skerishKang/ai-revenue-lab/pull/3965) MERGED. 계획기 [Draft #3855](https://github.com/skerishKang/ai-revenue-lab/pull/3855)는 인증 렌더러 아님 | 헤더·합계·특기사항 등 주요 시각 결함은 개선됨. CENTRAL [최신 래스터 감사](https://github.com/skerishKang/ai-revenue-lab/issues/3839#issuecomment-6086936555)에서 원치 않는 **왼쪽 사선**을 추가 발견하고 PDF 연산자·피연산자 순서 수정 시 제거됨을 독립 확인; 수정 복사본 11/11 PASS. LOCAL1 원본 수정·이미지 회귀·정식 4+행 인증·실사용 Saved Skill→PDF→D1 E2E 및 Draft PR은 아직 별도 확인 필요 |
| [#3871](https://github.com/skerishKang/ai-revenue-lab/issues/3871) 고객 Google Drive | **OPEN · LOCAL3 실사용 E2E 진행 / 재열기 재검증 대기** | 기존 JSON+인증 PDF 소스 #3924/#3960, revoke 보안 #3981 병합. LOCAL3 실브라우저 보고: 기존 Padiem Chat OAuth 재사용·승인 JS origin·Pages 설정/배포 완료, 실제 합성 2품목 JSON+인증 PDF 2파일 저장·같은 소유자와 packageId 확인, 연결 해제 `/revoke` 0건, 재연결·파일 목록 성공. 재열기 fingerprint 불일치 수정 [PR #4007](https://github.com/skerishKang/ai-revenue-lab/pull/4007) **MERGED** (`afe837934f031c6dccba7246bb1626d402de33ef`) | CENTRAL은 소스 및 관련 테스트 8/8 + 최신 main 병합 시뮬레이션 8/8 확인. **#4007의 Production 제공·동일 계정 JSON 실제 재열기·다른 브라우저·수정 후 QuoteCore/PDF·계정 격리·실기기 검증은 아직 PASS 아님**. Owner 지정 LOCAL3가 남은 E2E 진행, 다른 로컬의 Drive 중복 수정 금지. [운영 체크포인트](https://github.com/skerishKang/ai-revenue-lab/issues/3871#issuecomment-6088291709) |
| [#3884](https://github.com/skerishKang/ai-revenue-lab/issues/3884) 고객 비공개 원본 | **OPEN · 중점 선행 의존성** | 기존 **별도 로컬 브랜치** `b66-template-custody-3884` / [Draft #3925](https://github.com/skerishKang/ai-revenue-lab/pull/3925); **로컬 번호는 GitHub 근거로 미확정** | HTTP 원문 크기 상한(파싱 전), OOXML 구조 안전성, R2 orphan 삭제실패 대응, D1 owner 분리 및 원본 SHA-256 복원, 버전/삭제/보유정책, 실제 cross-browser E2E. 현재 PR 미병합 |
| [#3906](https://github.com/skerishKang/ai-revenue-lab/issues/3906) 모델별 추론 수준 | **OPEN · Owner 승인 / LOCAL1 담당** | B66 사용자 선택 UI·`/quote/models`·`/quote/interpret` 계약은 LOCAL1 담당. 선행 B14 [#3977](https://github.com/skerishKang/ai-revenue-lab/issues/3977)의 backend 소스 [PR #3984](https://github.com/skerishKang/ai-revenue-lab/pull/3984) **7/7 CI 후 MERGED** | 정확한 모델·제공자별 공식 capability를 검증한 옵션만 노출하고 명시적 미지원 옵션은 4xx. B66 연동·실제 upstream payload·제품 E2E와 Production은 별도 미완료; 소스 선행 병합만으로 #3906 완료 금지 |
| [#3916](https://github.com/skerishKang/ai-revenue-lab/issues/3916) 근삿값 확인 | **CLOSED** | 기존 안전성 작업 종료 상태 확인 | 새 실제 회귀 증거 없으면 재오픈하지 않음 |

### #3839의 테스트 결과는 이렇게 구분

- **기존 Sol 인증:** 1–3행 단일 A4 패키지 재현과 QuoteCore 근거 있음.
- **LOCAL1 최신 실물 감사:** 기존에 접근하지 못했던 별도 산출물을 이후 찾았으며, Sol 6.1 기반 `sol61_multipage.py`와 실제 PDF·PNG 1~500행을 중앙에서 독립 확인했다. 헤더·합계·특기사항 개선 뒤에도 **PDF 경로 명령의 피연산자/연산자 출력 순서 오류** 때문에 왼쪽 비정상 사선이 남았고, CENTRAL은 원본을 건드리지 않은 복사본에서 한 루프 수정으로 제거·11/11 재검증했다. [상세 감사](https://github.com/skerishKang/ai-revenue-lab/issues/3839#issuecomment-6086936555). LOCAL1 정식 수정 반영·이미지 회귀·4행 이상 인증은 아직 미완료.
- **이전 별도 로컬 프로토타입:** PyMuPDF 테스트가 통과해도, **GLM53 기반 PDF/manifest**를 재사용했다면 Owner가 정한 Sol-native 인증을 충족하지 못함.
- **#3855:** 테스트에 쓰인 예시 지오메트리(예: 180pt 이름 열)를 실제 Sol 인증 치수로 간주하지 않는다.
- **#3965:** LOCAL2의 데이터 경로 **source-only 계약·테스트 PR이 22 PASS/1 SKIP 후 MERGED**(`f296df9b87aab9e60153358d62fe71e3e43fdfa1`). D1 개별 스냅샷 101개 보존과 상위 입력 허용 100개의 차이를 검증하되, 이 병합은 **실제 Sol PDF 4+행 고객 인수/E2E를 증명하지 않는다.**

## 인접 프로젝트 경계 — B14, Claw, Web

| 이슈 | 현황 및 담당 | B66 작업과의 경계 |
|---|---|---|
| [#3977](https://github.com/skerishKang/ai-revenue-lab/issues/3977) B14 공식 모델 파라미터 | **OPEN · LOCAL6 소스 병합 단계 완료**. [PR #3984](https://github.com/skerishKang/ai-revenue-lab/pull/3984) 7/7 CI 후 main MERGED (`8ce830113348fe2f4e6ca256e36faf3fbdd3bdae`) | provider-native 생략 기본값·모델별 명시 옵션 전달 소스 반영과 각 정확한 모델/서빙업체의 공식 capability 실증, 제품·스트림/비스트림 E2E 및 실제 운영 활성화는 별개. #3906 B66 UI와 중복 개발하지 않음 |
| [#3566](https://github.com/skerishKang/ai-revenue-lab/issues/3566) B54/Claw post-A7 502 | **OPEN; 최근 진단 담당 LOCAL3, 마지막 지시 STOP/STANDBY**. B14-상위 제공자 rate-limit 출처 및 안정적 최종 답변 미입증 | 모델 라우팅/Claw 정상답변 문제. B66 Sol PDF 재현 문제와 혼합하지 않음 |
| [#3382](https://github.com/skerishKang/ai-revenue-lab/issues/3382), [#3523](https://github.com/skerishKang/ai-revenue-lab/issues/3523) Claw Golden Path | **OPEN; CENTRAL 총괄** | Engine/Claw의 실제 로그인→AI 답변 E2E 별도 종료 기준 |
| [#3385](https://github.com/skerishKang/ai-revenue-lab/issues/3385) TinyFish Search/Fetch | **CLOSED · 신규 B66 업무 아님**. [PR #3950](https://github.com/skerishKang/ai-revenue-lab/pull/3950)·[#3957](https://github.com/skerishKang/ai-revenue-lab/pull/3957)·[#3975](https://github.com/skerishKang/ai-revenue-lab/pull/3975) MERGED. 별도 오래된 [Draft #3386](https://github.com/skerishKang/ai-revenue-lab/pull/3386)의 Core-검색 소스는 병합됐다고 간주하지 않고 폐기/보존 판단 대기 | TinyFish 기본·Daum 제한적 fallback의 **현재 소스 결정**과 실제 운영 설정/실검색 근거는 구분; B66 견적 생성, 고객 Drive·비공개 원본 권한과 혼합 금지 |

## 다음 단계 — 소유자·병렬 진행

1. **LOCAL1 (#3839):** 동일 Sol 6.1 다중 페이지 원본에서 `Program.emit_path()`가 PDF 피연산자를 연산자 **앞에** 방출하도록 수정하고 왼쪽 사선 **래스터 픽셀 회귀**를 추가한다. 기존 1~3행 바이트 동일성, 4·8·25·100 첫/마지막 페이지 시각 검증 및 11개 규모 스트레스 재실행 후 **Sol-native Draft PR** 제출. #3906 UI는 별도 브랜치, 공용 경로 충돌 금지.
2. **LOCAL2 (#3839):** PR #3965 **squash MERGED·해당 소스 계약 작업 종료**. 추후 LOCAL1 실제 PDF 연동 시 새로운 범위가 생기면 CENTRAL에서 별도 배정. 지금 동일한 소스 작업을 반복하지 않는다.
3. **#3884 기존 브랜치 소유 로컬:** #3925 보안 검토 잔여 조건 확인·수정; 운영 R2/D1 변이 없이 Draft→재검토. **번호 불명확하므로 중복 배정 금지**.
4. **LOCAL3 (#3871 ACTIVE):** Google OAuth/Pages 운영 배포와 합성 견적 JSON+인증 PDF 실제 Drive 저장 및 `/revoke` 0건·재연결은 LOCAL3 실측 보고로 확인됐다. 저장된 JSON의 템플릿 프로필 fingerprint 불일치 수정 PR #4007은 main 병합. **다음은 새 app.js가 실제 서비스에 제공되는지 확인한 뒤** 동일 계정 재열기 → 다른 브라우저 재열기 → 수량·단가 수정/QuoteCore 재계산 → 인증 PDF → 로그아웃·계정 격리·휴대전화 검증. CENTRAL은 GitHub 코드/CI만 독립 확인했으므로 실사용 E2E 성공을 선포하지 않는다. LOCAL6의 과거 Drive 소스 작업 완료, LOCAL3 계속 담당.
5. **CENTRAL:** LOCAL6 [PR #3984](https://github.com/skerishKang/ai-revenue-lab/pull/3984) B14 backend source MERGED(7/7 CI)를 #3977·#3906 인수 사항으로 추적하되, 모델별 공식 제공업체 capability/실제 추론 수준 전달 검증·Production 별도 게이트는 유지한다. #3884 Draft #3925 보안·운영 인수 미완료; #3542/#3708 범용 자동 컴파일러는 Owner 재개 요청까지 보류.

## 중복·통폐합 판정 (2026-10-10)

- **통합 관리, 이슈 자체 유지:** [#3180](https://github.com/skerishKang/ai-revenue-lab/issues/3180) 제품 Epic 아래 #3839(Sol 품목 확대), #3595(별도 원본 인증), #3884(고객 원본 custody), #3871(선택적 Google Drive), #3405(D1 이력)를 연결하되 **완료 증거와 소유권이 달라 일괄 종료·기능 병합하지 않는다**.
- **B14 계약 중복 개발 금지:** #3977은 LOCAL6 backend 공급자 요청(소스 PR #3984 병합), #3906은 LOCAL1 B66 UX 소비자, #2676은 모델 성능 재평가, #3554는 실제 응답 E2E, #2698은 미승인 Auto Router 보류. 모델 ID 선택을 자동화하지 않는다.
- **Claw 상위·원인 분리:** #3523은 Production Golden Path 총괄, #3382는 로그인→실제 답변 사용자 E2E, #3566은 B14 post-A7 502 원인, #3930은 SSE 실시간 화면. 하나가 소스 병합됐다는 이유로 전체 종료 금지.
- **보류 유지:** #3542 최초 새 원본 분석과 #3595 인증은 독립 단계. #3708 외부 대형 컴파일러와 #3736 Modal PDF standby는 **실제 신규 고객 요구 전 활성 개발 제외**, 필요 시 Owner가 한 번에 재검토하되 무증거로 지금 병합·종료하지 않는다.
- **오래된 Draft 관리:** 현재 열린 PR 다수 중 #3597(B14 과거 provider max-token/UI), #3914(Agnes 진단), #3386(Core TinyFish), #3855(Sol 계획기), #3830/#3835(StepFun 평가)는 최신 merged #3984/#3975·#3839 실제 엔진과 계약·파일 충돌 가능성이 있다. **별도 존치 사유와 최신 main 재기반 검증 없이 병합 금지**. 역사적 증거가 필요한 PR은 Draft/보류로 보존하고, 겹치는 코드를 이미 구현했다는 사실만으로 자동 폐기하지 않는다.

## 종료 규칙 및 원본 보호

- 이슈 종료: **기능 코드 + 정확한 HEAD CI + 승인된 수용 E2E + 기존 기능 회귀 + 운영 배포 상태**를 이슈별로 따로 증명한다. Source-only 이슈라면 범위를 명시하고, 실서비스 수용이 남아 있다면 OPEN 유지.
- 공개 표준 CGI `reference/b66-public-standard-templates/cgi/v1`과 고객 비공개 원본(R2/D1)은 별개의 저장소·권한이다. 비공개 원본/로고/인장·실계정·토큰은 공개 Git/검증 로그에 게시하지 않는다.
- 다른 LOCAL의 브랜치/작업 폴더/담당 소유권을 임의 침범하지 않는다. Production, 시크릿/OAuth, 과금 서비스 호출, 데이터 마이그레이션은 별도 게이트다.
