# Phase 2: Multi-Provider BYOK Pilot — Runbook

## Product Locale Operations

- 기본 locale은 한국어(`ko-KR`)다.
- 한국어 문구가 제품 문구의 source of truth다.
- 영어는 선택형 보조 locale로 운영하며, 언어 전환 기능이 구현된 경우에만 사용자가 선택한다.
- 신규 기능은 한국어 문구와 검증을 먼저 완료한다.
- 영어 번역이 없는 신규 문구는 한국어로 fallback한다.
- Phase 2 운영 중 영어 문구의 완전한 동등성은 배포 차단 조건이 아니다.
- 사용자 또는 브라우저에 저장된 locale 값이 없거나 잘못되면 한국어를 사용한다.

## Environment Variables

### Multi-Provider Mode

BUSINESS14_PROVIDER_REGISTRY_JSON: Provider registry JSON string

### Legacy Single-Provider Mode (Phase 1 Compat)

BUSINESS14_PILOT_PROVIDER_ID=pilot-openai-compat
BUSINESS14_PILOT_BASE_URL=https://...
BUSINESS14_PILOT_MODEL_ID=my-model
BUSINESS14_PILOT_UPSTREAM_MODEL=upstream-model
BUSINESS14_PILOT_TIMEOUT_SECONDS=30

## Local Run

```bash
cd apps/korean-ai-platform
.venv/bin/uvicorn app.main:app --reload
```

## Testing

```bash
.venv/bin/python -m pytest -q
```

언어 전환이 구현되면 최소한 다음을 검증한다.

- 최초 접속 기본 언어가 한국어인지
- 잘못된 locale 저장값이 한국어로 fallback하는지
- 영어 선택 후 화면 전환이 가능한지
- 영어 번역이 없는 신규 문구가 빈 문자열이 아니라 한국어로 표시되는지
- Provider·모델 ID, API 경로, 오류 code 같은 기술 식별자는 번역으로 변형되지 않는지

## Fake Transport Testing

All tests use httpx.MockTransport — no external network calls.
Provider-specific fake transports verify correct routing:
- Provider A transport: receives Model A requests
- Provider B transport: receives Model B requests
- Authorization header verification for key isolation

## Troubleshooting

| Symptom | Check |
|---------|-------|
| registry_invalid | BUSINESS14_PROVIDER_REGISTRY_JSON JSON 형식, 중복 ID, URL scheme 확인 |
| model_not_found | 요청한 model_id가 registry에 존재하고 enabled=true인지 확인 |
| key isolation | 각 요청의 X-Business14-Provider-Key가 올바른 Provider에 전달되는지 MockTransport로 확인 |
| 영어가 기본으로 표시됨 | locale 기본값과 저장값 fallback이 `ko-KR`인지 확인 |
| 번역되지 않은 문구가 비어 있음 | 한국어 source 문구로 fallback하는지 확인 |

## Known Limitations

- Single upstream model per Business 14 model ID
- No DNS rebinding protection (endpoint is server-configured, not user-supplied)
- No automatic failover or load balancing
- No streaming or tool calling
- Full Korean/English localization parity is not required in Phase 2
