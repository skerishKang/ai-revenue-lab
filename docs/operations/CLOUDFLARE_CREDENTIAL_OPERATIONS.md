# Cloudflare Credential Operations

**정본:** 로컬 운영 조회와 GitHub Actions 인증 문제의 공통 진입점. 최종 정리일: **2026-10-21 KST**.

이 문서는 인증 경로 선택·진단 절차입니다. 새 토큰 발급, 권한 확대, 운영 설정 변경, 다른 계정 사용을 승인하지 않습니다. 실제 조회·변경은 해당 작업의 기존 승인 범위를 따릅니다. 비공개 값과 현재 계정별 설정은 승인된 비공개 저장소에 둡니다.

## 0. Padiem AI Cloudflare 계정 구분 — Owner 결정 2026-10-21

현재 Padiem AI 작업의 운영 계정은 **`Charliekant`(찰리칸트)**입니다. 제품 이름 `Padiem`과 Cloudflare 계정 이름 `Padiem`을 같은 대상으로 해석하지 않습니다.

| Cloudflare 계정 표시 이름 | 역할 | 이번 Padiem AI 작업 |
| --- | --- | --- |
| **`Charliekant`** | 현재 Padiem AI의 운영 계정 | Chat·Engine Worker의 기존 배포·진단·로그 조회에 사용 |
| **`Padiem`** | 별도 비즈니스용 계정 | 현재 Padiem AI 작업 대상에서 제외 |

이 구분은 2026-10-21 Owner의 명시적 작업 범위 결정입니다. 두 계정의 리소스 목록이나 현재 권한을 이 문서에서 실측했다고 주장하지 않습니다. 다른 비즈니스 작업에 `Charliekant`를 일괄 적용하는 규칙도 아닙니다.

실행 전 기준:

1. Padiem AI 작업이면 기대 계정 이름을 먼저 `Charliekant`로 고정합니다. `wrangler whoami`의 첫 계정이나 제품·도메인 이름으로 선택하지 않습니다.
2. 기존 승인된 계정 설정과 해당 작업의 인증 출처를 통해 계정 ID가 `Charliekant`에 대응하는지 확인합니다. 로컬 프로세스/`.env`/OAuth와 GitHub Actions의 `CLOUDFLARE_ACCOUNT_ID`·인증 출처를 구분합니다. 계정 ID와 자격증명 원문은 공개 문서·로그에 추가하지 않습니다.
3. 현재 설정이 `Padiem`을 가리키면 **이번 작업의 계정 범위 불일치**로 보고합니다. 문서 수정만으로 전역 환경·워크플로 Secret·운영 바인딩을 변경하거나 다른 계정 권한을 사용하는 승인이 생기지 않습니다. 기존 승인 범위의 `Charliekant` 인증 경로로 작업을 이어갑니다.
4. `Charliekant`에서 목적 API가 실패하면 HTTP 상태·Cloudflare 오류 코드와 실제 인증 출처를 확인합니다. 일반 API 실패만으로 “워커가 없다” 또는 “다른 계정으로 가야 한다”고 결론 내리지 않습니다. 계정 선택의 기준은 이 표이며, 실제 로그/리소스 권한 판정은 아래 절차를 따릅니다.

간결한 진단 기록에는 `EXPECTED_ACCOUNT=Charliekant`, 실제 확인한 계정 이름, `ACCOUNT_MATCH`, 인증 출처, 대상 API와 오류 코드를 남깁니다. 확인하지 않은 실제 계정이나 권한은 `UNKNOWN`으로 표시합니다.

## 1. 같은 이름이어도 서로 다른 인증 경로

| 경로 | 자격증명 출처 | 확인할 것 |
| --- | --- | --- |
| 로컬 API 토큰 | 프로세스 환경 또는 Wrangler가 읽는 `.env`의 `CLOUDFLARE_API_TOKEN` | 실제 선택된 출처, 토큰 종류, 대상 계정·API 권한 |
| 로컬 Wrangler OAuth | `wrangler login`으로 저장된 기존 프로필 | 같은 Windows 사용자·호스트·프로필인지, 정상 갱신되는지 |
| GitHub Actions | 워크플로·environment의 보호된 Secret | 정확한 workflow/ref/run, 허용된 작업과 실제 성공 API |
| Worker의 Secret/Secrets Store 바인딩 | Worker의 서버 측 구성 | 바인딩 확인과 실제 사용 성공을 구분. 로컬 CLI 인증과 별도 |

같은 변수 이름도 로컬 환경과 GitHub Secret이 같은 값·종류·권한이라는 뜻이 아닙니다. 로컬 인증 실패는 배포된 Worker 또는 고객 PC 장애의 증거가 아닙니다. B14 공급사 API 키, 제품 로그인 세션, Mesh 실행자 채널 인증도 Cloudflare 관리용 인증과 구분합니다.

Wrangler는 **환경변수 API 토큰 → API key/email → 저장된 OAuth** 순서로 인증을 선택합니다. API 토큰이 있으면 정상 OAuth가 있어도 그 토큰이 먼저 선택될 수 있습니다. OAuth 자동 갱신은 별도 API 토큰이나 다른 프로세스의 환경변수를 갱신하지 않습니다.

Windows 프로세스는 시작 시 부모의 환경변수를 상속합니다. 사용자/시스템 환경변수를 수정했어도 이미 실행 중인 터미널·에이전트와 그 자식은 이전 값을 가질 수 있습니다. 새 탭만 열었다는 이유로 새 값이 반영됐다고 판단하지 않습니다.

## 2. 처음 실패했을 때의 최소 확인

1. **출처:** 실행 호스트·OS 사용자 역할·작업 디렉터리·설치된 Wrangler 버전·활성 프로필/설정과 인증 출처를 확인합니다. 프로세스 환경, 프로젝트 `.env`, 사용자/시스템 설정을 구분합니다. 값 대신 변수 이름·출처·설정 여부만 확인합니다.
2. **실제 오류:** HTTP 상태, Cloudflare 오류 코드, 실패 API의 비밀값 없는 경로를 남깁니다. `1000`, `9109`, `10000`만으로 만료·폐기·권한 부족 중 하나를 단정하지 않습니다.
3. **기존 경로:** 앞서 성공한 OAuth 또는 작업 전용 인증 경로를 확인합니다. 토큰 생성·회전, 전역 환경변수 삭제, `wrangler logout`, 반복 API 호출을 기본 해결책으로 삼지 않습니다. 실제 권한 거부를 다른 계정·무관한 자격증명으로 우회하지 않습니다.
4. **목적 API:** `wrangler whoami` 성공이나 토큰 `active`는 목표 D1의 `SELECT`, Workers 로그 조회 또는 Secret 조회 권한의 증거가 아닙니다. 해당 작업에 허용된 최소 읽기 전용 API로 따로 확인합니다.

`/user/tokens/verify`는 사용자 API 토큰 검증 경로입니다. 계정 소유 토큰은 해당 계정의 토큰 검증 경로를 사용합니다. 이 API들을 Wrangler OAuth 세션의 공통 검증 API로 사용하지 않습니다. 실패한 검증 한 건으로 모든 Cloudflare 인증이 무효라고 보고하지 않습니다.

## 3. 환경변수 충돌과 기존 OAuth를 분리하는 로컬 확인

전제는 **기존에 승인된 같은 계정의 OAuth를 확인하는 작업**입니다. 토큰 값을 복사하거나 영구 설정을 바꾸지 않고, 별도 자식 프로세스에서 환경변수 인증의 영향을 제외합니다. 부모 에이전트와 다른 작업의 환경은 유지합니다.

PowerShell 예시: 이미 Wrangler가 설치된 기존 작업 디렉터리에서 실행합니다. 설치가 없으면 `--no-install`이 실패한 사실을 기록하고 임의 설치·업그레이드로 범위를 넓히지 않습니다.

```powershell
$authChildScript = @'
Remove-Item Env:CLOUDFLARE_API_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:CF_API_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:CLOUDFLARE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:CF_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:CLOUDFLARE_EMAIL -ErrorAction SilentlyContinue
Remove-Item Env:CF_EMAIL -ErrorAction SilentlyContinue
npx --no-install wrangler whoami
exit $LASTEXITCODE
'@
& (Get-Process -Id $PID).Path -NoProfile -Command $authChildScript
```

**환경변수를 제외한 것만으로 OAuth 선택을 확정하지 않습니다.** Wrangler가 작업 디렉터리/설정에 따라 `.env`에서 API 자격증명을 다시 로드할 수 있습니다. 실제 사용 인증 종류를 확인하고, 다시 로드됐다면 파일의 존재·변수 이름·설정 위치만 파악합니다. `.env` 원문을 출력하거나 전역 설정을 고치지 않습니다. 설치 버전이 지원하는 기존 프로필·작업 경로로 OAuth 확인 조건을 맞춥니다.

기존 OAuth는 정상 동작 중 만료된 access token을 자동 갱신할 수 있습니다. 저장 파일의 `oauth_token`/`refresh_token` 필드 존재나 과거 만료 시각만으로 현재 유효성을 판단하지 않습니다. 토큰을 직접 꺼내 HTTP 헤더에 넣는 대신 Wrangler의 기존 갱신 경로를 사용합니다.

`whoami`에서 OAuth와 목표 계정을 확인한 뒤에도, D1·로그 등 목적 API의 권한은 따로 확인합니다. OAuth 경로도 실제 실패하면 그 오류를 보고합니다. 다른 계정 로그인이나 토큰 교체를 암묵적으로 진행하지 않습니다.

## 4. D1 및 보호된 GitHub Actions 조회

- 로컬 자격증명과 Actions의 보호된 자격증명은 별개입니다. 한쪽의 실패·성공을 다른 쪽 권한의 증거로 사용하지 않습니다.
- 기존 워크플로가 지원하는 조회 범위를 소스에서 확인합니다. **스키마 전용 게이트를 애플리케이션 행 조회 도구로 사용하지 않습니다.** 스키마 `EXACT`는 특정 run/dispatch 행 존재의 증거가 아닙니다.
- 해당 작업에 승인된 행 조회 경로가 있으면 사용자·run·dispatch를 특정한 최소 읽기 전용 조회로 확인합니다. Secret을 로컬로 복사하거나 다른 DB를 대신 조회하지 않습니다. 승인된 경로가 없으면 정확히 부족한 조회 기능과 최소 보강안을 제시합니다.
- B66/Chat의 기존 스키마 확인·배포 성공 기록과 재사용 절차는 [B66_D1_ACCESS_AND_PRODUCTION_RELEASE_20261015.md](B66_D1_ACCESS_AND_PRODUCTION_RELEASE_20261015.md)에 있습니다. 이 문서의 스키마 실행 예시는 일반 고객 데이터 조회 승인이 아닙니다.
- Secret 메타데이터의 조회 성공은 원문을 읽을 수 있다는 뜻이 아닙니다. ownership map은 승인된 원본 또는 서버 측 검증 결과에서 필요한 일치·단일성만 확인하며 공개 로그에 원문을 남기지 않습니다.

## 5. 로그 접근과 실제 장애 판정

- `logging.warning()` 추가는 로그 보존·Grafana 전달·과거 조회 가능성의 증거가 아닙니다. 실제 수집기, 보존 설정과 읽기 권한을 확인합니다.
- 실시간 tail은 이후 로그 구독입니다. 구독 자체가 PC 명령을 재실행하는 것은 아니며, 과거 요청의 로그를 복원하지도 않습니다. 로그 확보를 위해 새 Chat POST·PC 명령을 자동 발생시키지 않습니다.
- 계정 확인, Workers 실시간 tail, 보존 로그 조회 권한은 서로 다를 수 있습니다. 실제 거부된 API와 오류를 보고합니다. 관측 기능 활성화·Logpush 추가·권한 변경은 문서 수정이나 읽기 전용 조사에 포함된 것으로 간주하지 않습니다.
- UI 답변 표시·무서명 401·클라이언트 unknown 상태·claim 로그 부재만으로 각각 저장 성공·Mesh 구성 정상·PC 오프라인·dispatch 미생성을 확정하지 않습니다. 요청 식별자와 서버 기록을 대조합니다.

간결한 보고 항목:

```text
AUTH_SOURCE=<process_env / project_env / stored_oauth / workflow_secret>
HOST_CONTEXT=<호스트 역할·OS 사용자 역할·작업 경로·프로필>
ACCOUNT_MATCH=<PASS / FAIL / UNKNOWN>
AUTH_CHECK=<확인 방법·결과>
RESOURCE_CHECK=<대상 API·결과 또는 NOT_EXECUTED>
ERROR=<HTTP 상태·오류 코드 또는 NONE>
NEXT=<최소 다음 동작 또는 필요한 사용자 조치 1개>
```

계정·기기·고객 식별자는 공개 보고에서 생략하거나 마스킹합니다. 원시 토큰, 쿠키, refresh token, `.env`/OAuth 저장 파일 원문, Authorization 헤더를 출력·첨부하지 않습니다. 토큰을 출력하는 명령의 결과를 보고서에 복사하지 않습니다.

## 6. #5015 인증 충돌 인수인계 — 2026-10-19 KST

제공된 조사 보고에는 로컬 환경변수 토큰으로 보낸 검증 요청이 거부됐고, 자식 프로세스에서 그 환경변수를 제외한 뒤 기존 OAuth의 갱신과 D1 조회가 성공했다고 기록돼 있습니다. 토큰 재생성·전역 환경 설정 변경 없이 경로를 분리한 사례입니다. 이 기록은 현재 모든 호스트의 인증 정상이나 PC 실행 장애 해결을 뜻하지 않습니다.

이전의 `9109 = OAuth 만료` 또는 `로컬 토큰 실패 = 운영 조회 불가` 단정은 재사용하지 않습니다. 연결 장애·실행 결과 추적은 기존 [#5015](https://github.com/skerishKang/ai-revenue-lab/issues/5015)에서 이어갑니다. 과거 pending run 정리, 코드 배포, 로그 설정 변경은 각각 실제 실행 여부를 별도로 기록합니다.

## 7. 역사적 기록 — 현재 자격증명 상태표가 아님

다음은 당시 기록의 보존입니다. 현재 토큰 종류·값·만료·권한은 이 표로 판단하지 않습니다.

| 당시 항목 | 당시 기록 |
| --- | --- |
| GitHub secret | `CLOUDFLARE_API_TOKEN` (GitHub production environment) |
| Cloudflare token name | `ai-revenue-lab-pages` |
| 2026-07-30 종류·상태 | Wrangler OAuth access token을 사용한 임시 복구 자격증명; run `30581067392` |
| 2026-09-06 D1 기록 | `b54-engine-d1-provision-gate.yml`에 필요한 Account > D1 > Edit 추가 기록 |

당시 로컬 OAuth access token을 CI에 복사한 방식은 Actions에서 자동 갱신되지 않고 만료를 알 수 없다는 위험이 기록됐습니다. 전용 CI API 토큰 권고는 당시 개선안이며, 현재 자격증명이 이미 교체됐거나 지금 교체해야 한다는 증거가 아닙니다. 원래 Pages 중심 권한 밖이던 D1 API의 `10000` 기록도 당시 범위로 해석합니다.

기존 `audit-cloudflare-pages-credentials.yml`은 Pages/계정 중심 읽기 전용 감사입니다. 그 실행 범위·일정은 현재 워크플로 소스를 확인하며, 성공을 D1 행·Workers Logs·Secrets Store 전체 권한 증거로 확대하지 않습니다.

과거 `urllib.request` in-process patch 설명은 토큰 감사 테스트의 mock 격리 기록입니다. 모든 로컬/배포 요청이 해당 방식으로 보호된다는 운영 보장은 아닙니다. 배포는 [정식 배포·롤백 절차](DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md)를 따릅니다.

관련 역사 자료: 비공개 운영 저장소 `skerishKang/ai-revenue-operations`의 `incidents/2026-07-31-cloudflare-pages-credential-401.md`. [2026-10-15 read-only run](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38693899424)은 당시 B66 스키마 성공 기록입니다.

## 공식 참고

- [Wrangler 일반 명령·인증 선택 및 OAuth 갱신](https://developers.cloudflare.com/workers/wrangler/commands/general/)
- [Wrangler 시스템 환경변수·프로젝트 .env 로딩](https://developers.cloudflare.com/workers/wrangler/system-environment-variables/)
- [사용자 API 토큰 검증](https://developers.cloudflare.com/api/resources/user/subresources/tokens/methods/verify/)
- [계정 소유 API 토큰 검증](https://developers.cloudflare.com/api/resources/accounts/subresources/tokens/methods/verify/)
- [Windows 환경변수와 자식 프로세스 상속](https://learn.microsoft.com/en-us/windows/win32/procthread/environment-variables)
