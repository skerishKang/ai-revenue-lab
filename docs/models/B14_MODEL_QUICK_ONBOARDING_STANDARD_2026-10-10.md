# B14 모델 등록: JSON 1회 / 빠른 CI 1회 / 배포 1회

**운영 기준 2026-10-10 — 등록과 품질 벤치마크를 분리한다.** 같은 제공업체(provider)에 정상 지원되는 신규 모델을 추가할 때 10개 QKR·Sol PDF·Drive·Claw·Engine·전체 1,100건 평가를 반복하지 않는다.

## 기존 제공업체의 신규 모델 — 권장 경로

B14 단일 기준: `apps/korean-ai-platform/app/pilot/b14_models.json`. 8개 기존 제공업체는 JSON 안에 `base_origin`, 허용 호스트 및 Secret **이름**이 등록돼 있다. 공급사에서 사용하는 정확한 `upstream_model`과 공식 모델 페이지를 확인한다.

신규 모델 **미리보기 (쓰기 없음, API 요청 0건)**:

```powershell
python .github/scripts/b14_model_quick_add.py add --provider kira --upstream example-future-model --name "Kira: Example Model" --source https://kiraai.vn/models/example-future-model/ --checked-at 2026-10-10
```

실제 신규 모델명을 공식 자료로 검증하고 **같은 명령에 `--write`만 추가**해 JSON에 1행을 append한다. 위 `example-future-model`은 데모 문자열이며 **등록/실제 호출 대상으로 사용하지 않는다**. 등록 전송 결과는 `JSON_APPENDED`와 `expected_ci_lane=model_registration_only`이며, `provider_api_posts=0`. 기존 엔트리, 모델 그룹, Secret, 코드, 타 제공업체를 변경하지 않는다. 가격 및 context window를 공식적으로 검증하지 못했으면 `null`과 `0`으로 둔다. 무료 프로모션만 보고 영구 무료 가격이나 `free` capability를 생성하지 않는다. 필요하면 `--input-price`, `--output-price`, `--context-window`, `--capability coding`, `--capability image`를 **검증된 사양으로만** 명시한다.

```powershell
python .github/scripts/b14_model_quick_add.py check --model-id kira/exact-upstream-id
```

이후 **한 PR에 JSON 추가만 넣는다**. 이미 구현된 `.github/scripts/b14_model_registration_ci_plan.py`의 *엄격한 append-only 판별기*가 다음 빠른 경로를 선택한다.

- B14: `.github/workflows/validate-b14-alpha.yml`의 `B14 fast model registration contract` (모델 레지스트리/수동 라우트/Secret 격리). `Locked Alpha full suite`는 **SKIPPED**.
- B62: `.github/workflows/b62-padiem-chat-ci.yml`의 `B62 B14 registry-only contract` (기존 B14 수동 선택 통합). B62 전체 회귀·Worker/Pyodide 작업은 **SKIPPED**.

**정확한 PR HEAD CI 통과 → 스쿼시 병합 → 별도 승인된 공식 B14 Production Deploy Gate 1회 → 배포된 `/api/pilot/models` GET으로 소스/운영 ID·provider·upstream 일치 확인**. Git 기반 Cloudflare Worker이므로 **로컬 Kilo Code처럼 JSON 저장 즉시 Production 반영은 아님**. 이 절차는 재배포 1회만으로 끝내도록 배포를 묶는다.

**최초 제공업체 등록은 별도:** 신규 `provider_id`는 JSON origin/allowed-host 추가, `worker.py`와 `wrangler.toml`의 정확한 Secret Store **이름** 추가, 실제 계정 내 Secret 값 연결/권한 확인이 일회성으로 필요하다. `b14_model_quick_add.py`는 새 제공업체를 자동 생성하거나 Secrets를 변경하지 않고 `NEW_PROVIDER_REQUIRES_ONE_TIME_CREDENTIAL_BINDING`으로 차단한다. 등록 이후 같은 제공업체의 다음 모델부터는 JSON-only.

## 기본 출시 합격선 vs 선택 벤치마크

| 항목 | 신규 등록 기본 | 추가 사용자가 요청할 때만 |
|---|---|---|
| 등록 정보 | JSON 스키마, 중복/폐기 모델, 공식 model ID, provider, upstream, endpoint, Secret 바인딩 **이름** | 전체 가격·quota/컨텍스트 연구 |
| 로컬/CI | 한 번의 변경분 빠른 회귀 | 전체 B14/B62 중복 회귀 |
| 운영 | 공식 배포 후 GET 메타데이터 일치 | UI/Claw/Engine/PDF/Drive E2E |
| 모델 API | 기본 등록에는 필요 없음. 연결 실측을 요구하면 **승인된 정확한 모델 1회**, no retry/fallback, 응답 완성·모델 일치·소요시간 기록 | 10문항 QKR, 여러 모델 품질 비교, 장문/대용량 문서, 스트리밍 내구성 |
| 문제 발생 | 오류/phase만 분류하고 해당 경계 해결; 동일 요청을 자동 재호출하지 않음 | 무차별 타임아웃 상향·모든 모델 재시험 |

**배포 성공 ≠ 모델 추론 결과 성공.** 첫 실제 고객 기능 요청은 실패 시 해당 모델에만 장애/가용성 이슈로 분리한다. 동시성, 비용, 품질 수치, 전체 문서/PDF 재현은 사용자 제품 평가에서 다루되 단순 등록을 막는 일반 선행조건이 아니다.

## 앞으로 과도한 공수를 방지하는 약속

- **모델당 이슈·PR 한 세트**가 기본. 재시도·호출 실패·글꼴·문서 렌더러를 독립 PR로 연쇄 분할하지 않는다. 예외는 실제 원인이 확인된 운영 장애다.
- 기존 공급사 모델은 **JSON 1곳 변경**, **빠른 CI 1회**, **Production 배포 1회(승인 시)**로 기본 수명주기를 마감한다.
- 전체 10건 이상 모델 품질 평가, 100% PDF 복제 테스트 및 결제 세부 연구는 제품 기능별 **별도 트랙**으로 분리한다.
- 모델 API 유료 가능 호출, Production 배포, Secret 값 변경은 각각 현행 승인 절차를 준수한다. 자동 실행 옵션을 새로 추가하지 않는다.
- 과거 Kira의 실제 `httpx.ConnectTimeout` 504 장애는 **기존 신규 등록의 표준 과정이 아닌 특정 런타임 장애 처리**였다. 공식 배포 v610에서 Kira만 connect=30초 패치됐지만, **실제 QKR-008 성공/정확도는 아직 별도 확인 전**이다.

### 개발자 자체 확인 (모델 API 0회)

```powershell
python .github/tests/test_b14_model_quick_add.py -q
python .github/scripts/b14_model_quick_add.py check --model-id kira/qwen3.8-flash-free
```

명령은 저장소 로컬에서 실행한다. `--write` 없이 실행하면 파일/Secrets/운영 환경이 변경되지 않는다.
