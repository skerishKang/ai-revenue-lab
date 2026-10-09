# B14 모델·서빙 제공업체 네이티브 API 파라미터 실행 계약

**2026-10-10 / 이슈 #3977 / 기준 [B14 역할](../architecture/B14_MODEL_PROVIDER_EXECUTION_AUTHORITY_2026-10-10.md)**

## 실제 변경 사항

- `gateway._validate_body`는 요청에서 생략한 `temperature`, `max_tokens`를 **None**으로 보존한다. 기존 숨은 `0.2`는 주입하지 않는다.
- `start.js`, `workspace.js`, `pilot.html`, `ui.py`, `workspace.py`는 브라우저·폼에서 `0.2/512/300/1800` 기본값을 만들어 내지 않는다. **사용자가 지정한 명시적 값만** upstream으로 전달한다.
- 일반/스트리밍 B14 플랫폼 어댑터는 정확한 모델 ID와 실제 provider origin을 보존하며, 모델이 공식적으로 허용하는 **명시적 옵션**만 그대로 HTTP JSON에 넣는다.
- 과거 일반 요청 공통 `max_tokens` 4,096 제한은 제거했다. **양의 32-bit 정수 wire safety bound**는 남되 이는 **공식 모델 최대 출력량이 아니다**. 실제 최대 출력 및 rate/credit 제약은 서빙업체 API가 결정하며 사용자가 초과 요청 시 provider가 오류를 낼 수 있다.
- 유효하지 않거나 출처가 입증되지 않은 **model-native 옵션은 네트워크 호출 전에 422**로 거부한다. 모델을 변경·대체하거나 사용자가 지정한 추론 강도를 몰래 줄이지 않는다.
- 기존 model authorization, credential binding, live fail-closed, no silent fallback 등의 안전 경계는 유지한다.

## 원제작사 공식 문서 + 제공업체 공식 API 문서

정확한 **B14 등록 ID**를 키로 모델 옵션을 관리한다. `b14_models.json`은 계속 **유일한 모델 등록 권위**이며, `model_native_parameters.py`는 모델 등록소나 별도의 Auto Router가 아니다.

| Exact B14 ID / 옵션 | 공식 API/제작사 근거 | B14 opt-in 지원 | 미지정 시 |
|---|---|---|---|
| `google/gemini-3.1-flash-lite` | [Google Gemini OpenAI 호환 thinking](https://ai.google.dev/gemini-api/docs/openai) + [Gemini 3 Thinking Level](https://ai.google.dev/gemini-api/docs/gemini-3) | `reasoning_effort` minimal/low/medium/high | **생략** |
| `google/gemini-3.5-flash-lite` | 동일 [Google OpenAI 호환](https://ai.google.dev/gemini-api/docs/openai) 및 이전 실제 모델별 직접 추론 테스트. 모델별 미지원 단계가 확인되면 별도 거부 | `reasoning_effort` minimal/low/medium/high | **생략** |
| `atria/Atria-Dawn-Preview` | [Atria 개발사 공식 모델 카드](https://huggingface.co/internlm/Atria-Dawn-Preview-FP8) / 제공업체 API 실측 low/medium/high 성공 | `reasoning_effort` low/medium/high (실제 제공업체 검증값만) | **생략** |
| `sensenova/sensenova-6.8-flash-lite` | [SenseNova 정확한 서비스 모델 공식 API](https://github.com/OpenSenseNova/SenseNova6.8/blob/main/API.md) | `top_p/top_k/min_p/presence_penalty/repetition_penalty` | **생략** |
| 그 외 등록 모델 6개 (Gemma4 26B/31B, Poolside, Mercury, Agnes, ExLab) | 정확한 서빙업체의 reasoning API 전달 규약 확인 전까지 지원하지 않음 | **공식 사양 불명 추론·샘플링 확장 파라미터 거부** | 실제 provider 기본 동작 |

**주의:** model card의 '권장 샘플링값'을 B14에서 무조건 전송하지 않는다. `temperature`나 `max_tokens` 기본값 **생략**은 공식 provider 네이티브 동작의 보존이다. 사용자가 명시적으로 고른 generic `temperature`와 출력 예산은 선택한 실제 API로 전달한다. Gemma의 별도 공식 `top_k=64`를 Google OpenAI-compatible API의 top-level `top_k`로 **검증 없이 변환하지 않는다**.

**주의:** HCNSEC `longcat-2.5`, `Qwen3.8-Flash-Next`는 **이번 B14 10개 등록 모델이 아니다**. 이들 HCNSEC upstream ID를 ExLab uncensored 모델 프로필에 섞거나 임의 등록하지 않는다.

## 회귀·실증

- `cd apps/korean-ai-platform && python -m pytest -q tests` — 현재 패치의 전체 B14 suite.
- `test_b14_native_parameters.py`: 등록 10개 숨은 기본값 0건, 공식 지원 옵션/거부, 수동 고출력 요청값 보존, MockTransport **completed + SSE** 파라미터 비교, ExLab 변형 모델 추측 금지, UI 숨은 주입 방지.
- 이 검증은 **네트워크 없는 코드/MockTransport 검증**이다. 실제 Provider와 B14 Production POST, 실제 견적 10문항, B66 견적/PDF 연결을 통과했다고 주장하지 않는다.
- 기존 10문항 historical `temperature=0` 점수는 별도 실험 조건 기록으로 유지. 공식 설정 재시험은 [#2676](https://github.com/skerishKang/ai-revenue-lab/issues/2676)에서 새 조건으로 진행한다.
- 사용자의 B66 추론 수준 UI는 Owner 승인된 [#3906](https://github.com/skerishKang/ai-revenue-lab/issues/3906) LOCAL1 범위로 유지한다. B14는 해당 정식 지원 옵션이 도착할 때 정확하게 전달하는 역할만 수행한다.

**소스 병합 ≠ Cloudflare Production 배포 ≠ 10모델 실추론 성공**. 운영 배포·Secret Store 변경·추론 비용 지출은 이 문서만으로 승인되지 않는다.
