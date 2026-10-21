# B14 Free 모델 배포 — 저장소 전체 상태 기록 (2026-10-18)

> STATUS: **PARTIAL / Production 배포 확인, 인증 사용자 Free 응답 미검증**
>
> 범위: B14, B62 Chat, B54 Claw, B66, P01/AI Engine, 공통 Control Plane, 운영 배포.
> 이 문서는 공개 가능한 기술 상태만 기록합니다. 비공개 사업방침/인증정보는 포함하지 않습니다.

> **2026-10-21 정합화 안내:** 이 문서는 2026-10-18 상태 기록이며 아래 등급표는 그 시점의 값입니다. 이후 Free 등급의 기본 라우트는 `google/gemini-3.1-flash-lite`로 바뀌었고(`google/gemma-4-26b-a4b-it`이 1순위 폴백), Plus/Pro/Max의 제품 라우트는 Muse Spark 1.3으로 유지됩니다. 현재 계약의 권위는 [B14 Free route 결정(2026-10-20)](B14_FREE_ROUTE_20261020.md)와 [Control Plane 제품 등급 라우트](../../packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py)이며, B14 등록 상태의 권위는 [단일 레지스트리](B14_MODEL_REGISTRY_SINGLE_SOURCE.md)입니다.

## 대표 확정 모델 라우팅 (2026-10-18 시점)

| 등급 | 기본 | 순서가 정해진 폴백 |
| --- | --- | --- |
| Free | `opencode-go/beam-free` | `opencode-go/longcat-2.5-preview-free` → `google/gemini-3.1-flash-lite` → `google/gemma-4-26b-a4b-it` |
| Plus | Beam Free | LongCat Free → Gemini 3.5 Flash-Lite → Gemma 4 31B |
| Pro | Beam Free | LongCat Free → Gemma 4 31B |
| Max | Beam Free | LongCat Free → Muse Spark 1.3 Contributor |

자동 폴백은 공급사 제한(429), 서버 오류(5xx), 타임아웃 등 기존 복구 가능 오류에서 정해진 순서로만 시도합니다. 제품 회원 등급은 신뢰된 서버 검증값을 사용합니다. `b14/auto`의 과거 범용 라우팅과 구분합니다.

## 확인된 실행 이력

- [PR #4983](https://github.com/skerishKang/ai-revenue-lab/pull/4983) 병합. 관련 구현: `apps/korean-ai-platform`, `packages/padiem-control-plane`, `apps/padiem-chat` 테스트. PR 병합 자체와 운영 배포는 다른 단계입니다.
- COM2 격리 B14 후보에서 Beam Free 및 LongCat Free 단건 텍스트 추론을 각각 HTTP 200으로 확인한 이전 CENTRAL 실행 기록이 있습니다. 이는 운영 사용자 Free 체인 E2E 증명이 아닙니다.
- LOCAL 보고: B14 Production Deploy Gate run `39077044833`, exact-main `1443143ce2cdb31d8d0807f23fc80bb4a6de33c6`, 배포 버전 `abdf04cb-dea9-42bc-a147-078e203506d8`. `POST_DEPLOY_VERSION_AT_100`, `ENGINE_B14_BOUND_SMOKE`, `B14_OWNER_JSON_CATALOG_PARITY` PASS; Production 모델 목록에 Free 체인 4개 확인.
- LOCAL 보고: B62 코드 릴리스는 같은 main SHA로 완료되어 별도 재배포하지 않음. 배포 전 버전 `83aae188-8fc8-4b75-ae45-54fe605b543c` 롤백 앵커 확보, 롤백 미실행.
- LOCAL 보고: COM2 기존 `18717` 릴리스는 아직 교체하지 않음. 다른 로컬 후보 포트는 그대로 유지.

## 제품/계층별 현재 판정

| 계층 | 확인 내용 | 미확인/남은 내용 |
| --- | --- | --- |
| 공통 Control Plane | 4개 등급 기본·순차 폴백 선언 병합 | 운영 회원등급을 거친 사용자 E2E |
| B14 라우터 | 배포 및 Free 4개 카탈로그/등록 확인(LOCAL 보고) | 실제 운영 Beam 완료/LongCat 자동 폴백 실행 증빙 |
| B62 Chat | 해당 main SHA 코드 릴리스(LOCAL 보고) | 로그인한 Free 사용자 `/api/chat/stream` 성공 |
| B54 Claw | 공유 모델/등급 정책 및 관련 코드 영향 범위 | 정식 Claw 사용자 인증·모델 실행 E2E |
| P01/AI Engine | 배포 게이트의 엔진↔B14 연계 smoke PASS(LOCAL 보고) | 실제 Claw 업무 대화 모델·응답 증빙 |
| B66 | 공통 B14 카탈로그/모델 선택 경계에 영향 가능 | B66 전용 exact model 선택 동작 별도 확인. 이번 모델 Free 전환을 B66 직접 선택 모델에 강제하지 않음 |
| COM2 로컬 B14 | 별도 후보 Beam/LongCat 단건 성공 | 기존 18717 교체 보류 |

## 확인된 운영 장애와 진단 경계

- 사용자가 2026-10-18에 제공한 Chat 화면/개발자 콘솔에서 `/api/chat/stream` HTTP **502** 두 건과 '답변을 불러오지 못했습니다' 표시가 관찰됐습니다.
- 이 화면만으로 Beam 공급사 장애, B14 라우팅 실패, B62 SSE 파싱 또는 폴백 실패 중 원인을 특정할 수 없습니다. Tabbit 확장 로그와 B62 502의 인과관계도 확인되지 않았습니다.
- LOCAL 보고: 무인증 `POST /api/claw/manual-intake/execute`는 `403 canonical_b54_session_unavailable`로 모델 디스패치 전에 거부됨. 이 **Claw 전용 인증 경로**의 403을 Chat `/api/chat/stream` 502 원인으로 동일시하지 않습니다.
- GitHub CI에서 B14 Alpha/Worker 번들 성공 이력이 있으나, 일부 Control Plane MeshCentral FakePort, B62 SSE/grounding 및 다른 기능 테스트 실패 이력도 있습니다. 전체 CI PASS로 보고하지 않습니다.

## 후속 실행 범위 (현재 문서·이슈 정합화만 진행)

1. 인증된 운영 Free 사용자 요청 1회에서 B62→B14 `request_id`/모델/결과를 대조하여 502 최초 실패 지점을 확정.
2. Beam 실패 시 LongCat → 3.1 Flash-Lite → Gemma 26B 순서가 실제 유지되는지 복구 가능한 오류의 bounded evidence 확인.
3. B54 Claw·P01, B66 관련 회귀를 각각 제품 경계 내에서 점검. 동일 인증 경로라고 가정하지 않음.
4. 운영 성공 증거 확보 후 COM2 `18717` 교체 여부 판단. 롤백 앵커 보존.

**운영 재배포·로컬 파일 수정·서비스 재기동은 이 문서 업데이트에서 수행하지 않았습니다.** 관련 이슈: [#1397](https://github.com/skerishKang/ai-revenue-lab/issues/1397), [#4317](https://github.com/skerishKang/ai-revenue-lab/issues/4317), [#4318](https://github.com/skerishKang/ai-revenue-lab/issues/4318), [#4483](https://github.com/skerishKang/ai-revenue-lab/issues/4483), [#4316](https://github.com/skerishKang/ai-revenue-lab/issues/4316).
