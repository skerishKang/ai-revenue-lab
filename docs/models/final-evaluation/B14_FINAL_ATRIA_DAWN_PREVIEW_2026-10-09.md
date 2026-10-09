# B14 신규 독립 최종 평가 — Atria Dawn Preview

**독립 라운드:** `B14_FINAL_MODEL_EVALUATION_2026-10-09`
**평가일:** 2026-10-09 (KST)
**B14 exact 모델:** `atria/Atria-Dawn-Preview`
**제공자 exact 모델:** `Atria-Dawn-Preview`
**종합 판정:** **IN_PROGRESS / DIRECT_LATENCY_UNSTABLE / B14_PREFLIGHT_HTTP403 / F6_NOT_TESTED** — 미승인·고객 Production 미검증.

**상태 업데이트(2026-10-09): PRODUCTION_B14_STREAM_PREVIEW_QUOTE_PASS / STANDARD_QUOTE_UPSTREAM_TIMEOUT / F6_NOT_TESTED** — 기본 클라이언트 UA 403은 Cloudflare Error1010, 별도 제공자 응답 아님. 현재 B14 대화 HTTP200 및 수동 스트리밍 Preview 견적 HTTP200 확인. 기본 비스트리밍 QKR001은 HTTP504.

## F1 — 공식 모델 능력

출처: [Atria 개발자 공식 문서](https://api.atria-asi.ai/docs), [모델 공식 카드](https://huggingface.co/internlm/Atria-Dawn-Preview).

| 항목 | 검증값 |
|---|---|
| 공식 upstream API | `https://api.atria-asi.ai/v1/chat/completions` |
| 공식 exact upstream model ID | `Atria-Dawn-Preview` (대소문자 구분) |
| 입력 컨텍스트 | **256K tokens** |
| 요청 출력 토큰 범위 | **1–65,536** |
| 입력 유형 | 텍스트. 이미지 및 PDF 원문을 그대로 입력할 수 있다고 판단하지 않음 |
| 지원 API | Chat Completions, Messages, Responses; 비스트리밍/스트리밍 |
| 추론 | 공식 카드에 reasoning effort 후보값 언급. 그러나 현재 API의 `reasoning_effort=none` 실제 호출은 HTTP422로 거부됨. 요청 오류 원문은 저장하지 않았으므로 지원 모드·원인은 **UNKNOWN** |

이론적 출력 상한과 B14 자체 명시적 요청 상한 4,096은 별개다. 평가에서는 비스트리밍/스트리밍 기본 `max_tokens=1800`, 인사 700을 사용했다.

## F2 — 실제 사용 계정 / B14 연결

- 현재 canonical B14 JSON에 `atria/Atria-Dawn-Preview` enabled, provider `atria` enabled, upstream `Atria-Dawn-Preview`, 고정 HTTPS URL이 공식 API와 일치.
- 로컬 OpenCode의 Atria 제공자에 API key 필드와 정확한 baseURL이 존재한다는 사실만 확인. 값·계정 ID·비밀을 로그나 Git에 저장하지 않았다.
- **로컬 실제 API 응답 헤더**: `x-rpm-limit: 50`, `x-rpm-remaining: 49` — 이번 인사 성공 직후 한 번 관찰한 **로컬 계정** 한도. B14 운영 Secret에 적용되는 한도로 일반화하지 않는다.
- 실제 계정 TPM, RPD, 플랜 및 잔여 크레딧: **UNKNOWN**.
- B14 Production `GET /api/pilot/health` 및 `GET /api/pilot/models`: **둘 다 HTTP403**. 운영의 정확한 등록·인증 준비도 preflight가 확보되지 않아 **B14 provider POST 0회**, B14 경유 성능·응답을 측정하지 않았다.
- **금지:** 이 403을 Atria upstream 403 또는 모델 불합격이라고 단정하지 않는다.

## F3 — 파라미터 / 추론

- B14 source 허용값: `messages`, `temperature`, `max_tokens` 등, 명시적 `reasoning_effort`는 현행 generic adapter에서 제공자 POST에 전달되지 않음.
- 직접 API 기본값 `temperature=0`, `max_tokens=1800`, reasoning 미지정으로 견적 측정.
- `QKR-002` 스트리밍 `reasoning_effort=none` 추가 1회: **HTTP422 (1,093ms)**. 원본 오류가 보존되지 않았으므로 `none` 값·요청 형식·계정 설정 중 무엇이 거부됐는지 미확정. 추론 On/Off 수준별 성공·정확도 수치를 꾸며내지 않는다.
- 다른 사용자 모델로의 자동 선택이나 대체는 한 번도 사용하지 않음.

## F4–F5 — 신규 합성 견적서 실측

이번 라운드 고정 `QKR-001..010`와 공통 `PROMPT_HEADER`; 단일 모델 고정, no retry, no fallback. 응답이 완료된 경우에만 B66 정규화 및 정확도 검사를 수행한다.

| 입력/호출 형태 | 실제 HTTP | 완료 | 견적 채점 | 지연 |
|---|---|---|---|---:|
| 짧은 일반 대화, non-stream | **200** | 성공, 정상 답변 | 견적 채점 대상 아님 | **17,859ms** |
| QKR-001, non-stream | 응답 없음 | **TimeoutError** | UNAVAILABLE | **50,328ms** |
| QKR-001, stream | **200** | 완료, 첫 조각 27,031ms | **엄격 PASS** | **31,625ms** |
| QKR-002, stream | **200** | **65초 내 미완료**, 첫 조각 59,204ms | UNAVAILABLE | **65,000ms** |
| QKR-002, stream + reasoning none | **422** | 요청 거부 | UNAVAILABLE, 원인 미확정 | **1,093ms** |
| QKR-003~010 | 미호출 | NOT_TESTED | NOT_TESTED | — |

- 실측된 **엄격 견적 정확도는 완전한 답변을 받은 QKR-001 1건에서만 1/1**이며, 10문항 전체 정확도 10/10이라고 주장하지 않는다.
- QKR-001에서 비스트리밍 50초 타임아웃, 스트리밍 31.6초 PASS가 교차했다. **스트리밍은 일부 요청에서 도움이 되지만 보편적 해결책은 아님**. QKR-002는 스트리밍에서도 65초 미완료.
- 안전 중단: QKR-002 스트리밍 미완료 후 잔여 문항 자동 실행하지 않음. reasoning none은 범위 제한 1회만 검증하고 422로 종료.
- 총 실제 direct POST **5회**(인사 1 + QKR001 비스트림 1 + QKR001 스트림 1 + QKR002 스트림 1 + QKR002 추론 none 1); 실패가 발생한 요청에 재시도 정책 적용하지 않았으며 각 설정 변경은 별도의 단일 시험으로 기록.
- 모델 API 응답의 정상적인 형식과 응답 안정성을 구분한다. 실제 응답의 정확한 범주 외 본문/개인정보는 Git에 포함하지 않는다.

## F6 — 모델 실제 추출 → QuoteCore → 최종 PDF

**NOT_TESTED**. 필수 12품목 QKR-008의 Atria 실제 응답이 없기 때문에 다른 모델이 생성한 PDF·품목을 이 모델의 결과로 대체하지 않는다. 고객 저장 양식/최종 PDF 다운로드도 미검증.

## 현재 판단과 다음 승인 관문

- **현재 판정: `IN_PROGRESS / DIRECT_LATENCY_UNSTABLE / B14_PREFLIGHT_HTTP403`.** 고객 운영용 합격 근거가 부족하므로 `FINAL_PASS` 금지.
- Atria 성능에 대해 **일부 실측에서는 추출이 정확하지만 응답 지연이 크고 완료되지 않는 사례가 있다**는 사실만 확정.
- 다음 평가 조건: B14 GET 403 별도 해결 및 exact-model 서비스 준비 확인 → 모델 최대 지연/출력 예산 정의 → 제공자 공식 reasoning 파라미터/지원 여부 확인 → 허용된 안정성 예산 하에 나머지 QKR·실제 12품목 PDF E2E. 반복 타임아웃에 대해 무한 재시도 금지.

로컬 메타데이터 증거(비공개, 원문·키 없음):
- `E:\\b14-atria-dawn-DIRECT-10QKR-20261009.json`
- `E:\\b14-atria-dawn-STREAM-QKR001-20261009.json`
- `E:\\b14-atria-dawn-STREAM-QKR002-010-20261009.json` (첫 QKR-002에서 중단)
- `E:\\b14-atria-dawn-REASONING-NONE-QKR002-20261009.json`

Owner 모델 선택 원칙 유지: 사용자 명시 선택, 자동 fallback 없음, 운영 등록부·서비스 배포 미변경.

## 2026-10-09 B14 Production 실호출 검증

- `PADIEM-Source-Eval/1.0` UA로 B14 GET health/models HTTP200, 등록 모델/Worker Secret 존재 확인. 앞선 GET403은 Cloudflare **Error1010 / browser_signature_banned**, **Atria 모델 403 아님**.
- 운영 B14 `atria/Atria-Dawn-Preview` 수동 선택 짧은 대화 **HTTP200 / 6,078ms**, route identity PASS, attempt 1, fallback false.
- 운영 B14 표준 `POST /api/pilot/v1/chat/completions` QKR-001 **HTTP504 / `upstream_timeout` / 10,563ms**, 내용 미채점.
- 운영 B14 별도 `/api/pilot/v1/chat/completions/stream-preview` QKR-001 **HTTP200 / 50,640ms / 첫 조각 43,531ms / 종료 [DONE] / 엄격 견적 PASS / selected route PASS / attempt 1 / fallback false**.
- **Preview-only API**로서 고객 UI 기본 채팅의 스트리밍 연동·응답시간 SLA 충족·최종 PDF E2E는 여전히 NOT_TESTED. 일반 모델 호출의 504는 해결되지 않았다.
- **현재 판정: LIVE_STREAMING_SAMPLE_PASS / STANDARD_REQUEST_TIMEOUT_UNRESOLVED / FINAL_APPROVAL_NOT_YET**.
