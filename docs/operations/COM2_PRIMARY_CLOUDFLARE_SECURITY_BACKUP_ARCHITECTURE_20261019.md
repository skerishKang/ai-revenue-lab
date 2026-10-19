# PADIEM COM2 통합 실행 / Cloudflare 보안 관문·백업 전환 계획 (2026-10-19)

- 결정/추적: [#5115](https://github.com/skerishKang/ai-revenue-lab/issues/5115)
- 상태: **TARGET ARCHITECTURE**, 전환 미실행 / 제품별 LIVE CUTOVER 미검증
- 적용 범위: Chat·Claw·B66·P01 Engine·B14 Router·Connectors·Automation·DB·파일·런타임 환경변수·Secret, Cloudflare edge/security/backup.
- 우선순위: 기존 운영 보존, 무료 사용 가능한 서비스·오픈소스·기존 코드 재사용, 최소 중복 실행.

## 역할 및 데이터 정본

```text
Public users / authorized integrations
         |
Cloudflare DNS/TLS/WAF/DDoS/Bot + Tunnel (edge security, no app business logic)
         |
COM2 primary PADIEM application runtime
  |-- Chat / Claw / B66 endpoints
  |-- P01 Engine / B14 Router
  |-- Connectors / automation / jobs
  |-- operational primary DB / files
  '-- encrypted server-owned credentials / env config
         |
 encrypted incremental backups / integrity / restore
         v
Cloudflare R2 standard storage (retention subject to measured free allowance)
```

Cloudflare의 목적은 '가벼운 앱 실행'이 아니라 **접속·보안·보호·백업**. COM2는 **업무 실행의 유일한 정본**. 구형 Worker는 컷오버 시점까지 정상 유지; 초기 동기화 Cloudflare → COM2는 유지하고 정본 승격 후 COM2 → R2 백업으로 방향 전환. 이중화 실행 대신 복원 가능한 백업을 우선하며 COM2 장애 시 자동 무중단을 주장하지 않는다.

## 비용: 무료 기반 가능, 무조건 0원 보장은 아님

| 구성 | 계획상 선택 | 비용 판단 |
|---|---|---|
| COM2 compute | 기존 PC/WSL/서비스, 소프트웨어 재사용 | 신규 클라우드 실행 구독 0원; 전기·통신·장비 비용은 별도 |
| Cloudflare Tunnel | Public hostname / outbound-only tunnel | Tunnel 게시에 유료 Access 플랜 불필요 |
| Cloudflare Free WAF | Free Managed Ruleset, 기본 Bot Fight Mode, 가용 Free 규칙 | 무료 기능 범위; 고급 Enterprise 보안 분석/규칙 아님 |
| Access | 운영자 전용 적용 검토; 일반 사용자 PADIEM 로그인과 분리 | 계정 무료 제공 범위 확인 후 적용, 유료 기능 강제 금지 |
| R2 backup | Standard 스토리지, 압축·암호화·증분 | 무료 10 GB-month, Class A 월 100만, Class B 월 1,000만. 초과 종량 과금 |
| Secrets | COM2 서버 소유 암호화 저장/OS 보안 체계 | 별도 유료 vault 의존 없음. 복호화 키·재시작·복구 실제 검증 필수 |
| Models / SaaS | 기존 승인 공급자·계정 사용 | 외부 API 비용은 무료 인프라와 별도 관리 |

근거 (2026-10-19 확인):
- https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/
- https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/
- https://developers.cloudflare.com/waf/get-started/
- https://developers.cloudflare.com/waf/feature-interoperability/
- https://developers.cloudflare.com/r2/pricing/

**실제 Cloudflare 계정 상품·결제 상태, R2 저장/요청 사용량, 선택 기능 적용 가능 여부는 마이그레이션 인벤토리에서 다시 확인.** 무료 할당량을 넘으면 자동으로 계속 무료가 되는 것은 아니다.

## 이전 대상 인벤토리
- Workers/Pages: 서비스명, route, 환경변수, binding, deploy, 버전, cron
- Storage: D1 migrations/tables/export, R2 objects, KV, DO, Queues와 실제 서비스 링크
- Credentials: 각 공급자 Secret 명칭, Secrets Store/Worker bindings, OAuth refresh 소유자, rotation/expiry, COM2 DPAPI 및 Windows↔WSL 신원 경계
- Runtime: B14 모델 라우팅, P01 승인/작업, Chat/Claw/B66, SSE/장시간 요청, webhook, Mesh connector, event/notifications, admin
- Edges: DNS/WAF/Access/Tunnel, anti-origin bypass, rate limiting, health, audit, rollback
- Ops: 백업 증분·restore, 로그·메트릭, 전원 복구·부팅 후 자동 기동, 최소 권한

## 실행 단계 및 검증
1. **현황**: 최신 main·AGENTS·로컬 Governance·진행 중 PR 확인. 위 각 대상의 실제 구현과 권한/설정 위치·비용 측정. Secret 원문은 기록하지 않음.
2. **COM2 환경**: 현재 엔진/끝단 코드를 가능한 그대로 COM2에서 실행, 내부 요청 프로토콜/계정/작업 큐 테스트. 서버 기동·자동 재시작.
3. **보안 진입점**: Cloudflare Tunnel/DNS/WAF 구성, 원본 외부 접근 차단, 공개 고객 로그인/관리자 Access 경계 검증.
4. **자격증명/데이터 이전**: 제품별 세션·테넌트 격리, 원본 지속 증분 복제, COM2 encrypted secret owner, DB/파일 컷오버에 단일 쓰기 주체 및 복구 앵커 유지.
5. **선택 트래픽**: Chat/Claw/B66/P01/B14에 대해 실 로그인·모델·SSE·파일·견적·커넥터 실행 검증. 운영 Cloudflare 기반과 동일 기능 여부 확인.
6. **전환**: 기준 시점·동시쓰기 차단·남은 델타 확인→COM2 정본 승격→Cloudflare 업무 로직 정리. 서비스별 즉시 복귀 계획 보존.
7. **백업·비용**: COM2→암호화된 R2 증분/무결성/빈 복구 환경 실증, 사용량 보고, 장애 시 복구 담당 경로 확정.

이 계획은 진행 중인 #5093의 D1·R2 동기화/원격 백업 구현을 재사용하고, #4318/#4317/#3936/#4316 기존 제품별 E2E를 단일 승인 증거로 재사용한다. 계획만으로 작업 완료를 선언하지 않는다.

## 상태
`PLAN=APPROVED; ISSUE=#5115; MAIN_DOCUMENT=CREATED; DEPLOYED=NO; LIVE_CUTOVER=NO; FREE_ARCHITECTURE=FEASIBLE_WITH_USAGE_LIMITS`
