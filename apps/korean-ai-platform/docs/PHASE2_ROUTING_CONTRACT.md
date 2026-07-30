# Phase 2: Provider Registry & Routing Contract

## Registry Format

BUSINESS14_PROVIDER_REGISTRY_JSON 환경변수에 JSON 배열로 설정:

```json
[
  {
    "provider_id": "provider-a",
    "display_name": "Provider A",
    "base_url": "https://api.provider-a.example.com",
    "timeout_seconds": 30,
    "models": [
      {
        "model_id": "b14-model-a",
        "upstream_model": "upstream-model-a",
        "display_name": "Model A",
        "enabled": true
      }
    ]
  }
]
```

## Validation Rules

- provider_id 중복 금지
- model_id 전체 registry에서 중복 금지
- 빈 provider_id/model_id/upstream_model 금지
- base_url은 https://만 허용
- URL credential(username/password) 금지
- fragment 금지
- loopback/private/link-local IP 금지
- timeout_seconds: 1~120
- enabled model이 최소 1개 이상 필요

## Routing Rules

- 요청의 `model` 값을 registry의 Business 14 model_id와 매칭
- 매칭된 model의 provider_id로 RouteTarget 결정
- RouteTarget: {provider_id, provider_name, model_id, upstream_model, base_url, timeout_seconds}
- 모호한 매핑(동일 model_id가 여러 Provider)은 registry 초기화 시 차단
- 알 수 없는 model_id → model_not_found 오류
- disabled model → model_not_found 오류

## Key Isolation

- X-Business14-Provider-Key 헤더로 key 전달
- 한 요청의 key는 해당 요청의 RouteTarget Provider에만 전달
- 다른 Provider로 key 누출 금지
- key 저장·로그·응답 반사 금지
