# Product Contract

## Identity

```text
Business 14
Korean AI Platform
한국형 AI 모델 플랫폼
```

## Target user

A Korean individual developer, freelancer, student or indie maker who uses more than one AI model and wants one understandable entry point before considering team or enterprise controls.

## Painful moment

The user currently has to visit several AI companies, understand incompatible model names and prices, manage multiple keys, and repeatedly change integration settings.

## Changed outcome

The user can discover an appropriate model, connect only the required Provider key, test the model, understand the selected route, and copy one endpoint and code example without first learning gateway administration.

## Primary promise

> 목적을 고르면 맞는 AI 경로가 보이고, 키를 연결하면 바로 시험할 수 있습니다.

## Product hierarchy

1. Make the first useful request.
2. Understand which model and Provider handled it.
3. Copy an endpoint or code example.
4. Explore alternatives and compare evidence.
5. Review personal activity and cost.

## Public product boundary

Business 14 owns model access, Provider connections, BYOK, model discovery, routing evidence, API keys, usage and an OpenAI-compatible endpoint.

Business 54 later consumes Business 14 as a terminal coding agent. It does not duplicate the Provider or Router layer.

## Visual metaphor

A personal switchboard. A single request travels through visible eligibility and preference stages to one selected route.

## Top-level navigation

```text
시작
모델
활동
개발자
```

Provider keys and account settings are contextual controls, not permanent primary navigation.

## Core visual states

- first request;
- model explorer;
- model detail/playground;
- Provider key connection;
- automatic route decision;
- no-safe-route recovery;
- personal activity;
- mobile equivalents.

## Truth boundary

All content and state transitions in this reference are synthetic. Cost, latency and route quality values are visibly identified by evidence labels such as `설정값`, `최근 측정`, or `확인 불가`.

## Explicit non-goals

- live Router Core;
- real Provider calls;
- secret persistence;
- authentication;
- platform credits;
- organization controls;
- government controls;
- Business 54 TUI;
- Production deployment.