# B54 Padiem Claw — 경량 Connect + Full Desktop 이중 사용자 경험 제품계획 (#4139)

> **상태:** 제품 방향/구현계획 문서 · 2026-10-10 · **구현 완료 또는 Production 출시를 의미하지 않음.**
>
> **상위 전략:** [#3074](https://github.com/skerishKang/ai-revenue-lab/issues/3074) · **Cross-surface 대형 실행 EPIC:** [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139) · **기술 계약:** [공통 로컬 실행 아키텍처](../architecture/B54_CLAW_CONNECT_DESKTOP_SHARED_LOCAL_RUNTIME_ARCHITECTURE_20261010.md)

## 1. 결정: 두 앱 경험, 하나의 Claw

| 구분 | Padiem Claw 웹 | **Padiem Claw Connect** | **Padiem Claw Desktop** |
| --- | --- | --- | --- |
| 핵심 역할 | 대화·작업·기기·승인·결과 화면 | 웹과 사용자 PC를 연결하는 **최소 트레이 프로그램** | 사용자의 PC 안에서 직접 일하는 **Full Workbench** |
| 사용자 | 설치 없이 클라우드 중심 작업 | 웹 사용 + 내 PC 파일/실행 필요 | 프로젝트/파일/브라우저 등 데스크톱 중심 고급 사용자 |
| UI | 브라우저 | 트레이·연결 상태·최소 설정, 터미널 불필요 | ZCode 개념을 선별 적용한 전체 Desktop UI |
| 로컬 실행 | 연결된 실행기 있을 때만 | **공통 Windows Resident/Local Runner** | **같은 Resident/Local Runner** |
| 계정·P01·기기·작업 | Padiem 기존 권위 | **같은 권위 재사용** | **같은 권위 재사용** |
| 필수 설치 | 없음 | Windows용 경량 연결기 | 전체 데스크톱 앱 |
| 권한 | 서버/커넥터 범위 | 사용자가 선택한 로컬 폴더·기능·개별 작업 승인 | 동일한 로컬 권한·승인·감사 체계 |
| 현재 확인 상태 | 기존 웹 UI/Golden Path 작업 진행 중 | **트레이 제품은 신규 구현·검증 필요** | Electron 소스 존재, ZCode `ADAPT_PARTIAL` #3583 미완료 |

**정책:** 웹 사용자를 데스크톱 워크벤치로 강제 이동시키지 않는다. Full Desktop 사용자를 브라우저 화면으로 강제 이동시키지 않는다. 다만 사용자 계정과 작업/기기/승인 권위는 **한 벌**이다.

## 2. 일반 사용자 여정: 다운로드 → 로그인/연결 → 트레이 온라인

1. 사용자가 웹 Claw에서 평범하게 업무를 요청한다. 클라우드에서 가능한 일은 **설치 없이 처리**한다.
2. 내 PC가 필요한 작업에만 **“내 컴퓨터 연결”**을 보여준다. 지원 OS와 실제 접근 권한을 간단히 설명한다.
3. **설치되지 않은 경우:** 공식 출처의 서명된 Connect 설치기를 내려받는다. 설치 후 처음 실행한다. 명령 프롬프트·PowerShell·MCP 설정·localhost 주소를 보여주지 않는다.
4. **설치된 경우:** 웹의 연결 버튼이 서버에서 받은 유효한 `padiem://` handoff를 OS 등록 앱에 넘긴다. 사용자의 명시적 행위를 전제로 한다.
5. 사용자는 **같은 Padiem 계정/워크스페이스**, 짧게 유효한 1회용 페어링으로 현재 PC를 등록한다. 연결 상태는 서버 권위가 검증할 때만 “온라인”.
6. 첫 사용 시 **허용할 폴더와 작업 기능**을 선택한다. 초기값 전체 PC/관리자 권한은 거부. 정책에 따라 읽기, 쓰기, 명령 실행이 별도로 드러난다.
7. 사용자 화면에는 **“연결됨 / 승인 필요 / 연결 끊김 / 업데이트 필요”** 같은 자연스러운 상태를 보여준다.
8. 이후 사용자는 웹에서 작업을 요청하고 필요한 때 승인한다. Resident가 실행한 결과가 **기존 같은 Claw 대화**로 돌아온다.
9. 트레이 아이콘으로 **일시중지·권한 보기·연결 해제·종료**할 수 있다. 사용자가 중단한 경우 서버·실행기 모두 더 이상 새 작업을 실행하지 않아야 한다.
10. 자동 시작은 사용자가 켜고 끌 수 있어야 한다. 프로그램을 닫거나 PC가 꺼지면 정직하게 OFFLINE으로 표시한다.

**목표 사용감:** 메신저처럼 익숙한 트레이 프로그램. 평소 방해가 없는 작은 아이콘을 제공하되, 실행 중인 원격 작업/승인/연결 상태를 **사용자에게 숨기지 않는다**.

## 3. 고급 사용자 여정: Full Desktop

- Full Desktop은 직접 실행하는 별도의 Padiem Claw 워크벤치: 대화, 프로젝트, 파일 탐색, 작업 진행, 승인, 연결 기기, 아티팩트를 하나의 앱에서 본다.
- **ZCode 전체를 그대로 이식하지 않는다.** [#3436](https://github.com/skerishKang/ai-revenue-lab/issues/3436)의 `ADAPT_PARTIAL` 결정과 [#3583](https://github.com/skerishKang/ai-revenue-lab/issues/3583)을 유지한다.
- 파일/프로세스/브라우저 기능은 Padiem 자체 Local Runner와 기존 P01/Broker 권위 안에서 제공하며, Z.ai 로그인/모델/결제/텔레메트리/업데이트 권위는 상속하지 않는다.
- **기능 표시가 곧 활성화는 아님:** native OS GUI Computer Use, 범용 외부 브라우저 접근, 외부 메신저 발신, 클라우드 운영 변경은 별도 구현·권한·승인·출시 게이트 필요.
- 사용자가 Full Desktop만 설치해도 작업이 가능해야 하며 **Claw Connect를 다시 설치하라고 요구하지 않는다**.

## 4. 두 제품의 공존·전환 원칙

| 상황 | 기대 동작 | 검증해야 할 사항 |
| --- | --- | --- |
| Connect만 설치 | 트레이만 상주, 웹에서 로컬 작업 | 연결·승인·파일/실행 E2E |
| Full Desktop만 설치 | 앱을 켜서 Claw 사용, 동일 Resident 이용 | 엔진 중복 없이 Full UI 기능 제공 |
| 둘 다 설치 | **같은 호스트에서 동시에 Runner 두 개가 명령 실행하지 않음** | single owner / 공용 Resident / handoff 정책 결정 |
| Connect → Desktop 전환 | 작업·승인·대화/아티팩트 권위 유지 | 계정/기기/작업 재등록이나 재실행 방지 |
| Desktop → Connect 전환 | 웹 UX로 복귀, 이미 승인된 권한만 유지 | 자동 권한 확대/손실 없음 |
| 프로그램 업데이트/롤백 | 버전 호환 검사, 실행 이력 재생 금지 | old/new Resident 경합·앱 제거·복구 |
| 연결 해제/권한 취소 | 앞으로의 실행 즉시 차단, 상태 업데이트 | Broker lease·취소·재시도 검증 |

**미결 제품 세부 결정(S0):** (A) 단일 패키지의 “트레이 모드 / 전체 UI 모드”, 또는 (B) 별도 설치기 2개 + 공통 단일 Resident. 어느 쪽이든 **한 기기에서 단일 실행 권한**을 유지하고, 실제 패키지 용량·설치 복잡도·업데이트 안정성을 비교해 선택한다. *“경량”은 사용자 경험을 뜻하며 다운로드 바이트 수가 작다고 아직 검증된 것은 아니다.*

## 5. 기존 구현을 어디까지 재사용하는가

- [#3074](https://github.com/skerishKang/ai-revenue-lab/issues/3074): Web-first + Desktop 로컬 실행 + Mobile/Cloud 옵션의 기존 전략. 본 설계는 Web/Connect/Full Desktop UX를 분명히 한다.
- [#3014](https://github.com/skerishKang/ai-revenue-lab/issues/3014), [#1633](https://github.com/skerishKang/ai-revenue-lab/issues/1633): 상주 Resident, 로컬 파일/명령 실행, 인증·권한 계약. **새 실행기 제작 금지**.
- [#3098](https://github.com/skerishKang/ai-revenue-lab/issues/3098), [#3650](https://github.com/skerishKang/ai-revenue-lab/issues/3650): 비운영 Windows exact-main 27/27 실험 기록은 **근거**지만 실제 사용자 제품 E2E는 미완료.
- [#3084](https://github.com/skerishKang/ai-revenue-lab/issues/3084), [#3094](https://github.com/skerishKang/ai-revenue-lab/issues/3094): 웹의 “이 컴퓨터 연결”과 딥링크 초기 경로.
- [#1651](https://github.com/skerishKang/ai-revenue-lab/issues/1651): Connections & Devices의 연결 기기 관리·폐기/권한 UI 계약.
- [#3583](https://github.com/skerishKang/ai-revenue-lab/issues/3583), [#3436](https://github.com/skerishKang/ai-revenue-lab/issues/3436): 전체 Desktop UX와 실행 어댑터의 선별 재사용 결정.
- [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099), [#3101](https://github.com/skerishKang/ai-revenue-lab/issues/3101), [#3102](https://github.com/skerishKang/ai-revenue-lab/issues/3102): 일반 사용자에게 설치 파일을 배포하기 위한 서명/자동 업데이트/실서비스 페어링/롤백 과제.
- [#3523](https://github.com/skerishKang/ai-revenue-lab/issues/3523): **현재 우선순위**인 운영 Golden Path. 그 진행을 밀어내는 새 대규모 병렬 개발은 기본 금지.

## 6. 단계별 제품 완성 조건

| 단계 | 확인 가능한 납품물 | 완료 판정 |
| --- | --- | --- |
| **S0** 설계 | 제품/실행 아키텍처, 패키지 모드·Single Resident 소유권 결정 | 기존 권위 충돌·중복 개발 없음 |
| **S1** Connect 트레이 PoC | OS 트레이 메뉴, 시작/중지/상태/설정, headless Runner | 사용자 커서/터미널 간섭 없이 안전한 로컬 lifecycle |
| **S2** 웹-기기 연결 | 다운로드/설치, 동일 계정/워크스페이스 페어링, 폴더/기능 승인 | 서버 권위 ONLINE/REVOKED/EXPIRED truth |
| **S3** 실사용 기능 | 웹+Connect 및 Full Desktop에서 같은 테스트 작업/대화 복귀 | 파일·명령 E2E, 동일 기기 두 Runner/이중 실행 0 |
| **S4** 배포·운영 | 서명된 설치기, 복구/업데이트/제거·로그/지원/접근성 | 여러 실제 Windows 기기에서 설치·복구·회수 검증 |

**선행 우선순위:** S0은 문서/기획으로 진행 가능. S1 이상은 #3523 Golden Path 진행 상태와 실행 리소스 충돌을 확인한 뒤 착수한다. **#4139의 OPEN은 기존 #3583·#3098의 완료 선언이나 Production 허가가 아니다.**

## 7. 사용자에게 명시할 한계

- 브라우저만으로 사용자의 PC 전체 파일·프로세스에 임의 접근할 수 없다. 적절한 **로컬 실행기·기기 인증/권한**이 필요하다.
- Padiem Connect는 Chrome Remote Desktop, Desktop Commander, Tabbit, MCP 도구와 **동일 제품이 아니다**. 외부 원격 도구 연동은 API/약관·보안·라이선스 심사 뒤 확장 가능성만 검토한다.
- 현재 기본 범위는 **승인된 로컬 파일/명령 작업**이다. **PC 화면의 마우스·키보드 조작(Computer Use)** 또는 마이크/화면 상시 감시는 별도 명시적 동의 및 별도 제품 요구/보안 검토가 필요하다.
- “어떤 컴퓨터든 설치하면 바로 된다”는 마케팅 표현은 금지. Windows 지원 범위, 연결 상태, 기기 등록·승인, 사용자 선택 권한, 네트워크/보안 소프트웨어 제약이 있다.

## 8. 성공 기준과 초기 파일럿

**첫 파일럿 시나리오:** Windows 11 테스트 PC에서 Connect를 설치하고, 웹 Claw의 “내 컴퓨터 연결”로 기기를 등록한다. 사용자가 고른 테스트 폴더에 텍스트 파일을 작성하도록 승인한 뒤 결과를 같은 대화에 반환하고, 트레이에서 연결 해제했을 때 추가 실행이 거부되는지 확인한다.

**확대 평가 지표:** 무터미널 설치 완료율, 최초 연결까지 걸린 시간, 미인가 실행 0, 회수 지연, 복구 성공률, 중복 명령 실행 0, 사용자 간섭 발생 건수, 지원 요청률, Full Desktop으로의 전환 후 작업 연속성.

**현재 판정:** `PRODUCT_DIRECTION=DEFINED`, `CONNECT_TRAY_IMPLEMENTED=NO_VERIFIED`, `SELECTED_PRODUCT_WINDOWS_E2E=PENDING`, `PUBLIC_RELEASE=NO`.
