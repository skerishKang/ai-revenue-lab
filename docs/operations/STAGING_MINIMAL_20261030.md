# 최소 스테이징 설계 (#6305)

상태: 설계 제안. 리소스 생성·워크플로 구현·운영 인증 서버 배포는 이 문서의 머지로 승인되지 않는다. 목표는 반나절 안에 실제 Workers 런타임과 로그인 경로를 검증하는 것이다. 코드가 바뀌면 동일한 head를 스테이징에서 다시 확인한다.

## 이름·경로·바인딩

아래 이름은 제안이며 실제 workers.dev 서브도메인과 계정 플랜, 이름 충돌은 생성 전에 확인한다. 운영 URL 또는 ID를 복제하지 않는다.

| 대상 | 스테이징 제안 | 운영과의 경계 |
|---|---|---|
| Chat Worker | `padiem-chat-staging`, `https://padiem-chat-staging.<account-subdomain>.workers.dev` | 별도 Worker·배포 버전·변수·시크릿. 운영 `chat.padiem.net` route 미등록. 실제 호스트는 계정에서 확인. |
| Chat D1 | `padiem-chat-staging-db`, 바인딩명 `PADIEM_CHAT_DB` | 별도 DB ID. 검토된 동일 마이그레이션으로 빈 DB에 스키마만 생성. 운영 데이터·백업·계정 복사 금지. |
| Auth callback | 위 스테이징 origin의 `/auth/shared/callback` 한 개 | padiem-auth의 b62 허용 목록에 정확한 URL과 해당 클라이언트 공개키를 추가하는 별도 PR. 실제 콜백은 #6282 코드의 최종 경로와 대조. 기존 운영 콜백·키 유지. |
| Auth 클라이언트 | 기존 b62 프로토콜, 스테이징 전용 클라이언트 서명키와 세션·상태 키 | 값은 별도 시크릿으로 주입, 저장소·로그에 기록 금지. 개인키 생성·보관은 승인된 절차로 시행하고 운영 padiem-auth의 키는 재생성하지 않음. |
| COM2 큐 | `PC_QUEUE_BACKEND=com2`; `PC_QUEUE_ORIGIN`은 Qoder가 제공할 전용 스테이징 HTTPS Tunnel 주소; `PC_QUEUE_SERVICE_SECRET`은 전용 시크릿 | Qoder가 별도 포트·DB·자격증명·터널 및 합성 실행기 구성. 운영 큐 URL/DB/시크릿·실제 PC에 연결 금지. |
| 기타 서비스 | `ASSETS`, `CF_VERSION_METADATA`는 스테이징 Worker 자체 것 | 운영 D1·R2·P01·B14·Broker·파일 레인 등 쓰기 가능한 바인딩은 미연결. 필요한 것은 별도 스테이징 또는 fail-closed 테스트 대체만 사용. 실제 경로라고 주장하려면 대체 여부를 결과에 명시. |
| 관찰 | 스테이징 Worker 로그·버전 메타데이터 | 시각·단계·상태·안전한 상관값만 기록. 본문·헤더·비밀·사용자 식별 정보 금지. |

## 인증 경계: 구현 전 결정 필요

현재 padiem-auth는 자체 상태 저장소와 `IDENTITY_AUTHORITY`에 연결된다. #6296/#6282는 프로필 교환과 identity authority의 신규 RPC를 요구한다. **운영 padiem-auth에 콜백만 추가해도 실제 로그인은 운영 인증 상태와 identity authority에 쓰기를 일으킬 수 있다.** 별도 Chat D1만으로 전체 인증이 격리되는 것은 아니다. 또한 운영 authority가 새 RPC를 지원하지 않으면 정상 통합이 불가능하다.

CTO는 실제 로그인 시험에서 운영 padiem-auth/identity authority에 남을 시험 계정 및 일회성 인증 상태 쓰기를 허용할지, 아니면 별도 스테이징 auth·identity authority와 별도 상태 저장소를 사용할지 결정한다. 후자는 추가 리소스와 설정이 필요하며 반나절 목표를 재평가한다. 어떤 선택이든 운영 Chat D1과 운영 padiem-auth 키는 변경하지 않는다. 결정 전에는 콜백 추가 PR 설계만 진행하고 로그인 시험·인증 서버 배포는 하지 않는다. 단순 모의 authority 통과는 실제 로그인 통과로 보고하지 않는다.

## 무료 한도와 타당성

- Workers Free는 계정 전체 일 100,000 요청, 요청당 CPU 10ms, 메모리 128MB, Worker 100개다. D1 Free는 계정 일 500만 행 읽기·10만 행 쓰기, DB당 500MB, 계정 저장 5GB·DB 10개다. 일일 한도는 UTC 자정에 초기화한다. [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [D1 limits](https://developers.cloudflare.com/d1/platform/limits/), [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/).
- 플랜은 Worker별이 아닌 계정 기준이다. 현 운영 계정의 실제 플랜·사용량은 미확인이다. 운영 계정의 요금제 변경이나 다운그레이드 없이 무료 범위 안의 저사용 테스트를 목표로 한다. 별도 Free 계정을 택하면 service binding·접근 권한·인증 연동을 다시 검증해야 한다. Free 10ms CPU가 Python 로그인 경로에 충분한지도 실제 실행으로 확인한다. 초과하면 성공으로 간주하지 않고 측정 결과와 대안을 CTO에게 보고한다.
- 실 계정과 합성 데이터만 최소 요청으로 사용하고 외부 모델·메일·실제 PC 작업은 차단한다. 계정 공용 한도 소진이 운영에 영향을 줄 수 있으므로 사용량과 잔여 한도를 시험 전에 확인한다.

## 구현·검증 순서

1. CTO 설계 확인 및 위 인증 경계 결정 후, 실제 스테이징 호스트·계정 플랜·가용 한도와 격리된 서비스 대상을 확정한다. 운영 배포 창에는 main 머지 금지.
2. 스테이징 전용 Wrangler 설정과 최소 수동 workflow를 별도 PR로 작성한다. 기존 B62 운영 게이트를 복제하지 않는다. 고정된 검토 head, `padiem-chat-staging` 이름 및 스테이징 DB ID를 엄격 검증하고 운영 route·운영 DB·운영 자격증명 사용 시 실패한다. PR은 CTO가 머지한다.
3. 승인 후 빈 스테이징 D1에 스키마만 적용하고 리소스와 바인딩을 확인한다. Qoder가 별도 큐와 합성 실행기를 준비하면 스테이징 변수만 연결한다. 테스트 행 외 데이터 없음 확인.
4. #6296·identity authority 계약 준비, 스테이징 콜백 허용 목록 PR을 검토한다. padiem-auth 변경·재배포는 별도 CTO 승인 후 기존 키를 유지하며 `--keep-vars`를 사용한다. 해당 auth/authority 경계와 실제 RPC 지원 버전을 명시한다. #6282 코드가 반영된 스테이징 Chat을 배포한다.
5. 실제 Workers/Pyodide에서 로그인 1회: 인가→콜백→코드 교환→프로필 저장→세션 발급→인증 상태를 검증한다. 테스트 계정만 사용하고 토큰·프로필은 출력하지 않는다. 신규/기존·충돌과 기존 로그인 회귀는 자동 테스트로 확인하고, 어떤 서비스가 실제 또는 대체인지 기록한다. 이후 합성 PC 작업 요청→큐→실행기→결과까지 1건과 스테이징 복귀 1회를 별도 확인한다.
6. 정확한 소스 SHA·Worker 버전·스키마 버전·실제/대체 의존성·결과를 기록한다. 로그인 전환의 운영 5단계는 이 실제 로그인 성공과 별도 CTO 지시 이후에만 실행한다.

## 복귀

스테이징 장애는 스테이징의 직전 Worker 버전·설정으로 복귀하거나 테스트를 중단한다. 격리 DB는 그대로 보존하며 운영 리소스에 복귀 명령을 적용하지 않는다. 운영 padiem-auth에 콜백이 추가된 경우 제거도 별도 승인·PR과 `--keep-vars` 배포로 수행한다. 진행 중인 로그인은 실패할 수 있으므로 스테이징 세션을 종료한 뒤 재시험한다. 테스트 계정과 만료된 인증 상태의 정리 방법은 인증 경계 결정 때 확정한다.
