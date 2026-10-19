# B14 → ExLab 장애 시 로컬 직접 호출 비교 Runbook

**관련 이슈:** #4186, #4252
**대상 모델:** B14 = experiential/qwen3.8-flash-next-uncensored, upstream = qwen3.8-flash-next-uncensored
**원칙:** B14 실패가 확인되었을 때 **로컬 → ExLab 직접 호출을 정확히 한 번** 실행하고 결과를 비교합니다. 무한 재시도, 임의 공급자 전환, 원격 키 변경은 하지 않습니다.

## 언제 실행하나

1. B14에서 정확한 모델을 수동 지정해 호출했는데 HTTP 429/503/504 또는 빈 응답으로 실패한다.
2. B14 로그에서 요청 ID, HTTP 상태, 모델명, 안전한 오류 분류를 기록한다. 등록 여부는 실응답을 보장하지 않는다.
3. 로컬 스크립트를 사용해 ExLab에 **직접 정확히 한 번** 호출한다. 가능하면 동일 키·모델·합성 입력·토큰 상한 32·비스트리밍으로, 짧은 시간 간격 내 비교한다.
4. 아래 표대로 결과를 분류하고 #4252 또는 #4186에 기록한다.

**주의:** B14 HTTP 호출은 브라우저(Tabbit)로 검증합니다. 로컬 httpx로 Cloudflare Worker를 호출하면 Cloudflare/WAF 403이 나타날 수 있어 모델 오류로 혼동할 수 있습니다. 이 스크립트는 B14를 우회해 ExLab 공식 API만 호출합니다.

## 로컬 실행 (Windows PowerShell, 소유자 PC)

저장소 루트에서 실행합니다. Python 및 httpx가 필요합니다.

    # 1. 사전확인: 기본값은 네트워크 호출 0회
    python scripts\ops\b14_exlab_direct_probe.py

    # 2. 자신의 개인 API 키 노트 경로를 현재 세션에만 설정
    # 경로는 개인 PC의 실제 로컬 비밀키 노트 경로로 교체
    $env:PADIEM_EXLAB_CREDENTIAL_NOTE = 'G:\your-private-folder\apikey.txt'

    # 3. 명시적으로 1회의 실제 ExLab POST 실행
    python scripts\ops\b14_exlab_direct_probe.py --send

    # 4. 세션에 보관한 노트 경로 변수 제거
    Remove-Item Env:\PADIEM_EXLAB_CREDENTIAL_NOTE

노트 파일은 https://platform.experientiallabs.ai/ 가 단독 줄에 있고 **바로 다음 줄이 API 키**인 기존 개인 노트 형식을 사용합니다. 이 블록이 없거나 두 개 이상이면 요청 없이 중단합니다. 로컬 환경변수 PADIEM_EXLAB_API_KEY를 설정한 경우에는 노트 없이도 사용할 수 있습니다. 두 경로가 동시에 설정되면 fail-closed 중단합니다.

키 값은 명령행 인수, 문서, GitHub, 채팅에 기록하지 않습니다. 기본값은 DRY_RUN_NO_NETWORK 및 calls_sent=0입니다. --send 시 최대 calls_sent=1, retry_count=0, fallback_used=false입니다. 응답 본문/원문, 프롬프트, Authorization 헤더, 키·키 식별자는 출력하지 않습니다. 출력되는 것은 미리 정한 상태·HTTP 코드·요청 시간·모델 및 합성 마커 일치 여부뿐입니다. 모호한 실패라도 **자동으로 재호출하지 않습니다**.

## 결과 해석

| B14 결과 | 로컬 직접 결과 | 판단 및 다음 확인 |
|---|---|---|
| HTTP 429/504 등 실패 | HTTP 200 + 정확한 모델/합성 마커 | **B14 경로 우선 조사:** 운영 키 동일 여부(ExLab 공식 요청 이력), 요청 헤더/본문, Worker 연결/응답 처리/타임아웃 |
| HTTP 429/504 등 실패 | HTTP 429 unavailable_route 또는 HTTP 503 deadline_exceeded | **ExLab 경로/용량 불안정 가능성 높음:** ExLab 공식 요청 이력, 공급 경로, Retry-After 존재 여부 확인. B14 원인 완전 배제 금지 |
| HTTP 429/504 등 실패 | HTTP 401/403 | 로컬 키 또는 공급자 계정 권한 점검. 다른 키로 실험했다면 비교 불충분 |
| HTTP 429/504 등 실패 | 로컬 타임아웃/연결 오류 | 로컬 네트워크·프록시·공급 경로가 원인일 수 있음. 요청이 도착했을 수 있으니 자동 재시도 금지 |
| B14 HTTP 200 | 로컬 호출 생략 | 비교 목적의 추가 과금 호출 불필요 |

Cloudflare Secrets Store는 비밀키의 실제 값을 조회할 수 없습니다. 소유자가 양쪽 키를 맞춘 뒤 공급업체 대시보드의 키 구분을 확인합니다. 몇 분이라도 시간차가 있으면 완전한 동일 시점 실험은 아닙니다.

## 2026-10-11 실행 증거 (KST)

- **03:17** B14 신규 Worker f8d89b51, 정확한 모델, 재시도 0회: HTTP **429**, 981 ms, upstream_rate_limited, 안전한 분류 reason_group=route_unavailable, 요청 ID b14req_c5bc0d478a2d. 공급자 공식 이력에는 모델 용량 부족으로 표시.
- **03:32:55** 로컬 기존 1회 스크립트 실행: HTTP **503**, 15,016 ms, error_code=deadline_exceeded, 호출 1회 및 재시도 0회. 로컬 직접 경로에서도 답변을 받지 못했음.
- **02:23** 같은 모델의 B14 HTTP **200**, EXLAB_OK 정상 응답도 있었음. 모델이 항상 실패하는 것은 아님.
- 따라서 이번 비교는 서로 다른 시점(약 16분)의 **공급 경로 불안정 정황**이며, B14 문제가 완전히 없다는 증거나 동시 통제 실험은 아닙니다.
- 키·개인 정보는 기록하지 않았습니다.

## 운영 원칙

- 로컬 성공 1회로 Cloudflare 자체 장애를 확정하거나 로컬 실패 1회로 B14 버그를 배제하지 않습니다.
- B14 안전한 오류 코드, ExLab 공식 요청 이력, 시간·모델명만 기록합니다.
- 사용자 데이터가 아닌 합성 테스트 문장만 사용합니다.
- 운영 키 교체, Production 배포, 자동 반복 호출 및 모델 임의 전환은 진단 범위 밖입니다.
- CI는 **오프라인 단위 테스트만** 실행하고 실제 공급업체 호출은 0회입니다.
