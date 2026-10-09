# B14 모델 평가 우선순위 — Owner 결정 (2026-10-10)

> **평가·재시험 작업 대기열이며 실서비스 자동 모델 순위·라우팅 정책이 아니다.**
> 정확한 사용자 지정 모델 선택이 유일한 실행 권한이다. 이 문서 때문에 어떤 모델도 등록 해제, 자동 변경, 우회·fallback, 기본 추천/선택하지 않는다.

## 0. 현재 등록소와 과거 평가의 범위 구분 — 2026-10-10 재확인

- **현재 코드 기준:** `apps/korean-ai-platform/app/pilot/b14_models.json`에 모델 **11개**, 제공업체 **8개** 등록. 이 숫자는 현재 `main` 소스의 사실이며, 과거 9모델·10모델 실측을 소급해 11모델 평가라고 부르지 않는다.
- **새로 추가된 평가 미확정 모델:** `kira/qwen3.8-flash-free`는 등록만 확인된다. 기존 이 문서의 6개 HTTP200 안정 경로 묶음, Gemma 4 31B HTTP504, Agnes/Atria 평가 후순위, ExLab Qwen 429 보류 기록 어느 쪽에도 근거 없이 포함하지 않는다. `평가 증거 없음/별도 검증 필요`로 표시한다.
- **등록과 검증 구분:** 11개 등록 ≠ 11개 실제 제공자 응답 확인 ≠ 11개 Claw/Engine E2E 확인. 실제 비교 순위는 사용자 지정된 평가 대상·동일 샘플·원래 제공업체 API 파라미터 및 완료된 응답 증거를 기반으로만 매긴다.
- **담당 구분:** #2676 B14 평가·기존 근거 정리 = CENTRAL 직접 담당, #3554 응답/Engine·Claw E2E = CENTRAL 직접 검증 책임, #3789 제외 모델 실행 안전성 = CENTRAL 직접 담당, #3977 Core·모델 파라미터 전달 = LOCAL1 담당. 서로 다른 PR/worktree를 침범하지 않는다.

## 1. 현재 우선순위 결정

**사용자 결정:** Agnes 3.0 Flash와 Atria Dawn Preview는 현재 운영 안정성 문제가 확인됐으므로 개별 장애 이슈를 보류 종료하고, 다른 정상 사용 가능한 모델보다 **평가 후순위**에 둔다. 이는 **모델 자체 품질이 낮다는 판정이 아니라 B14 운영 가용성·완료성 평가**다.

| 상대 우선순위 | 등록 모델 | 최신 근거·조치 |
|---|---|---|
| 정상 경로 평가 우선 | `google/gemini-3.1-flash-lite`, `google/gemini-3.5-flash-lite`, `google/gemma-4-26b-a4b-it`, `sensenova/sensenova-6.8-flash-lite`, `poolside/laguna-s-2.1`, `inception/mercury-2.5` | 2026-10-10 B14 운영 간단 합성 프롬프트 각 HTTP200·본문 확보. 최종 한국어 견적 정확도·PDF 고객 E2E 합격을 의미하지 않는다 |
| 가용성 재확인 필요 | `google/gemma-4-31b-it` | 동일 운영 실측 HTTP504, 소스·공식 설정만으로 실제 제공자 가용성 확정 불가 |
| **후순위 1** | `atria/Atria-Dawn-Preview` | SSE 운영 실호출 HTTP200·정상 [DONE] 성공 사례가 있지만 별도 504와 고객 견적→PDF E2E 미검증. 개별 #3922 **CLOSED / NOT_PLANNED (DEFERRED)** |
| **후순위 2** | `agnes-ai/agnes-3.0-flash` | 운영에서 HTTP429 반복. 안전 진단 결과 `Retry-After` 있음·업스트림 오류 범주 미분류, 계정/제공자 차단 원인 불명. #3913 **CLOSED / NOT_PLANNED (DEFERRED)**. Atria보다 낮은 재시험 우선순위 |
| 별도 보류 (순위 비교 제외) | `experiential/qwen3.8-flash-next-uncensored` | 제공업체 운영 HTTP429, 기존 Owner 보류 지시 유지. 이 문서로 재호출·자동 대체하지 않음 |
| 신규 등록·평가 증거 미확보 | `kira/qwen3.8-flash-free` | 현재 등록소에 모델이 존재함만 확인. 기존 9모델/41요청 평가 대상 아님. 실제 HTTP 응답·품질·견적 PDF E2E는 별도 검증 필요 |

**현재 등록된 11개 모델의 정확한 품질·성능 전체 순위는 확정하지 않는다.** 위 표는 운영 안정성에 따른 **재평가 우선순위 밴드**다. 429/504는 0점이나 모델 성능 불량으로 환산하지 않는다. 과거 제한된 QKR 비교 결과는 측정 당시 샘플·설정의 역사적 기록으로 유지한다.

## 2. 이슈 처리 결과

- [Agnes #3913](https://github.com/skerishKang/ai-revenue-lab/issues/3913): **Owner 요청으로 보류 종료**. 진단 소스 [PR #4006](https://github.com/skerishKang/ai-revenue-lab/pull/4006) 병합·실운영 배포는 완료. **HTTP429 복구 완료 아님**.
- [Atria #3922](https://github.com/skerishKang/ai-revenue-lab/issues/3922): **Owner 요청으로 보류 종료**. 수동 SSE UI [PR #3923](https://github.com/skerishKang/ai-revenue-lab/pull/3923), 안전 타임아웃 진단 [PR #4008](https://github.com/skerishKang/ai-revenue-lab/pull/4008) 병합·배포, 실호출 성공은 확인. **간헐적 504 및 견적→PDF 해결 완료 아님**.
- 실제 운영 배포 증거: [B14 Production run 37983673404](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37983673404), exact-main `080985248b1407621ca8240c3751b816ed63eeb3`.
- 모델 평가·재시험 총괄: [#2676](https://github.com/skerishKang/ai-revenue-lab/issues/2676); 전체 Claw·Engine 연동: [#3554](https://github.com/skerishKang/ai-revenue-lab/issues/3554).

## 3. 운영 영향 = 없음

이 결정은 **평가 대기열과 이슈의 처리 우선순위만 변경**한다.

- `b14_models.json`의 provider/model ID, enabled, 배열 순서, user-facing catalog, 사용자 수동 선택, 요금제/기본 모델/추천 모델/자동 fallback을 **변경하지 않는다**. 특히 배열 순서가 UI 초기 선택에 영향을 줄 수 있으므로 문서상 우선순위를 이유로 배열을 정렬하지 않는다.
- 모델 제작사·실제 제공업체의 공식 API 기준, 사용자 생략 파라미터의 생략 유지, 토큰 제한 제거 계약을 유지한다.
- 추가 반복 호출·비용 발생 실험을 새로 시작하지 않는다. Owner가 다시 지정하면 보류 상태의 기존 증거를 기준으로 재개한다.
