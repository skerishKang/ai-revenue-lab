# PADIEM Connector — 플랫폼 제품 결정 및 구현 로드맵 (2026-10-12)

**상태:** 사용자 비전/구조 결정 + 검증된 기존 코드 목록. **전체 제품 구현·출시 선언 아님.**  
**기준:** `skerishKang/ai-revenue-lab`, 2026-10-12 KST.  
**통합 구현:** [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139) / **Windows 실사용 수용:** [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099) / **통합 홈·관리자:** [#4428](https://github.com/skerishKang/ai-revenue-lab/issues/4428) / **Browser Use:** [#3782](https://github.com/skerishKang/ai-revenue-lab/issues/3782), [#3783](https://github.com/skerishKang/ai-revenue-lab/pull/3783) / **Hark E2E:** [#3936](https://github.com/skerishKang/ai-revenue-lab/issues/3936).

## 2026-10-13 정정 — 고객 브랜드 분리 및 구현 상태 우선 적용

**최신 고객 결정:** PADIEM Claw/Chat/Engine과 **B66 견적은 독립된 고객 서비스**다. 내부 Identity/Control Plane·Broker·Windows Connector의 코드 재사용은 허용되지만, **통합 고객 계정/메뉴/PC 목록·동일 이메일 기반 자동 연결·권한 공유를 의미하지 않는다**. B66에는 견적 서비스 전용 회원·PC 화면을, PADIEM에는 PADIEM 전용 회원·PC 화면을 별도로 제공한다. 교차 브랜드 연결은 향후 검증된 사용자 승인과 별도 권한 심사 전까지 OFF다. 본 문서의 2026-10-12 'B66/Claw/Chat을 한 계정/메뉴로 묶는다'고 읽히는 표현은 이 결정을 우선하여 제한 해석한다.

**진행 상태:** S1 Windows tray #4420과 제품별 PC 사전 정책 #4429는 **병합된 소스**다. 그러나 CENTRAL [Draft #4476](https://github.com/skerishKang/ai-revenue-lab/pull/4476)·LOCAL2 [Draft #4490](https://github.com/skerishKang/ai-revenue-lab/pull/4490)는 **미병합·운영 OFF**, 실제 PC 등록/신뢰된 전송/ACK/ONLINE/권한 있는 업무 실행의 성공 증거가 아니다. 중앙 Draft에는 해결 전 GitGuardian 탐지가 존재한다. 제품 실기기 출시 수용은 여전히 #3099 OPEN이다. **단일 최신 점검 인덱스:** [#4139 중앙 상태·이슈 통합](../operations/PADIEM_CONNECTOR_4139_CENTRAL_STATUS_20261013.md) (소스/문서 스냅샷, 기능 승인 아님).

## 1. 한 문장으로 정의

**PADIEM Connector = 하나의 PC 설치 프로그램으로 웹 기반 PADIEM AI 제품이, 사용자 허가 범위 안에서, 해당 PC의 파일·프로그램·전용 브라우저·격리 실행 환경을 공유해 쓰는 공통 로컬 실행 기반.**

PADIEM 웹(Claw/Chat/Engine/향후 승인 제품) 및 독립 브랜드 B66 Quote 웹은 **업무 요청·승인·상태·미리보기·최종 산출물**을 제공한다. 사용자는 별도의 Browser Use 앱, Desktop Commander형 UI, RDP, CLI, 수동 업·다운로드 또는 제품별 페어링 절차를 배울 필요가 없도록 설계한다. Windows Connector에는 경량 트레이/상태·일시정지·연결해제·계정·권한 안내만 기본 제공한다.

**잠정 대외 제품명: PADIEM Connector.** 기존 S1 경로/내부 명칭은 `apps/claw-connect/**` / Claw Connect로 유지한다. 향후 제품명 전환은 계정 등록·기기 identity와 호환성을 검증한 별도 변경에서 진행하며, 이름만 바꾼 것으로 one-click 연동 완료를 선언하지 않는다.

## 2. 실제 고객 경험: 설치 한 번 + 확인된 동일 계정 로그인

1. 고객은 이용 중인 서비스(PADIEM 또는 B66 견적)의 **별도 승인된 설치 진입점**에서 Connector를 내려받아 PC에 설치한다. 서비스 사이의 계정·기기는 기본적으로 연결되지 않는다.
2. **최초 1회(명시적으로 승인된 계정·브랜드 범위)** 해당 제품의 검증된 계정으로 안전하게 로그인하고, **이 PC 등록/활성화에 명시적으로 동의**한다. 동일 이메일 표기만으로 동일 계정이라고 판단하지 않는다.
3. 서버는 기존 검증된 identity + workspace + 기기 소유 증명을 사용하여 **Canonical Broker**의 단일 device authority에 등록한다. 내부 canonical Broker는 단일 device ID를 재사용할 수 있으나, **제품·브랜드마다 검증된 인증과 명시적 연결 승인 없이는 같은 PC를 노출하지 않는다**. 별도의 웹 '연결 버튼'/QR/코드/서드파티 MCP 커넥터 설정을 기본 요구하지 않는다.
4. 안전하게 저장된 자격증명·짧은 세션·회전/철회 정책과 outbound 연결/heartbeat로 재연결한다. 재부팅 자동 시작은 사용자 선택이다. 잠자기·오프라인·계정 철회 때는 즉시 unavailable.
5. **등록 != 파일 접근/터미널/브라우저 실행 허가.** 각 제품 capability grant는 기본 OFF이며 작업별 대상·범위·기기·승인(P01 READ vs 별도 WRITE), WorkTicket, 만료/재생 방지, 감사가 별도로 필요하다.
6. 외부 ChatGPT/Claude 연계는 향후 명시적으로 동의받는 별도 커넥터 경로다. PADIEM 자체 제품 사용에 필요하지 않다.

기업 공용 PC는 정책에 따라 관리자의 기기 승인도 요구할 수 있다. 가입/로그아웃/계정 전환 시 다른 사용자 기기 목록과 작업 결과가 노출되면 안 된다.

## 3. Authority 및 모듈 경계 — 절대 중복 생성 금지

| 구성 | 유일한 책임 | 책임이 **아닌 것** |
|---|---|---|
| **B14** | AI 제공업체·모델 실행 및 라우팅 | PC/device/tenant/P01/로컬 프로그램 실행 권한 |
| **PADIEM Identity / Control Plane** | 인증된 owner/workspace, 제품 구독/권한, 실행 사전 검증 | 새로운 로그인 인증기관 생성, Broker 기기 저장소 복제 |
| **Canonical Local Agent Broker** | 기기 식별/등록/세션/heartbeat/작업 및 정규 사실 | 제품 UI, AI 모델 라우팅, 사용자 브라우저 쿠키 저장 |
| **기존 P01·WorkTicket** | 스코프가 제한된 READ/WRITE 승인·1회 실행 근거 | UI 로그인만으로 승인 발급 |
| **PADIEM Connector** | outbound Resident, 원격 작업의 제한된 로컬 실행, 결과/영수증 전송 | 제2 Broker, 제2 P01 서버, 무제한 화면·파일·쉘 권한 |
| **각 제품** | 실제 업무·UX·고객 산출물·제품별 정책 | 글로벌 관리자·공통 기기 소유권 자체 발급 |

**이미 병합:** canonical Broker device directory PR #4418, B62 인증된 Claw 기기 조회 #4424, 기기 목록 UI #4419, 공통 제품별 PC 접근 계약 [#4429](https://github.com/skerishKang/ai-revenue-lab/pull/4429) (2026-10-12, squash SHA `dbf8d658b2a8cd03c64ee4e3b86899136fe2bb40`), B66 embedded quote 화면의 제품 승인 조건 기본 OFF PC 정보 패널 [#4430](https://github.com/skerishKang/ai-revenue-lab/pull/4430). **이것들이 설치 후 자동 접속·파일 전송·실행 성공을 뜻하지 않는다.** #4429의 `PcPreflightDecision.dispatch_authorized`는 언제나 `False`이다.

**2026-10-12 S1 Windows 소스 병합:** 트레이·사용자별 설치·종료 복구 #4420 (main `9047933dc3a5f5c573375f5da16b2a5d52c180ef`), 정확한 PR HEAD에서 Windows pytest 57/57, Node 5/5, LOCAL2 실제 Windows 종료 하네스 7/7. 트레이 `웹 열기`는 운영 `https://chat.padiem.net/`으로 수정. **단, 아직 placeholder Resident(`python -c pass`)와 기본 disconnected probe를 사용하므로 검증된 PADIEM 계정 등록·온라인 presence·실제 파일/명령 실행이나 배포된 고객 설치 프로그램은 아니다.** Browser Use #3783은 Draft이며 2-PC 등록·Office 실행·파일 왕복 운영 E2E #3099는 미증명. **제품 실행 OFF.**

## 4. 실행 환경 선택 전략 — '항상 로컬 Excel이 더 빠르다'고 가정 금지

실행 유형을 제품과 사용자에게 감추되 근거와 상태를 남기는 **Capability Router**를 공통 Engine/Control Plane에서 구성한다. 새 모델 엔진을 만들지 않는다.

| 순서 | 실행 환경 | 적합한 업무 | 주요 제약 |
|---|---|---|---|
| A | 서버/클라우드 파일 처리, API, CLI | 단순 XLSX 수정, 일반 문서, ERP API, 데이터 정리 | 원본 서식/수식의 정확성 검증, 데이터 위치/비용 |
| B | PADIEM Connector의 로컬 API/파일·CLI | 고객 PC 설치 프로그램의 정식 API, 큰 파일, 로컬에만 있는 리소스 | 사용자 승인·연결 상태·백그라운드 지원 |
| C | **에이전트 전용 내장 브라우저** | 로그인된 업무 웹, 웹 페이지 읽기/제한된 폼 작업 | 별도 프로필·사이트 정책·2FA·작업별 허가 |
| D | 감시/격리된 Windows GUI 자동화 | 설치된 Excel/한글/HWP/레거시 ERP의 UI 전용 기능 | 사용 중인 화면/키보드/포커스/팝업/UAC 충돌 |
| E | 선택적 Windows VM / 정당하게 라이선스된 Cloud PC | 사용자가 같은 PC를 쓰면서 AI도 GUI를 독립적으로 실행 | 별도 guest Windows 및 앱 설치/라이선스, 용량·RAM·비용 |

**Windows 가상 데스크톱은 별도 보안 사용자 세션/가상머신이 아니다.** 호스트에 Excel이 설치됐다고 VM 게스트에서 공짜로 실행되는 것도 아니다. 일반 고객의 MVP에서 VM 설치를 의무화하지 않는다. GUI가 사용자 작업을 방해할 가능성이 있으면 UI 자동화를 강행하지 말고 일시 중단·알림·승인/격리 환경 옵션을 제공한다. PC가 잠자기나 종료 상태면 실제 실행 불가이며, 가용성 표시·대기/만료가 정확해야 한다.

성능 판단 시 서버↔로컬 파일 왕복 전송, 데이터 크기, 엔진 기동 시간, 재시도와 정확성을 함께 측정한다.

## 5. 내장 Browser Use: 사용자가 브라우저를 몰라도 되는 구조

**한 설치파일 + Connector 전용 격리 브라우저 프로필**을 원칙으로 한다. Chrome/Edge 개인 쿠키, 비밀번호 저장소, 북마크, 다른 제품/다른 워크스페이스 프로필을 자동 가져오지 않는다. 사이트별 로그인은 고객이 명시적으로 허용하고 유효한 세션만 재사용한다.

- 일반적인 조회·작업은 가능한 범위에서 백그라운드/헤드리스 실행.
- 로그인·MFA·패스키·CAPTCHA·개인정보 승인·사이트 오류·작업 보조가 필요할 때 **보이는 별도 에이전트 브라우저 창으로 사람에게 안전하게 인계**. CAPTCHA/MFA 우회 금지.
- 웹 페이지 내용은 비신뢰 입력이다. 웹페이지의 프롬프트 인젝션은 파일·쉘·새 도메인·계정 변경을 승인할 수 없다.
- Origin/allowlist, 명령 수/시간, P01 READ/WRITE 및 민감 행동별 추가 승인, 중단 버튼, 기록 및 영수증을 강제한다.
- 기존 browser.control Broker/P01/WorkTicket 구현(#3782/#3783) 재사용. 별도 상시 원격 데스크톱 제품이나 두 번째 브라우저 실행 기관 생성 금지.
- '항상 창이 뜨지 않는다'는 보장은 불가능하므로 사용자가 도와야 할 상황을 예상한 디자인 적용.

## 6. 가장 중요한 데이터 흐름 — 웹 XLSX → 로컬 처리 → 웹 산출물

사용자는 웹에 XLSX **한 번만** 올린다. Connector가 기존의 작업 사본을 안전하게 자동 수신한 다음 처리하고 결과를 웹으로 반송하는 UX가 목표다.

```text
별도 인증된 B66 Quote 또는 PADIEM Claw/Chat 웹: XLSX 업로드
    ↓ (인증된 owner/workspace private store; immutable source SHA256)
PADIEM 서버: 저장/작업 대기 + 정확한 대상/작업 승인
    ↓ (기존 Broker로 PC 작업 전달, 파일 본문/브라우저 쿠키는 실어 보내지 않음)
PADIEM Connector: 작업 티켓 수신 → scoped TLS 파일 다운로드
    ↓ (바이트 크기/sha256/문서 유형 검증, run별 격리 임시 폴더)
적합한 실행 경로 선택: 파일 라이브러리/CLI 또는 허용된 로컬 Excel
    ↓ (원본 별도 유지, READ 승인과 WRITE 승인 분리)
PADIEM Connector: 검증된 결과·receipt 업로드
    ↓
PADIEM 웹: 수정 XLSX/PDF 미리보기·다운로드·실행/오류 이력
```

**전송 주체는 권한 있는 Connector의 Pull 방식(outbound HTTPS)**으로 설계한다. 서버에서 집 PC로 직접 inbound 포트를 열거나 사용자가 IP·RDP를 설정하게 하지 않는다.

**현존 재사용 자산:**
- `apps/padiem-chat/app/claw_web_xlsx_source_routes.py`: owner/workspace 범위로 업로드·목록·다운로드 (현재는 업로드 자체로 P01 처리 승인이 생기지 않음).
- `apps/padiem-chat/app/claw_web_xlsx_p01_owner_decision_routes.py`: 승인된 원본의 해시 검증 및 workcopy 다운로드 (현재 **브라우저 사용자 세션 기준**; Connector의 M2M artifact delivery는 **별도 개발 필요**).
- `apps/korean-ai-code-agent/src/kagent/local_xlsx_artifact_handoff.py`, `local_office_chunk_publisher.py`: 로컬→서버 방향 전달 계약 일부 (Resident 운영 전체 배선/역방향 웹→로컬 자동 전달 증거 아님).
- 파일을 직접 R2/D1 키로 받아가도록 개방하거나, 브라우저 쿠키를 Connector에 넘기지 않는다. 정확한 owner/workspace/product/device/run/artifact/hash/TTL과 1회용 전달 권한을 기존 authority로 검증한다.
- 사용자의 Documents 폴더를 임의로 덮어쓰지 않는다. 임시 사본, sha256·크기 검증, 안전한 저장·정리 정책 및 실패 시 재처리/중복 처리 방지 적용.

**실제 웹→로컬 자동 전달 및 로컬 Excel→웹 결과 E2E: 미구현/미증명.** 위 코드는 바로 조합한다고 동작하는 기성 기능이 아니다.

## 7. 제품/고객·운영 화면 — 무엇을 보여야 하는가

**PADIEM 통합 홈(고객):** PADIEM 브랜드 안에서 승인된 제품/등급·권한, 권한 있는 PC 온라인 상태(실제 Broker), 실행 중/완료/차단 작업, 결과물, 승인 대기, 연결 관리. **B66 견적 고객은 포함하지 않는다**.  
**제품별 대시보드:** PADIEM Claw 작업·Chat 대화·Engine 실행과 B66 견적서 UX는 고객에게 별개의 브랜드·로그인·메뉴로 제공한다. 브랜드 간 공통 제품 전환 헤더는 기본 제공하지 않으며, 각 권위 있는 데이터 저장소도 분리 유지.  
**PADIEM 통합 관리자(운영자):** 회원·제품별 entitlement, B14 모델별 접근/비용/사용량, PC 등록/철회, 승인/감사/오류, 연결 및 실행 상태. 처음은 최소 범위 READ-ONLY로 시작하고 권한 수정은 정규화된 중앙 RBAC·감사를 완료한 뒤 단계적 추가. B66 개별 관리자라는 이유만으로 글로벌 관리자 권한 부여 금지.  
**기존 Portfolio Console:** 개발/PR/CI/배포 운영 전용, 일반 고객 홈과 통합 금지.

사용자 웹 화면에는 업무 결과와 허가 요청을 중심으로 배치하고, GUI/RDP 화면은 로그인·오류·직접 보기/보조가 필요할 때만 노출. 가상화·브라우저 프로필·임시 폴더 같은 개념은 기본 UX에서 숨긴다.

## 8. 단계별 실행 우선순위와 수용 조건

| 단계 | 실제 산출물 | 출하/활성화 필수 조건 |
|---|---|---|
| S0 **현존** | Broker 기기 조회, Claw 조회 UI, 기본 OFF 제품 권한 계약, B66 embedded 숨김 PC 패널 | CI·코드 존재는 출하 증거 아님 |
| S1 **부분 구현** | Windows 설치/트레이·종료 안정화 #4420 병합. 동일 계정 최초 검증된 인증·PC 등록·재연결은 미배선 | 실제 PC 2대, 인증·동의·재설치·철회/오프라인, owner/workspace 분리. **현재 제품 온라인/실행 OFF** |
| S2 **부분 구현** | B66 전용 서버 PC 목록 권한 #4439 병합, Claw API 존재. Chat/Engine 제품별 연결 및 운영 정책 공급원은 후속 | **기본 OFF 유지**, 운영 grant·실제 인증 PC·배포 E2E 미완료 |
| S3 | **웹 XLSX→Connector 제한된 Pull→결과 웹 반환** | Scoped artifact ticket, 해시·크기, READ/WRITE 승인 별도, 실패·취소·중복 처리, Windows Excel 실작업 증거 |
| S4 | Connector 전용 Browser Use/profile + 사람 로그인·MFA 인계 | 기존 browser.control + P01 안전 게이트, 다른 크롬 개인세션 비접근, 실제 사이트 허용 범위 QA |
| S5 | Native GUI(HWP/ERP/Excel UI), 선택 VM/Cloud PC | 동시 사용 간섭 방지, 라이선스·비용 검증, 안전한 중단/관찰 및 승인 |
| S6 | 통합 대시보드/통합 관리자 상세화, 제품별 정책 일원화 | 글로벌 RBAC·감사·쿼터/비용의 신뢰 가능한 소스, 실제 서비스 화면 QA |

GUI 자동화/VM 전체를 최초 출시 선행 조건으로 만들지 않는다. S1/S2/S3으로 사용자가 체감할 수 있는 XLSX 완결 흐름부터 검증한다.

## 9. 동시 작업·책임자

- **CENTRAL:** 제품 통합 홈·관리자, B66/Chat/Engine 제품 API/UI, 전체 이슈·PR·CI·배포 및 실제 사용자 흐름 수용.
- **LOCAL1:** canonical Control Plane/Broker 제품별 grant 및 PC 실행 전제의 안전한 단일 계약. #4429 **병합**. 후속은 새 명확한 브랜치/PR에서 독립적으로 수행.
- **LOCAL2(Windows):** `apps/claw-connect/**` #4420의 설치·트레이·Resident 검증. Browser Use 앱 전체를 무리하게 같은 PR에 넣지 않음.
- **Browser Use 담당:** #3782/#3783의 기존 Broker/P01/browser.control. LOCAL2 또는 다른 에이전트의 별도 브라우저 명령 권위기관 구축 금지.
- **LOCAL2(Hark QA, 별도 레인):** #3936의 adopt 실사용 차단은 **소유자 인증 세션·완료 XLSX 데이터가 없어 BLOCKED**. Connector 완료 보고와 혼동 금지.

## 10. Hark adopt QA — 확인된 범위와 차단 (2026-10-12)

LOCAL2 보고에 따르면 `D:\padiem-hark-xlsxadopt-3936-261012-7\evidence\hark_3936_adopt_live_authboundary_20261012.txt`에 운영 익명/합성 QA 인증 경계 검증을 저장했다(파일 자체의 중앙 독립 검토는 별도). reported: adopt UI JS 2개 운영 응답과 당시 main `acd31e29e...` 바이트 패리티, 테스트 31 PASS, 익명 adopt/followup 401, 합성 QA 인증 세션에서 잘못된 cid 400·무산출물 404, web-sources 200. **이 결과는 사용자의 진짜 완료 XLSX adopt 성공/새 P01 READ 실행 증거가 아니다.** 합성 QA 계정 1개가 생성되었고, WRITE/P01/XLSX 생성은 하지 않았다고 보고됐다.

반면 현재 최신 main은 이후 변경되어 `acd31e29e...`가 아니다. '현재 main과 동일'이라는 진술은 그때 검사한 커밋에만 유효하다. QA 소유자 세션 없음(브라우저 게스트), 이전 일회용 계정에 재사용 가능한 완료 XLSX 없음, wrangler token 9109. **owner가 브라우저에 직접 로그인하기 전에는 그 계정의 사적 XLSX 존재 여부를 '없음'으로 확정하면 안 된다.** 승인 버튼은 owner가 누르고, QA는 그 경계까지 준비/증빙만 한다.

이 사안은 [#3936](https://github.com/skerishKang/ai-revenue-lab/issues/3936)에서만 별도로 추적한다. PADIEM Connector Windows #4420의 완료와 연결해 보고하지 않는다.

## 11. 구현 불가/금지 오해 목록

- '프로그램 설치만 하면 자동 연결'은 실제로 **1회 안전한 동일 계정 로그인·PC 등록 동의가 필요**하다.
- '브라우저가 알아서 로그인'은 **명시적으로 승인한 외부 사이트 세션만 재사용**한다. MFA/CAPTCHA 우회·개인 쿠키 가져오기 금지.
- '로컬 엑셀이 서버보다 항상 빠르다'는 확인되지 않았다. 파일 왕복·Excel 기동·서식 정확도를 기준으로 실행 위치 선택.
- 'PC 연결이 곧 Desktop Commander 무제한 권한'이 아니다. 등록·읽기·쓰기·터미널·브라우저 실행은 각각 제한되고 P01/WorkTicket으로 연결된다.
- '가상 데스크톱을 열면 Excel이 격리되어 같이 돌아간다'는 아니다. 독립 세션/VM/Cloud PC는 기술/라이선스/OS 제약 검증 필요.
- 'PR 병합 = Windows PC 실사용 성공'이 아니다. #3099를 실제 인증 Windows E2E 전까지 닫지 않는다.

## 12. 세부 후속 논의 연결

- Connector 전체/파일 전송/Windows QA: #4139, #3099, #4420.
- Browser Use 전용 프로필·신뢰되는 작업 명령: #3782, #3783.
- 고객 홈·전 제품 관리자·제품별 UI: #4428.
- 제품/로컬 공통 권한 계약: #4429 (기본 OFF, preflight only, 병합).
- B66 embedded UI: #4430 (병합). B66 전용 서버 API·워크스페이스별 제품 권한 검증 #4439 (2026-10-12 병합, `5db28a4ef6b0706b761623e187a0510eebc42ffc`). `/api/b66/connect/devices`를 사용하며 canonical Claw/Broker read projection을 재사용한다. 운영 Worker는 아직 신뢰된 B66 grant를 주입하지 않아 **기본 OFF/패널 숨김**. 인증된 실제 PC 등록과 운영 grant 활성화 및 E2E는 아직 미증명.
- Hark adopt 실사용 차단: #3936.

추가로 웹→PC 자동 Pull·로컬 XLSX 처리·웹 결과 반환의 구체적인 독립 수용 과제는 [#4434](https://github.com/skerishKang/ai-revenue-lab/issues/4434)에서 추적한다. 기존 #3580의 로컬→클라우드 파일 경로와 중복 구현하지 않는다.

다음 실제 개발 우선순위: **S1 Windows 실제 자동 등록 → S2 서버 검증된 제품별 PC 목록 → S3 #4434 파일 왕복·XLSX 로컬 편집 E2E**. 원격 UI/VM은 검증 가능한 후순위 R&D로 유지.
