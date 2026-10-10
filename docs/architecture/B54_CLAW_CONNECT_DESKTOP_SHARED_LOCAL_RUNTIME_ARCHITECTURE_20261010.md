# B54 Padiem Claw — Claw Connect / Full Desktop 공통 로컬 실행 아키텍처 (#4139)

> **문서 상태:** Architecture proposal / S0 기준안 · 2026-10-10. **미구현 기능과 운영 배포 완료를 주장하지 않는다.**
>
> [#4139 대형 개발 이슈](https://github.com/skerishKang/ai-revenue-lab/issues/4139) · [제품·UX 계획](../product/B54_CLAW_CONNECT_DESKTOP_DUAL_SURFACE_PRODUCT_PLAN_20261010.md) · [#3074 상위 전략](https://github.com/skerishKang/ai-revenue-lab/issues/3074)

## 1. 설계 원칙과 정확한 기술 경계

**“사용자 인터페이스는 두 가지, 실행 권위는 한 가지.”**

- **Claw Connect**는 웹 기반 Claw를 선호하는 사용자의 Windows 트레이/백그라운드 호스트. 기능은 연결 상태·시작/중지·재연결·권한/진단·기기 연결/해제로 제한한다. 별도 대화/Agent/모델 엔진을 만들지 않는다.
- **Claw Desktop**은 로컬 워크벤치(프로젝트/파일/대화/실행 진행). [#3583](https://github.com/skerishKang/ai-revenue-lab/issues/3583)의 **ZCode `ADAPT_PARTIAL`** 구조를 따른다. Desktop UI 또한 Broker/P01/Resident의 독립 대체제가 아니다.
- **단일 Windows Resident/Local Runner**는 두 표면이 공유할 OS 레벨 실행 엔드포인트다. 계정·워크스페이스·기기·작업의 유효 권한을 가진 경우에만 작업한다.
- 모든 작업은 **Padiem Identity/Control Plane → P01 human approval → Canonical Execution Broker → bounded Resident/Runner → bounded receipt → 원래 Claw 대화** 경계를 거친다. 승인 사실을 UI boolean, ZCode 로그인, 트레이 상태로 위조할 수 없다.
- 일반 웹은 브라우저 보안 경계 바깥 로컬 파일·프로세스에 마음대로 접근하지 못한다. **사용자가 설치·기기 연결·권한 승인한 로컬 호스트가 필수**다. “모든 PC에 무설치 원격 접속”이라고 설명하면 안 된다.

## 2. 제안하는 실행 토폴로지

```text
                PADIEM ACCOUNT / IDENTITY / WORKSPACE (canonical)
                                     |
                         Web Claw / Mobile(optional)
                                     |
                      User intent / task / approval UX
                                     |
                PADIEM ENGINE / CORE / B14 model authority
                                     |
                      P01 approval / grant evidence
                                     |
           Canonical Control Plane + Execution Broker (one)
            |                    |                   |
      signed task/grant     authoritative       bounded result/
      & device routing      device presence      same conversation
            |                    ^                   ^
            +----------- authenticated TLS, OUTBOUND-ONLY -------------+
                                 |
               Windows: single supervised PADIEM Resident
                     canonical device + credential owner
                                 |
               bounded Local Runner / Windows Executor
                (granted roots / capability / cancellation)
                    /                         \
    Connect tray (minimal UI)           Full Desktop UI/workbench
    web user controls locally           direct app user controls
    no second executor                  no second executor
```

이 도식은 **제품 목표**다. Desktop/Connect 공존과 공통 Resident 바인딩을 운영 검증했다는 뜻은 아니다.

## 3. 재사용 권위와 실제 소스

| 단일 권위/기반 | 현재 소스·이슈 | 지금 증거와 남은 범위 |
| --- | --- | --- |
| Claw 제품 전략 | [#3074](https://github.com/skerishKang/ai-revenue-lab/issues/3074) | Web-first, Desktop local, Mobile/Cloud optional 구조는 이미 존재 |
| Local Agent capability / selected roots | [#1633](https://github.com/skerishKang/ai-revenue-lab/issues/1633) 및 #1634–#1636 | 파일·프로세스 경계, 최소 권한·승인 계약. **확대/복제 금지** |
| Windows Resident | [#3014](https://github.com/skerishKang/ai-revenue-lab/issues/3014) | start/stop, reconnect, heartbeat/poll, credential store, command lifecycle 기반 |
| Web Connect CTA/deeplink | `apps/padiem-chat/static/claw-local-connect.js`, [#3084](https://github.com/skerishKang/ai-revenue-lab/issues/3084), [#3094](https://github.com/skerishKang/ai-revenue-lab/issues/3094) | `padiem://` handoff 및 nonprod connect 구성. 운영 사용 가능하다고 단정 금지 |
| Broker/Pairing | `packages/padiem-control-plane/padiem_control_plane/local_agent_broker_*.py` | authenticated pairing / one-shot / session device truth 재사용 |
| Desktop Shell | `apps/padiem-desktop-shell/`, [#3583](https://github.com/skerishKang/ai-revenue-lab/issues/3583) | Electron + 분리형 headless runner, ZCode 선별 적용 방향; **트레이 모드가 완성된 소스라는 증거 없음** |
| Windows Web→Desktop 증명 | [#3098](https://github.com/skerishKang/ai-revenue-lab/issues/3098), [#3650](https://github.com/skerishKang/ai-revenue-lab/issues/3650) | **2026-10-10 기록상 nonprod exact-main 27/27 PASS**, 그러나 selected-product trusted end-user Production pairing/E2E는 아직 미검증 |
| Connections & Devices | [#1651](https://github.com/skerishKang/ai-revenue-lab/issues/1651) | 기기·권한·상태·revocation 안전 투영, 새 권한 저장소 금지 |
| 브라우저 실행 | [#3782](https://github.com/skerishKang/ai-revenue-lab/issues/3782) | Electron/CDP bounded actions primary; 실사용 P01/Broker 제품 활성화 **OFF** |
| 패키징·배포 | [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099)/[#3101](https://github.com/skerishKang/ai-revenue-lab/issues/3101)/[#3102](https://github.com/skerishKang/ai-revenue-lab/issues/3102) | 서명/업데이트/회수/운영 pairing/릴리스는 **별도 Alpha 게이트** |

**기존 선택을 덮어쓰지 않는다:** #2996과 `docs/operations/TECHNOLOGY_ADOPTION_POLICY.md`는 기술 재사용의 단일 정책, #3436은 `ZCode=ADAPT_PARTIAL` 결론. 새로운 Electron 전체 포크·별도 Broker/P01/모델 라우터·새 승인 저장소를 만들지 않는다.

## 4. 설치/프로비저닝/연결 설계

```text
(1) 웹 사용자가 "내 컴퓨터 연결" 명시 클릭
(2) 설치됨? → 유효 padiem:// handoff
    설치 안 됨? → 서명된 공식 Windows Connect 설치기 다운로드 → 앱 실행
(3) PADIEM canonical user/workspace 로그인 사실을 기준으로 server-minted
    single-use, short-lived pairing challenge
(4) local app이 bound proof를 승인된 TLS Broker에 outbound 전송
(5) Broker가 device/account/workspace/capabilities를 확정
(6) Resident가 authenticated outbound heartbeat/poll 시작
(7) 서버-backed ONLINE을 웹/트레이/Full Desktop에 동일 투영
(8) workspace/root/capability 선택 및 작업별 P01 승인 뒤 실행
(9) sanitized receipt/artifact → 원래 run & conversation
```

신규 사용자가 **터미널 명령·MCP 구성·수동 IP/포트 지정** 없이 연결할 수 있게 하되, 최초 로그인/기기 권한 승인은 생략하지 않는다. 설치기 링크 전달과 페어링은 별도의 보안 이벤트다. 웹이 요청을 보냈다고 임의 PC 프로세스를 직접 생성할 수는 없다.

### 로컬 트레이 동작 계약 (S1)

- 온라인 / 오프라인 / 승인 필요 / 일시중지 / 업데이트 필요 / 로그아웃 표시.
- 사용자에게 보이는 “연결 끊기”, “앱 종료”, “실행 일시중지” 각각의 효과 정의: **승인 취소·세션 폐기·진행 중 작업 취소와의 상호작용은 별도 테스트**. UI 문자열만 바뀌어서는 안 된다.
- 트레이 프로그램은 **실행기·권한 엔진 자체가 아니라 선택적 상태/설정 UI**. 브라우저/Full Desktop의 연결 상태도 같은 server truth 사용.
- Windows 자동 시작은 opt-in 기본(정책 결정 필요), 관리자가 아닌 표준 사용자 세션. 트레이에서 손쉽게 해제/진단 가능.
- 비밀번호·토큰·기기 secret은 Windows OS credential store 등 기존 trusted path에만 보존하고 UI/로그/URL/클립보드에 노출하지 않는다.
- 화면, 마이크, 키보드 기록을 백그라운드에서 기본 수집하지 않는다. 이 제품 기본 버전은 **파일/실행 작업용 로컬 브리지**다.

## 5. 단일 실행기 소유권: 가장 중요한 아키텍처 결정

**의도된 invariants**:

```text
LOCAL_RUNNER_AUTHORITY_COUNT_PER_DEVICE=1
BROKER_COMMAND_CONSUMPTION=ONE_SHOT
CANONICAL_DEVICE_ID_PER_PAIRING=1
P01_APPROVAL_AUTHORITY=1
CONNECT_AND_DESKTOP_NO_DUPLICATE_JOB=TRUE
PAIRING_ORIGIN_WORKSPACE_RUN_AND_COMMAND_EXACT_MATCH=TRUE
OUTBOUND_ONLY_NO_PC_PUBLIC_INBOUND=TRUE
```

**S0에서 선택할 배포 전략** (둘 다 구현 완료 아님):

| 후보 | 구성 | 장점 | 리스크 |
| --- | --- | --- | --- |
| A. 단일 설치기, 2가지 UX 모드 | Resident/Runner 1 + Tray mode / Full Window mode, UI on-demand | 업데이트·단일 인스턴스가 비교적 단순 | 설치 용량/메모리가 Electron 수준이면 “경량” 체감 약할 수 있음 |
| B. Connect 경량 설치기 + Full Desktop 별도 앱 | **공통 Resident 1** + Tray shell / Electron workbench | 다운로드·런타임 비용 최적화 가능 | 2개 설치기 간 버전·서비스 소유권·제거 시 연결 끊김 복잡 |

**권장 의사결정 과정:** A로 기존 Electron + headless Resident를 먼저 소규모 PoC하고, 사용자가 체감하는 설치 크기·시작 시간·메모리·업데이트 위험을 측정. 기준을 충족하지 않으면 B를 전제로 별도 경량 UI 기술을 비교한다. **두 엔진/두 명령 큐로 분리하는 C안은 금지**.

- 서비스/앱 실행 중복은 **기기+사용자 계정과 세션 권위에 의해 거부**. 단순 OS mutex만 믿지 않고 Broker one-shot·durable recovery가 유지되어야 함.
- 두 앱 중 하나 제거 시 남은 앱이 요구하는 공통 Resident를 지우지 않도록 install ownership/refcount 또는 명확한 복구 UX 필요.
- 전체 데스크톱과 트레이가 서로를 강제 기동하거나 화면을 빼앗는 경험이 없어야 한다.

## 6. End-to-end 작업의 인증·권한·결과 일관성

1. LLM이 생성한 파일명/명령/URL/도구 파라미터는 **untrusted data**. 직접 실행 허가 아님.
2. 작업은 canonical owner + workspace + device + run + command id/request fingerprint + 허용 루트/capability + 유효 TTL에 결속.
3. **P01의 실제 사용자 승인** 없는 위험 명령은 Broker와 Resident가 모두 fail-closed. 동일 승인으로 권한 확대/다른 프로그램 실행 금지.
4. Resident는 단일 승인된 명령을 one-shot consume하고 실행 중 취소/timeout/프로세스 트리 정리. 실패 후 자동 중복 실행 금지.
5. 로컬 실행 결과는 raw 토큰·쿠키·민감한 stdout 전체가 아니라 **bounded, sanitized receipt / artifact ref**로 기존 Claw 대화에 반환.
6. 기기와 계정/워크스페이스가 바뀌면 다른 기기의 승인/로컬 결과가 투영되지 않도록 격리.
7. 웹/Connect/Desktop에 동일한 상태가 보여야 하지만 **클라이언트가 ONLINE·APPROVED를 스스로 주장할 수 없음**.

## 7. 실패 모드 및 사전 방어

| 위협 / 장애 | 방어와 확인 조건 |
| --- | --- |
| 잘못된 계정의 PC 연결 / 기기 가로채기 | 짧은 1회성 pairing, canonical owner/workspace/device 매칭, revoke·re-pair, challenge replay 0 |
| 악의적 문서·프롬프트로 명령 실행 | 명령은 승인된 typed bounded tool 계약으로만 전달; 사용자별 folder/capability allowlist; prompt injection은 권한이 아님 |
| 심볼릭 링크·Windows junction 통한 허용 폴더 탈출 | 기존 #1633 경로 정규화·realpath/escape 검증 사용 |
| 이미 취소·만료된 작업 실행 | P01 lease/admission·Broker one-shot/TTL·Resident 검증, offline/restart replay 0 |
| Connect와 Desktop의 동시 실행 | 단일 supervised runner + server durable command consume; 이중 프로세스/중복 작업 0 |
| 웹페이지가 OS 권한을 직접 발급 | 금지. 로그인 상태/클릭/UI boolean이 승인·로컬 실행 권위가 될 수 없음 |
| 통신 끊김/컴퓨터 종료/업데이트 | bounded backoff, offline truth, 취소·복구, 호환되지 않는 버전은 fail-closed |
| 설치 파일 변조·업데이트 오류 | SHA/서명 검증, 공식 배포 채널, 롤백 시 결과 재실행 금지 |
| 원격 접근 악용/개인정보 수집 | 선택한 폴더만, 공개 PC 포트 0, 원격 화면/마이크 기본 OFF, 비밀정보 로그 0 |

## 8. Desktop Commander·Tabbit·Chrome Remote Desktop 참고와 분리

- **Desktop Commander 방식:** 원격에서 허용된 PC의 파일/프로세스/터미널 능력을 쓰는 연결 도구의 **사례**. 해당 제품의 API·사용 약관·라이선스·운영 계정을 Padiem이 그대로 사용할 수 있다는 근거는 아직 없다.
- **Tabbit + Chrome Remote Desktop:** 2026-10-10 별도 실험에서 원격 Windows 화면을 보고 시작 메뉴를 열고 VS Code를 실행하는 **GUI 입력 실증**이 있었다. 이는 Claw의 현재 Remote GUI 제품 기능이 아니다.
- **외부 실행 어댑터:** P01/Broker/승인·워크스페이스·감사 위에 붙는 optional backend여야 하며, 자체 account/pairing/approval authority를 갖지 않는다. 계약 검증 전 실서비스 연결 금지.
- **Native OS GUI Computer Use:** 이 이슈 기본 MVP 범위 **OUT**. 새 위협 모델, 화면·키보드·오디오 데이터 처리 동의, 실제 Windows proof 및 독립 승인 필요.
- **하드웨어·OS:** 우선 Windows; macOS/Linux는 동일 개념으로 이식 가능하지만 해당 OS용 호스트/패키징·권한과 실제 E2E가 따로 필요하다.

## 9. PoC와 릴리스 게이트: 과도한 중복 테스트 방지

| 단계 | 최소 테스트 | PASS 선언 범위 |
| --- | --- | --- |
| S0 Docs | 현재 source/issue 계약 추적 + 링크·중복 권위 확인 | 두 UI의 경계와 단일 Resident 의사결정 |
| S1 Tray lifecycle | isolated Windows tray start/stop/state + 1-instance negative case | 트레이가 표시되고 기존 Runner와 공존 가능 |
| S2 Web Pairing | 1회성 pairing 승인/거부/만료·workspace/기기 mismatch + 서버 온라인 truth | 무터미널·명시적 사용자 연결 |
| S3 Golden Path | 사용자 승인된 테스트 파일 1개 수정/저장→같은 대화 결과, revoke/중복/재시작 0 side-effect | Connect/Full Desktop 각각에서 동일 계약 |
| S4 Alpha | 서명된 설치/업데이트/롤백/제거, 깨끗한 Windows 복수 기기, 사용자 혼동 없는 UX | controlled alpha readiness, Production은 별도 승인 |

작은 UI 수정마다 전체 테스트 1,000개를 반복하지 않는다. 변경한 계약에 직접 걸리는 focused 테스트 → 해당 exact-head CI → **정말 필요한** 실제 Windows/설치 E2E만 한다. E2E 독립 증명이 필요할 때에는 구현자 자기 테스트와 별도로 기록한다.

## 10. 현재 판정·의사결정 대기

```text
CURRENT_DATE=2026-10-10
DOCUMENT_PHASE=S0_PROPOSAL
CONNECT_TRAY_PRODUCT=NOT_YET_VERIFIED
FULL_DESKTOP_SELECTED_ZCODE_ADAPTATION=#3583_OPEN
REAL_NONPROD_WINDOWS_WEB_DESKTOP_E2E=#3650_27/27_PASS
PRODUCT_USER_WINDOWS_E2E=#3098_OPEN
TRUSTED_PRODUCTION_PAIRING=NOT_CLAIMED
CANONICAL_BROKER_AND_P01=MUST_REUSE
ONE_DEVICE_ONE_RESIDENT=TARGET_CONTRACT_NOT_YET_PROVEN_WITH_BOTH_UIS
OS_COMPUTER_USE=OUT_OF_SCOPE
PRIMARY_PRODUCT_GOLDEN_PATH=#3523
PRODUCTION_MUTATION=0
```

**S0 미결 결정:** (A) 통합 설치기/모드 vs (B) 경량/Full 별도 설치기·하나의 Resident, 사용자 로그인/권한 UX, Windows 지원 범위, 설치 크기/성능 목표, 배포·업데이트·제거 책임. **본 문서의 기술 방향은 기존 #3074·#3583·#3098·#3014의 권위에 종속된다.**

**우선순위:** S0 설계 기록은 가능. #3523 Golden Path P0를 완료하기 전 S1~S4의 무관한 병렬 개발은 기본 보류. 이 이슈/문서는 개발 허가나 운영 활성화 권한이 아니다.
