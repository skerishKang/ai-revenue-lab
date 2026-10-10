# B14 신규 제공업체 Kira / Qwen3.8 Flash Free (#4018)

<!-- OWNER_BILLING_REBASE_20261010 -->
## 2026-10-10 Owner 계정 요금제 정정 — 기존 프로모션 설명보다 우선

Owner가 **Kira 유료 계정**과 **매일 10,000,000토큰 충전**을 보고했습니다(실제 계정의 신용량·청구내역을 재조회한 값이 아님). `qwen3.8-flash-free`의 `-free`는 **서빙 모델 식별자**, 계정 무료/영구 무제한 요금 판정이 아닙니다.

**필수 구분:** [Kira 공식 안내](https://kiraai.vn/)는 구독 플랜 포함 토큰이 `kira-`로 시작하는 모델에 적용되고 제휴 모델은 별도 VND 지갑/모델별 요금을 쓸 수 있다고 명시합니다. B14 upstream `qwen3.8-flash-free`는 `kira-` 접두어가 없습니다. 따라서 Owner가 보고한 **일일 1,000만 토큰이 이 exact 모델 요청에 차감되는지는 UNKNOWN**이며, 실제 호출 승인 전에 해당 모델의 계정 사용권·지갑 차감·무료 프로모션 적용을 별도로 확인해야 합니다. 공개 프로모션 표시와 사용자 유료 구독은 동시에 참일 수 있습니다.

기존 **직접 Kira API 실측 HTTP200·비어 있지 않은 답변(2026-10-10)**은 유지하되, 그 1회 성공을 B14/Engine/Claw 최신 버전의 정상 실행·현재 RPM/RPD·현행 유료 사용권 검증으로 승격하지 않습니다. `b14_models.json`·credential·Provider 원점·요금 숫자·자동 fallback·실제 API 요청에는 변경을 가하지 않습니다.
<!-- /OWNER_BILLING_REBASE_20261010 -->

**기준일:** 2026-10-10 KST
**등록 권한:** Product Owner 요청 / 기존 수동 모델 선택 유지
**실측 상태:** Kira 직접 API 키 연결 1회 HTTP200, B14 소스 등록 및 배포 검증 별개

## 1. 정확한 모델·실제 서빙 제공업체

| 구분 | 값 |
|---|---|
| 모델 제작사·계열 | Alibaba Qwen 계열 (Kira 소개 기준) |
| 실제 서빙/API 제공업체 | Kira AI, 베트남 |
| Kira 공식 모델 페이지 | https://kiraai.vn/models/ |
| Exact Kira model ID | `qwen3.8-flash-free` |
| Exact PADIEM B14 model ID | `kira/qwen3.8-flash-free` |
| OpenAI-compatible origin | `https://kiraai.vn/api/v1` |
| Chat API path | `POST /chat/completions` |
| Worker Secret Store alias | `PADIEM_KIRAAI_API_KEY` |
| Kira 표시 컨텍스트 | 1,000,000토큰 (업체 공시, 길이 실측 전) |
| Kira 표시 출력 상한 | 131,072토큰 (업체 공시, 길이 실측 전) |
| 실제 요금 | 무료 프로모션 진행 중(시한 표시), 영구 무료 보장 없음 |

모델명에 Qwen 계열이 명시되어 있어도 **Alibaba 원본 모델과 Kira 자체 서빙 모델이 동일하다는 증거는 아직 없다.** B14에서는 실제 **Kira가 제공하는 정확한 모델 ID와 Kira API wire**를 권위로 사용한다. Kira의 `thinking`, `reasoning_effort`, `temperature` 등은 모델 원제작사 설정을 가져와 강제로 전송하지 않는다.

## 2. 선행 직접 테스트 증거

Kira 키가 존재하는 **Charliekant Cloudflare Secrets Store**에서 임시 Worker에 바인딩해 Kira 공식 Chat Completions API에 한국어 짧은 질문을 한 번 전송했다.

- upstream HTTP **200**; 응답 모델 `qwen3.8-flash-free`, 답변 `OK`, `finish_reason=stop`, 4,740ms
- Kira 반환 usage: 입력 1,931토큰, 출력 76토큰 (실제 과금·세부 프롬프트 내부 처리값은 Kira 사양에 따름)
- 요청에서 `temperature/max_tokens/reasoning_effort` 생략. 같은 모델 재시도 0, 다른 모델로 대체 0
- 시험용 Worker 삭제 성공, 임시 실행파일 삭제 성공; 기존 B14 Worker는 변경하지 않음
- 이 테스트는 **Kira 공급업체 직접 호출 성공**이며 B14 등록/Engine·Claw 견적·PDF 정확도까지 실증하지 않음

## 3. B14 코드 변경

- Canonical `apps/korean-ai-platform/app/pilot/b14_models.json`에 Kira provider **1곳**과 `kira/qwen3.8-flash-free` 모델 **1개를 목록 마지막에 추가**. 기존 10개 ID·순서·사용자 수동 선택/기본 UI를 유지한다. 목표 등록 11개/제공업체 8곳
- `wrangler.toml`에는 **기존 Kira Secrets Store record를 참조하는 메타데이터만** 추가한다. Worker의 `_ENV_KEYS`에 전용 alias를 명시해 `await env.PADIEM_KIRAAI_API_KEY.get()`를 통해 해당 요청이 실행할 때만 값을 꺼내 `Authorization: Bearer ...`로 전송한다. 다른 제공업체 키/원점 재사용 금지
- `context_window=1000000`은 업체 공시, `capabilities=["chat"]`만 초기 등록. 이미지/Tools/실제 Thinking·Streaming 기능은 API 별도 회귀 실증 전 UI에 모델 공식 지원으로 승격하지 않는다. `max_tokens=131072`을 임의 전역 요청으로 강제하지 않는다.
- Free가 **기간 한정**일 수 있으므로 영구 제로 요금으로 보이지 않게 `input/output_price_usd_per_1m=null` 유지. 실제 Kira 원격 계정 가격은 후속 확인
- 네이티브 옵션은 정확한 Kira API 해당 모델 지원 문서 검증 전 `reasoning_effort/top_p/top_k/min_p` 등을 **미확인·미지원** 처리(요청 시 사전 422). 미지정 시 제공자 기본값 사용
- `groups.plus/pro/max` 비움 유지. `b14/auto` 및 excluded 모델·자동 우회 라우터를 도입하지 않음

## 4. 병합·운영 완료 판정과 향후 평가

1. Source focused + B14 complete + docs consistency + CI PASS, exact main에 PR 병합
2. B14 공식 Production Deploy Gate exact-main 1회 배포, 새 버전 100% 적용·binding·등록 11/8 안전 검증
3. 실제 운영 B14 `POST /api/pilot/v1/chat/completions`, `model=kira/qwen3.8-flash-free`, `max_retries=0`, `allow_external_fallback=false`, 짧은 합성 질문 1회 응답 확인
4. 한국어 견적 QKR-001~010, PDF·SSE/도구·이미지·무료 정책은 **#2676의 별도 모델 평가 단계**. 1회 정상 응답으로 정확도·안정성 순위 확정 금지

**근거:** [Kira 공식 모델 페이지](https://kiraai.vn/models/), [GitHub 이슈 #4018](https://github.com/skerishKang/ai-revenue-lab/issues/4018).
