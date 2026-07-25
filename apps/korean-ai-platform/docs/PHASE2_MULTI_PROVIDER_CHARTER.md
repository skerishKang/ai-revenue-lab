# Phase 2: Multi-Provider BYOK Model Routing Pilot — Charter

## Product Objective

Phase 1의 단일 Provider BYOK Gateway를 여러 Provider와 모델을 지원하는 결정론적 라우팅 파일럿으로 확장한다.

고객은 호출할 모델을 선택하고 하나의 Business 14 요청 규격을 사용한다. Business 14는 서버에 등록된 Provider·모델 매핑에 따라 요청을 정확한 upstream으로 전달한다.

Business 14는 한국 시장에서 사용할 수 있는 독립적인 AI Provider 계층이 부족하다는 문제를 해결하기 위한 제품이다. 국내 사용자·기업·기관이 국내외 AI 모델을 한국어 중심의 인터페이스, 운영 기준, 비용 안내, 보안 설명 아래에서 사용할 수 있도록 하는 것이 제품의 기준 방향이다.

## Market and Language Direction

- 1차 목표 시장은 대한민국이다.
- 제품 문구와 UX의 원본 언어는 한국어(`ko-KR`)다.
- 기본 화면 언어는 한국어로 설계한다.
- 영어는 해외 Provider 관계자와 외국인 개발자를 위한 선택형 보조 언어로 제공할 수 있다.
- 신규 기능, 오류 메시지, 도움말, 정책 설명은 한국어를 먼저 완성한다.
- 영어 번역은 한국어 원본을 기준으로 후속 보강하며, Phase 2에서 모든 영어 문구를 동시에 확장할 필요는 없다.
- 영어 번역이 아직 없는 문구는 한국어로 안전하게 fallback할 수 있다.
- 이 Korea-first 원칙은 현재 사용자가 제한적이어서 정한 임시 방침이 아니라 제품의 시장 정의다.

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
- Korean-first multi-provider pilot UI
- optional English locale without requiring simultaneous English expansion
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
- full English localization parity in Phase 2

## Phase 1 Compatibility

설정 우선순위:
1. BUSINESS14_PROVIDER_REGISTRY_JSON이 유효하면 registry 사용
2. registry가 없으면 Phase 1 단일 Provider 설정(BUSINESS14_PILOT_*) 사용
3. 둘 다 없으면 not_configured
