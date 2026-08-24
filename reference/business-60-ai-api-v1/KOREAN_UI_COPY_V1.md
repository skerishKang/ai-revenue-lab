# B60 Korean UI Copy v1

Issue: #679

## Principle

B60 is Korean-first for the current product pass. Internal identifiers, enum values, route IDs, provider/model IDs, URLs, localStorage keys, and execution contracts remain unchanged. User-facing labels translate those contracts into plain Korean.

English is not mixed into the Korean primary experience. A separate English locale/version is a later task.

## Core terminology

| Internal / previous UI | Korean user-facing copy |
|---|---|
| VERIFIED_OFFICIAL_WEB | 공식 확인 완료 |
| PENDING_WEB_VERIFICATION | 추가 확인 필요 |
| OFFICIAL | 공식 확인 |
| INFO ONLY / DISCOVERY ONLY | 정보만 제공 |
| ROUTER MAPPED | 실행 경로 연결됨 |
| CONNECTABLE | 연결 가능 |
| CONNECTED | 연결됨 |
| CURRENT ACCESS | 현재 이용 조건 |
| SOURCE CONFIDENCE | 출처 신뢰도 |
| ACCESS ROUTE | 접근 경로 |
| PROVIDER | 제공사 |
| MODEL | 모델 |
| PRICE | 가격 |
| CONTEXT | 컨텍스트 |
| SAVE / SAVED | 저장 / 저장됨 |
| COMPARE / SELECTED | 비교 / 선택됨 |
| CHANGES | 변경 기록 |
| BASELINE | 기준선 |
| PENDING | 확인 중 |
| CHANGED | 변경됨 |
| OPEN SOURCE LAYER | 출처와 근거 보기 |

## Copy rules

1. Raw enum values are never intentional user-facing copy.
2. Provider/model names and exact technical IDs remain unchanged when they are identifiers.
3. Promotional claims that lack primary-source confirmation are explicitly separated as `추가 확인 필요`.
4. `정보만 제공` does not imply executable integration.
5. `실행 경로 연결됨` means an exact execution mapping exists; it does not mean a live execution target is bound.
6. Korean display headlines use relaxed line-height and `word-break: keep-all` so large Hangul does not visually collide.

## Current cinematic copy

- `현재 접근 정보 / 001`
- `확실한 것과, 확인 중인 것을 섞지 않습니다.`
- `출처와 근거 보기`
- `출처를 확인하고, 검증 상태를 구분합니다.`

## Vercel truth note

The old fixed Gateway price presentation (`$1.40/M input · $4.40/M output`) must not be presented as the route-wide GLM 5.2 price. Current user-facing wording is `라우팅 제공사별 상이`, matching the provider-dependent routed-price correction.
