# PADIEM Connector #4139 — 중앙 상태·의사결정·이슈 통합 인덱스 (2026-10-13 KST)

> **분류:** Source/issue/document audit snapshot (문서만). **운영 활성화·보안 승인·병합·실기기 E2E의 증거가 아님.**  
> **시점:** `main` `9c41885711ff9239203b0d9010c252f6b3cf0f5f` 기준. GitHub 상태는 변경 가능하므로 실제 작업·병합 전 해당 PR의 최신 HEAD/검사를 재조회한다.  
> **권위 구분:** 기존 Identity / canonical Broker / P01 / 원본 제품 정책은 이 문서보다 우선한다. 이 파일은 **단일 상태·업무 분배 인덱스**이며 새로운 인증/정책 엔진을 만드는 문서가 아니다.

> **CURRENT GATE UPDATE — 2026-10-13, main `b6b2f1a`:** PR [#4476](https://github.com/skerishKang/ai-revenue-lab/pull/4476) latest HEAD `355a635a9c82fd86937f4284231558662094fd93` has **GitGuardian SUCCESS** in the independent Check Runs API (58 checks in the observed set; no failed/pending checks). Its earlier `74875c3` high-entropy test-fixture scan failure is historical, **not the latest blocker**. However the PR remains **Draft/stacked**; source security success alone does not approve token enrollment authority, authenticated gateway, signed PC installation, or customer E2E. [#4523](https://github.com/skerishKang/ai-revenue-lab/pull/4523) stale-device-list read cancellation is **merged** as `b6b2f1a`; [#4525](https://github.com/skerishKang/ai-revenue-lab/pull/4525) pre-connection/help/recovery UX advanced to `11d09f7`, remains **Draft** (GitGuardian SUCCESS; some tests were still running at last observation). Windows [#4490](https://github.com/skerishKang/ai-revenue-lab/pull/4490) remains stacked Draft; [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099) is the only actual Windows Alpha E2E acceptance. **Do not merge stacked PRs or deploy based only on green CI.**

> **Authority separation:** Business/customer operating policy is private and must be read from the local path in root [AGENTS.md](../../AGENTS.md); the technical evidence matrix below is public development information, not permission to make new business policy.

## 1. 최신 고객·브랜드 결정 (기존 문서 표현 보정)

- **PADIEM Claw/Chat/Engine과 B66 견적은 고객에게 서로 독립적인 서비스**다. 별도 회원 화면, 로그인, PC 관리, 구독/등급, 내비게이션, 운영 문구를 사용한다. B66 고객에게 PADIEM 통합 메뉴를 표시하거나 PADIEM 고객에게 B66 회원·PC 정보를 자동 노출하지 않는다.
- **내부 구현은 재사용 가능**: canonical Identity/Control Plane, canonical Local Agent Broker, 단일 Windows Connector/Local Runner, model routing(B14) 등. 그러나 같은 이메일, PC, 모델 등급 또는 중앙 관리자 계정만으로 **교차 브랜드 계정 연계·기기 공유·파일/작업 권한을 자동 부여하지 않는다**. 교차 브랜드 연결은 미래의 별도 검증된 계정 링크·사용자 명시 승인·제품별 권한 검토가 필요하다.
- '기기 한 대/내부 Broker 한 벌'은 **기술적 저장/설치 중복 제거 목표**이지 현재 B66↔PADIEM 고객 연결 완료를 뜻하지 않는다. 제품별 `ProductPcAccessPolicy` 기본 OFF와 별도의 P01 READ/WRITE·WorkTicket 승인 유지.
- **최신 상세 결정 원문은 CENTRAL Draft PR #4476**의 [brand separation](https://github.com/skerishKang/ai-revenue-lab/blob/62eb917fbf7e0cd4f245472532e0dbaa2c513d81/docs/architecture/PADIEM_CONNECTOR_BRAND_SEPARATION_4139_20261013.md), [platform owner](https://github.com/skerishKang/ai-revenue-lab/blob/62eb917fbf7e0cd4f245472532e0dbaa2c513d81/docs/architecture/PADIEM_CONNECTOR_PLATFORM_OWNER_AUTHORITY_4139_20261013.md)에 **Draft 소스로만 존재**한다. 이를 `main`의 배포 코드로 인용하지 않는다.

## 2. 진척·증거 매트릭스 — 소스 통과 vs 실제 출하를 분리

| 영역 | 관찰된 사실 / 증거 | 아직 승인되지 않은 부분 |
| --- | --- | --- |
| Windows tray 기본 S1 | [PR #4420](https://github.com/skerishKang/ai-revenue-lab/pull/4420) 병합. 기존 Resident 재사용·단일 인스턴스·사용자 선택 자동 시작 | 신뢰된 실제 사용자 등록/기기 ONLINE/서명된 출시 증명이 아님 |
| 공통 제품별 PC 사전 검사 | [PR #4429](https://github.com/skerishKang/ai-revenue-lab/pull/4429) 병합; `dispatch_authorized=False`가 기본 | 제품 간 기기 노출·P01 실행 권한을 만들어내지 않음 |
| 중앙 Connector 등록·서버·My Devices | [Draft PR #4476](https://github.com/skerishKang/ai-revenue-lab/pull/4476), HEAD `355a635a9c82fd86937f4284231558662094fd93`, 중앙 S1 합성·거부/소유권·문서 | **Draft/미병합/운영 OFF**. 단일 redemption owner 실제 구현·초기 기기 인증·신뢰된 gateway·ACK/회수·고객 API/UI 없음. 기존 HEAD `74875c3`의 GitGuardian failure는 역사 기록이며, **최신 `355a635` GitGuardian SUCCESS**. 실인증·브로커 권위 검증 및 정확한 최종 HEAD 리뷰는 여전히 필요 |
| Windows transport·DPAPI·설치 ACK | [Draft PR #4490](https://github.com/skerishKang/ai-revenue-lab/pull/4490), HEAD `ba326acd86977ba892dfe1a2ffe7acfe35d81d34`. Windows CI Python **291 passed / 4 skipped**, Node **5/5**; DPAPI 저장·읽기 **11 passed** | **Draft/미병합/운영 OFF**. 실제 gateway/credential handoff·ACK 송신·로그인 실기기 E2E 미배선. 성공한 테스트는 배포/연결 성공과 다름 |
| 이전 LOCAL2 S2 | [Draft PR #4463](https://github.com/skerishKang/ai-revenue-lab/pull/4463) | #4490의 근거/상위 선행 소스. 독립 병합·중복 Windows 전구간 테스트 금지; head/파일 lineage를 확인한 후 정리 |
| 기존 중앙 S1 선행 | [Draft PR #4438](https://github.com/skerishKang/ai-revenue-lab/pull/4438) | #4476이 이 브랜치에 적층되어 있어 **main 대상 단독 병합으로 우회 금지**, 계층별 검증 필요 |
| Claw LIVE SSE (별도 레인) | [PR #4493](https://github.com/skerishKang/ai-revenue-lab/pull/4493) 및 [#4512](https://github.com/skerishKang/ai-revenue-lab/pull/4512) **병합 완료**, [#3936](https://github.com/skerishKang/ai-revenue-lab/issues/3936) E2E OPEN | 모델 HOLD 오류는 source-fixed이나 실사용 SSE/복구 별도 증거 필요. Connector 승인/장치 통합과 별개 |
| 실제 Alpha Windows 검증 | [이슈 #3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099) OPEN | 서명 설치→검증된 로그인/동의→단회 등록→서버 ONLINE→P01 작업/회수·재시작·롤백 실제 PC 통합 수용 **미증명** |

**현재 판정:** `CENTRAL_PROD=OFF / LOCAL2_SOURCE_TEST=GREEN / #4476_CURRENT_GITGUARDIAN=PASS / TRUSTED_GATEWAY_WIRED=NOT_PROVEN / PC_INSTALL_E2E=NOT_PROVEN / ALPHA_GATE=#3099_OPEN`.

**2026-10-13 추가 source:** [#4523](https://github.com/skerishKang/ai-revenue-lab/pull/4523) stale directory fetch cancellation has merged to `main b6b2f1a` (DONE_SOURCE, **not device enrollment/live pairing**). [#4525](https://github.com/skerishKang/ai-revenue-lab/pull/4525) is an independent draft of pre-connection UI help and recoverability. Keep both under #4139, do not conflate them with Windows #3099. 

## 3. 중복 추적 통폐합 — 이슈를 무조건 닫지 않음

| 책임/수용 경계 | 유지할 단일 원장 | 유사·관련 항목 처리 |
| --- | --- | --- |
| 플랫폼 Connector 구현 및 보안 게이트 | [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139) **OPEN** | #4438, #4476, #4463, #4490은 **서로 다른 소유권/스택의 활성 Draft PR**이다. 보안 리뷰·lineage 없이 합치거나 닫지 않는다. 신규 중복 '전체 Connector 구현' 이슈 금지 |
| Windows 실기기/서명 설치/Pairing Alpha 수용 | [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099) **OPEN** | #3098 / #3101 / #3102는 이전에 **이관 종료**. 수용 조건만 #3099에 재사용하며 각 이슈의 독립 대형 E2E 재개 금지 |
| Claw 웹 SSE·파일·승인 실사용 | [#3936](https://github.com/skerishKang/ai-revenue-lab/issues/3936) **OPEN** | #4493은 해당 범위만. #3099 Windows 설치 검증과 합치지 않음 |
| PADIEM 내부 고객 홈·중앙 관리자 (B66 고객 합병 아님) | [#4428](https://github.com/skerishKang/ai-revenue-lab/issues/4428) **OPEN** | 기존 B66 통합 고객 홈 암시 문구는 **구식**. B66는 별도 회원/PC UI; 글로벌 운영자 권한도 제품별 역할에서 자동 상승 금지 |
| 기기 통과 후 파일 왕복/로컬 XLSX | [#4434](https://github.com/skerishKang/ai-revenue-lab/issues/4434) **OPEN** | 선행 Connector 보안 통과 전 실제 사용자 파일/브랜드 간 전송 금지. 기존 #3580 파일 권한 재사용 |
| Browser Use (선택 미래 레인) | [#3782](https://github.com/skerishKang/ai-revenue-lab/issues/3782) **OPEN** | 기존 권한 검증 및 보류 유지. Connector 출하에 신규 범용 GUI/VM 요구 추가 금지 |

**통합 방법:** 같은 일을 다른 이슈에서 다시 만드는 것이 아니라 원장에 링크/상태를 모으고, 별도 검증은 각 실행 분야에서 한 번씩만 진행한다. 과거 성공 테스트 증거를 해당 정확한 SHA와 함께 보존한다.

## 4. 차단 해소 순서 — 중앙부터, LOCAL2 대기 사유 명시

1. **CENTRAL 보안 및 계약 리뷰:** #4476 최신 `355a635` GitGuardian 성공을 기준으로 감사하되, 이전 스캔 실패의 조치 기록 보존과 테스트 fixture 출처 확인을 마무리한다. **실계정 신뢰 경로/단회 redeem 권위/제품별 경계는 별도 필수 리뷰**. Ready/병합/실기기 배포를 스캔 성공만으로 승인하지 않는다.
2. **CENTRAL / 지정된 보안 소유자:** 한 번만 소비하는 **PC-initiated, Broker-owned, enrollment-scoped redemption** 계약 설계·구현·검증. 기존 서버 측 `CanonicalConnectorEnrollmentAsyncHost.redeem()`과 PC 측 일반 `.redeem()`을 동시에 실행하거나, 일반 Broker redeem을 새 승인 경로로 가장하지 않는다. 현재 OWNER/session/tenant/명시적 consent·challenge binding을 서버 권위로 검사하고 철회 경쟁·단회/재생방지·revoke/HOLD까지 시험한다.
3. **CENTRAL / LOCAL1 별도 명시 배정 시에만:** 기존 kagent outbound pinned HTTPS/443 transport를 **실제로 인증된 Broker gateway + 초기 device bootstrap source authentication + ACK 검증**에 배선한다. TLS만으로 기기 소유 증명 불가. Windows 자격증명이 제품 HTTP·브라우저·로그에 노출되어서는 안 됨. 세션 철회 시 후속 실행 금지.
4. **LOCAL2 #4490:** 위 서버 계약이 GitHub 정확한 head로 확정되기 전까지 현재 DPAPI/수신/증명 코드를 보존하고 **더 이상 일반 redeem/임시 webhook/새 Broker를 만들지 않는다**. 중앙 계약 확정 후 소형 어댑터 수정, Windows **국소** 설치/ACK 확인 및 해당 필수 CI만 재검증. 실제 로컬 작업은 이슈 댓글만으로 자동 시작하지 않는다.
5. **CENTRAL 제품 UI:** PADIEM과 B66에서 독립된 인증·기기 목록/동의·철회 UI를 설계하되 기본 OFF 유지. B66 세션이 Claw 기기 목록을 읽거나, 같은 이메일이라는 이유로 두 브랜드를 연결하면 안 된다. `device.list` 허가 != P01 READ/WRITE.
6. **#3099 단일 실기기 Alpha:** 서명 설치/업데이트·복구/회수·오프라인/재연결·동시 계정/기기 부정 테스트·작업 결과를 실제 Windows에서 통합 검증한 뒤 별도 제품 승인/배포 게이트. #4434 XLSX 작업은 이 기초 권한 경계를 통과한 뒤 진행.

## 5. 실행·보고 규칙

- 중앙의 새로운 기능이 LOCAL2 소비자 계약을 바꿀 때만 LOCAL2에 구현 지시하며, **진짜 실행 여부**는 로컬 프로세스·브랜치·PR 헤드 변화로 확인한다. 이슈 댓글 작성만으로 "로컬이 시작했다" 주장 금지.
- Draft #4476/#4490/#4463/#4438 모두 관련 보안·CI·신뢰·승인 필수 조건 충족 전 **Ready/merge/live = NO**. 기존 다른 로컬의 worktree/파일을 중앙에서 덮어쓰지 않는다.
- 문서 수정은 T0: 변경 범위·링크·보안 표현 검증 + 실제 GitHub 필수 CI만 확인. #3099를 위한 대형 테스트를 문서 리뷰 때마다 반복하지 않는다.
- 보고는 `HEAD / CODE / FOCUSED_CI / SECURITY_GATE / OWNER / BLOCKER / NEXT_DEPENDENCY / MERGED / PROD / REAL_PC_E2E`만. "설치됨", "온라인", "운영"이라는 말은 해당 증거가 있는 경우에만 쓴다.

## 6. 설계 원본의 현재 위치

- [기존 main 플랫폼 로드맵](../architecture/PADIEM_CONNECTOR_PLATFORM_DECISION_20261012.md) — 이 문서의 **브랜드 분리 정정**을 우선 적용.
- [CENTRAL Draft 단일 기기 등록/권한](https://github.com/skerishKang/ai-revenue-lab/blob/62eb917fbf7e0cd4f245472532e0dbaa2c513d81/docs/architecture/PADIEM_CONNECTOR_PLATFORM_OWNER_AUTHORITY_4139_20261013.md).
- [CENTRAL Draft 고객 브랜드 분리](https://github.com/skerishKang/ai-revenue-lab/blob/62eb917fbf7e0cd4f245472532e0dbaa2c513d81/docs/architecture/PADIEM_CONNECTOR_BRAND_SEPARATION_4139_20261013.md).
- [CENTRAL Draft Windows 인증정보·전송 계약](https://github.com/skerishKang/ai-revenue-lab/blob/62eb917fbf7e0cd4f245472532e0dbaa2c513d81/docs/architecture/PADIEM_CONNECTOR_4139_CREDENTIAL_AUTHORITY_TRANSPORT_DECISION_20261012.md).
- [CENTRAL Draft 장치 조회 S1](https://github.com/skerishKang/ai-revenue-lab/blob/62eb917fbf7e0cd4f245472532e0dbaa2c513d81/docs/architecture/PADIEM_CONNECTOR_ACCOUNT_DEVICES_S1_4139_20261013.md).
- [테스트 최소충분성 규정](TEST_SCOPE_AND_DELIVERY_POLICY.md), [실제 Windows 수용 원장](https://github.com/skerishKang/ai-revenue-lab/issues/3099).

**업데이트 방법:** 상태는 새 댓글·후속 수정으로 관리하고, 이미 병합된 진실과 미병합 설계를 혼합하지 않는다. 최신 PR HEAD·CI와 상충하는 이 문서의 옛 숫자는 최신 근거로 정정한다.
