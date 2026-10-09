# B66 활성 이슈·PR·담당 현황 — 2026-10-10

> **성격:** CENTRAL CTO의 시점별 작업 현황표. 기능 요구사항의 법적/기술적 권위는 각 이슈와 [B66 README](README.md), [SOURCE_TEMPLATE_FIDELITY.md](SOURCE_TEMPLATE_FIDELITY.md)에 있다. 상태가 바뀌면 실시간 GitHub 상태를 우선한다.
>
> **조사 기준:** 2026-10-10 KST, 저장소 `skerishKang/ai-revenue-lab`, 작업 시작 main `b55b634c7f17e5581cfc9ea26da57eea43453f10`.
> **범위:** 현재 대화에서 검토한 B66 원본 양식/견적 기능과 직접 연결된 B14·Claw 이슈. 저장소의 *모든* OPEN 이슈를 포괄한 대장이 아니다.

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
| [#3839](https://github.com/skerishKang/ai-revenue-lab/issues/3839) Sol 다중 페이지 | **OPEN · 현재 핵심 구현** | **LOCAL1=Sol 네이티브 구현·인증**; **LOCAL2=입력/보존 테스트**. [Draft #3855](https://github.com/skerishKang/ai-revenue-lab/pull/3855)=페이징 계산만. [Draft #3965](https://github.com/skerishKang/ai-revenue-lab/pull/3965)=다품목 한계/보존 테스트 | 실제 Sol 4/8/10/25/100+행 PDF, 페이지/서체/직인/로고·QuoteCore 합계·이전 데이터 잔존·고객 E2E 확인. GLM 기반 시험 결과는 Sol 인증으로 불인정 |
| [#3871](https://github.com/skerishKang/ai-revenue-lab/issues/3871) 고객 Google Drive | **OPEN · P2 / Live BLOCKED** | **LOCAL6/COMP2**. [PR #3924](https://github.com/skerishKang/ai-revenue-lab/pull/3924) 소스 MERGED. [PR #3960](https://github.com/skerishKang/ai-revenue-lab/pull/3960) OPEN, CENTRAL 수정 요청 | 실제 Pages 환경설정 전달 경로·잘못된 ID 차단 수정 후 신규 CI. B66 전용 Web OAuth 클라이언트/JS origin, 별도 Production 릴리스 승인, 격리된 테스트 계정으로 JSON+인증 PDF 쌍 저장·다른 브라우저 불러오기·실기기 검증 |
| [#3884](https://github.com/skerishKang/ai-revenue-lab/issues/3884) 고객 비공개 원본 | **OPEN · 중점 선행 의존성** | 기존 **별도 로컬 브랜치** `b66-template-custody-3884` / [Draft #3925](https://github.com/skerishKang/ai-revenue-lab/pull/3925); **로컬 번호는 GitHub 근거로 미확정** | HTTP 원문 크기 상한(파싱 전), OOXML 구조 안전성, R2 orphan 삭제실패 대응, D1 owner 분리 및 원본 SHA-256 복원, 버전/삭제/보유정책, 실제 cross-browser E2E. 현재 PR 미병합 |
| [#3906](https://github.com/skerishKang/ai-revenue-lab/issues/3906) 모델별 추론 수준 | **OPEN · PROPOSAL / Owner 결정 대기** | B14×B66 UX 정책·견적 추출 실측 근거만; 기능 미구현 | 수동 모델 선택 유지, 제공자별 지원 추론 수준 실측·upstream 전송 확인, B14 레지스트리→API→UI 계약·기본/권장 의미·저장정책 Owner 승인 후 착수 |
| [#3916](https://github.com/skerishKang/ai-revenue-lab/issues/3916) 근삿값 확인 | **CLOSED** | 기존 안전성 작업 종료 상태 확인 | 새 실제 회귀 증거 없으면 재오픈하지 않음 |

### #3839의 테스트 결과는 이렇게 구분

- **기존 Sol 인증:** 1–3행 단일 A4 패키지 재현과 QuoteCore 근거 있음.
- **LOCAL1 별도 공간 감사:** 보고된 `sol61_multipage.py` 및 8행 3페이지 PNG가 **그 작업 공간에서 발견되지 않아** 8행 다중 페이지 16/16 주장 재현 불가. 다른 작업 공간에 파일이 전혀 없었다는 뜻은 아님.
- **이전 별도 로컬 프로토타입:** PyMuPDF 테스트가 통과해도, **GLM53 기반 PDF/manifest**를 재사용했다면 Owner가 정한 Sol-native 인증을 충족하지 못함.
- **#3855:** 테스트에 쓰인 예시 지오메트리(예: 180pt 이름 열)를 실제 Sol 인증 치수로 간주하지 않는다.
- **#3965:** LOCAL2의 변경은 데이터 경로의 *source-only 테스트*다. 최신 브랜치에 CENTRAL 피드백 수정이 들어왔더라도 **새 HEAD CI와 리뷰 후** 병합하고, 이를 실제 Sol PDF 합격으로 표현하지 않는다.

## 인접 프로젝트 경계 — B14, Claw, Web

| 이슈 | 현황 및 담당 | B66 작업과의 경계 |
|---|---|---|
| [#3566](https://github.com/skerishKang/ai-revenue-lab/issues/3566) B54/Claw post-A7 502 | **OPEN; 최근 진단 담당 LOCAL3, 마지막 지시 STOP/STANDBY**. B14-상위 제공자 rate-limit 출처 및 안정적 최종 답변 미입증 | 모델 라우팅/Claw 정상답변 문제. B66 Sol PDF 재현 문제와 혼합하지 않음 |
| [#3382](https://github.com/skerishKang/ai-revenue-lab/issues/3382), [#3523](https://github.com/skerishKang/ai-revenue-lab/issues/3523) Claw Golden Path | **OPEN; CENTRAL 총괄** | Engine/Claw의 실제 로그인→AI 답변 E2E 별도 종료 기준 |
| [#3385](https://github.com/skerishKang/ai-revenue-lab/issues/3385) TinyFish Search/Fetch | **OPEN; LOCAL3**. [#3950](https://github.com/skerishKang/ai-revenue-lab/pull/3950) 합병, [#3957](https://github.com/skerishKang/ai-revenue-lab/pull/3957) Draft. 계정 요율/무료 표시는 검증했지만 Search/Fetch 라이브 비교·상업 조건 미확정 | 웹 검색용; B66의 결정적 견적 처리·고객 비공개 파일 검색에 끼워 넣지 않음 |

## 다음 단계 — 소유자·병렬 진행

1. **LOCAL1 (#3839):** 인증 Sol 벡터 패키지 기하·출처 확정 → Sol-native 가변 행/다중 페이지 **실제 PDF** → 1–3행 회귀 및 4/8/10/25/100+행 재인증. 이전 GLM/HTML 우회 금지.
2. **LOCAL2 (#3839):** #3965의 테스트 계약을 기존 소스 권위에만 연결; 업데이트 HEAD CI 후 CENTRAL 검토. 이미 입증한 D1 개별 스냅샷 능력을 전체 Save→Render E2E로 과장하지 않음.
3. **#3884 기존 브랜치 소유 로컬:** #3925 보안 검토 잔여 조건 확인·수정; 운영 R2/D1 변이 없이 Draft→재검토. **번호 불명확하므로 중복 배정 금지**.
4. **LOCAL6/COMP2 (#3871):** #3960 Pages 런타임 config 주입 및 malformed ID fail-closed 수정 → 새 HEAD CI → 별도 운영 OAuth/릴리스 승인 후 실제 Google Drive 검증.
5. **CENTRAL:** 각 PR의 최신 base/head/검증과 소유권 확인, 소스만으로 종료 처리 금지. #3586 실서버 입력 검증은 #3884 선행 기반 준비 후 실행. #3542/3708 일반 컴파일러는 Owner 재개 지시 전 착수 금지; #3906은 승인이 필요한 UX 제안으로 유지.

## 종료 규칙 및 원본 보호

- 이슈 종료: **기능 코드 + 정확한 HEAD CI + 승인된 수용 E2E + 기존 기능 회귀 + 운영 배포 상태**를 이슈별로 따로 증명한다. Source-only 이슈라면 범위를 명시하고, 실서비스 수용이 남아 있다면 OPEN 유지.
- 공개 표준 CGI `reference/b66-public-standard-templates/cgi/v1`과 고객 비공개 원본(R2/D1)은 별개의 저장소·권한이다. 비공개 원본/로고/인장·실계정·토큰은 공개 Git/검증 로그에 게시하지 않는다.
- 다른 LOCAL의 브랜치/작업 폴더/담당 소유권을 임의 침범하지 않는다. Production, 시크릿/OAuth, 과금 서비스 호출, 데이터 마이그레이션은 별도 게이트다.
