# Phase 2: Multi-Provider BYOK Model Routing Pilot — Charter

## Product Objective

Phase 1의 단일 Provider BYOK Gateway를 여러 Provider와 모델을 지원하는 결정론적 라우팅 파일럿으로 확장한다.

고객은 호출할 모델을 선택하고 하나의 Business 14 요청 규격을 사용한다. Business 14는 서버에 등록된 Provider·모델 매핑에 따라 요청을 정확한 upstream으로 전달한다.

## BYOK Decision

Phase 2도 BYOK를 유지한다:
- Provider 재판매 계약 불필요
- Business 14의 선결제 크레딧 불필요
- GPU 구매 불필요
- 고객의 기존 Provider 계정 활용

## Phase 2 Promise

> 여러 AI Provider의 모델을 하나의 모델 목록과 하나의 요청 형식으로 선택해 호출할 수 있습니다.

## In Scope

- server-configured multi-provider registry (JSON env var)
- provider-to-model mapping with validation
- deterministic model routing (model_id → RouteTarget)
- request-scoped BYOK key forwarding (key isolation across providers)
- aggregated model catalog with provider metadata
- provider health/configuration summary
- Korean multi-provider pilot UI
- network-free integration tests with multiple fake upstreams
- Phase 0 and Phase 1 backward compatibility

## Non-Goals

- API key storage
- customer accounts or authentication
- billing or credit sales
- automatic failover
- load balancing
- streaming
- tool calling
- image/audio generation
- native vendor-specific protocol adapters
- production SLA
- DNS rebinding protection

## Phase 1 Compatibility

설정 우선순위:
1. BUSINESS14_PROVIDER_REGISTRY_JSON이 유효하면 registry 사용
2. registry가 없으면 Phase 1 단일 Provider 설정(BUSINESS14_PILOT_*) 사용
3. 둘 다 없으면 not_configured
