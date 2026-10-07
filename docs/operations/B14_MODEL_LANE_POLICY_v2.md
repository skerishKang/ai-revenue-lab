# B14 모델 레인 정책 v2 (Model Lane Policy v2)

- Owner decision: 2026-10-06 (successor selection, #3568/#3569 후속 — 이 대화에서 운영자가 직접 결정)
- 적용 범위: B14 플랫폼 모델 레인 전체 (kilo gateway 레인 + 프로바이더 바인딩 운영 방식)
- 상태: 이 문서가 이전 키리스 선호 정책을 대체한다.

## 1. 변경된 정책

### 1.1 키리스(keyless) 선호 폐기 → 시크릿 스토어 키 기반 인증

이전 정책(#3143/#3209)은 Kilo 무료 레인의 익명/키리스 실행을 선호했다.
정책 v2부터는 **모든 모델 레인이 Cloudflare Secrets Store 바인딩으로 인증**한다:

- `PADIEM_KILO_API_KEY` — Kilo 게이트웨이 전 레인 (wrangler.toml 바인딩 등록 완료)
- `PADIEM_AGNES_API_KEY`, `PADIEM_B_AI_API_KEY`, `PADIEM_POOLSIDE_API_KEY` 등 동일 저장소에 기등록

워커(`apps/korean-ai-platform`)는 바인딩이 존재하면 Bearer 인증으로 업스트림을 호출하고,
바인딩이 없는 경우에만 기존 익명 요청 형태로 폴백한다. 새 시크릿 값 도입은 없다.

### 1.2 max_tokens 자체 상한 없음 — 모델 선언치가 상한

- B66 견적 해석 경로는 `max_tokens`를 전송하지 않는다(전송 시 프로바이더/게이트웨이 한도 적용).
- 게이트웨이 검증 상한: 4,096 (`apps/korean-ai-platform/app/pilot/gateway.py`).
- 워크스페이스 UI 폼 기본값: 300 → **4,096**(게이트웨이 상한과 일치)로 상향.
- 모델의 실제 한도는 게이트웨이 모델 메타데이터(`top_provider.max_completion_tokens`)가
  유일한 출처이며, 코드가 별도의 상한을 만들지 않는다.

## 2. Space Bunny 레인 은퇴

- 원인: 업스트림 `stealth/space-bunny-alpha`가 Kilo 게이트웨이 공개 모델 목록에서
  제거됨(2026-10-06 재확인 — 목록 399종에 부재). 호출 시 실패.
- 처리: `kilo/stealth-space-bunny-alpha` 레인 등록 제거 + `RETIRED_KILO_FREE_MODEL_IDS`
  편입(은퇴 메타데이터 보존). `product_tier_routes.py`의 Plus 라우트는 HOLD 이력으로 유지.

## 3. 후속 모델 선정: Ling 3.1 Flash (InclusionAI)

Kilo 게이트웨이 공개 목록에서 확인 후 **라이브 검증 완료**(2026-10-06):

- 모델: `inclusionai/ling-3.1-flash` (키리스 프로브 HTTP 200, 비용 0)
- 컨텍스트 262,144 / 최대 출력 32,768 / text→text (vision 없음)
- 신규 레인: `kilo/inclusionai-ling-3.1-flash` (repo-facing 변환 규칙 준수)

**검증 시 관찰된 품질 플래그**: reasoning 모델이라 추론 토큰을 먼저 소비하며
(무상한 max_tokens로는 빈 응답), 통제 프롬프트 없는 추출 시험에서 예시값 환각 1회 관찰.
→ 프롬프트 측 통제(입력 문장 값만 사용 강제) 필요. 통제 프롬프트 재검증 1회가
속도제한(429)으로 미완료 — **후속 이슈에서 완료한다.**

## 4. Padiem Plus 실행 라우트 교체

`product_tier_routes.py`:

- 신규 EXECUTABLE 라우트: `plus.ling-3.1-flash.v1`
  (provider `kilo` / model `kilo/inclusionai-ling-3.1-flash` / upstream
  `inclusionai/ling-3.1-flash` / credential binding `PADIEM_KILO_API_KEY`)
- 이전 실행 라우트 `plus.space-bunny-alpha.v1` → HOLD 이력 보존
- `plus.hold.v1` 센티널 → 데이터 전용 이력으로 보존
- Pro/Max 기존 HOLD 게이트 유지

Chat(`model_policy.py`)은 계약 기반 파생이므로 코드 수정 없이 자동 적용된다.

## 5. Agnes 3.1 후보 (미확정)

- Agnes 플랫폼(apihub.agnes-ai.com)은 키 필수 — 키리스 확인 불가(401 확인).
- `PADIEM_AGNES_API_KEY` 바인딩이 시크릿 스토어에 있으므로, B14 워커 경유 또는
  운영자 콘솔에서 agnes-3.1 제공 여부 확인이 가능하다. 확정 전까지 미등록.

## 6. 후속 작업

- [ ] 통제 프롬프트로 ling-3.1-flash 재검증 (환각 조절 확인)
- [ ] hold 상태를 고정한 테스트 갱신 (test_product_tier_routes / test_model_policy /
      test_neutral_mock_copy / test_unassigned_profile_gate / test_plus_space_bunny_image /
      test_tier_registry_v1 / test_model_primary / test_space_bunny_* /
      apps/b66-quote-adapter test_extraction_routing)
- [ ] Agnes 3.1 가용성 확인 (바인딩 키 경유)
- [ ] 배포 후 실계정 smoke
