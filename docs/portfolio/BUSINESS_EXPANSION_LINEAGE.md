# Business Expansion / Successor Lineage

- Status: portfolio implementation-location authority for expanded and externally implemented Businesses
- Numbering authority: `docs/portfolio/BUSINESS_REGISTRY.md`
- External-development policy: `docs/operations/EXTERNAL_DEVELOPMENT_PROJECTS_POLICY.md`
- Owner decision: 2026-08-09

## Purpose

Business 번호는 아이디어와 사업 계보를 보존한다. 번호가 붙은 Business가 별도 제품·브랜드·저장소로 확장되었다고 해서 번호를 삭제하거나 재사용하지 않는다.

대신 실제 구현 위치가 외부 제품으로 승계되었으면 이 문서에 명시하고 AI Revenue Lab 내부의 중복 구현을 금지한다.

이 문서는 **번호 자체를 새로 부여하거나 변경하지 않는다.** 번호 권한은 `BUSINESS_REGISTRY.md`와 그 정식 승격 절차에 남아 있다. 이 문서는 구현 위치와 승계 관계만 통제한다.

## Machine-readable status vocabulary

- `EXPANDED_SUCCESSOR` — 기존 Business가 더 큰 독립 제품으로 확장·승계됨.
- `INTEGRATED_SUCCESSOR` — 여러 Business 아이디어가 하나의 상위 제품으로 통합됨.
- `EXTERNAL_IMPLEMENTATION` — 실제 구현 원본이 AI Revenue Lab 밖에 있음.
- `EXTERNAL_SOURCE_PENDING_LINK` — 외부 제품은 확인되지만 canonical 외부 GitHub 저장소 링크가 아직 이 문서에 확정되지 않음.
- `NO_INTERNAL_IMPLEMENTATION` — AI Revenue Lab에서 UI/UX/backend/DB/scaffold/reference placeholder를 새로 만들지 않음.

## Confirmed expansion and external implementation map

| Business | Original portfolio idea | Expansion / implementation state | Successor or implementation source | AI Revenue Lab action |
|---|---|---|---|---|
| B5 | Neighbor Market / 우리단지 이웃가게 | `EXPANDED_SUCCESSOR` + `EXTERNAL_IMPLEMENTATION` | **DanjiOn / 단지온** — `skerishKang/02-danji-on` | `NO_INTERNAL_IMPLEMENTATION`; 번호와 사업 계보만 유지 |
| B23 | LoveBud / 러브버드 | `EXTERNAL_IMPLEMENTATION` | `skerishKang/LoveBud` | `NO_INTERNAL_IMPLEMENTATION`; 목록·연결만 유지 |
| B24 | LoveTree 3.0 / 러브트리 3.0 | `EXTERNAL_IMPLEMENTATION` | `skerishKang/lovetree3.0` | `NO_INTERNAL_IMPLEMENTATION`; 목록·연결만 유지 |
| B25 | Love Matchmaking / 서사 매칭 | `EXTERNAL_IMPLEMENTATION` | `skerishKang/401-love-match-making` | `NO_INTERNAL_IMPLEMENTATION`; 목록·연결만 유지 |
| B26 + B28 + B50 | Company Memory + Decision Archive + Private Data Connector Hub | `INTEGRATED_SUCCESSOR` + `EXTERNAL_SOURCE_PENDING_LINK` | **이어온** — PADIEM 기업 온톨로지/조직기억 제품 | 세 아이디어의 번호·계보 보존; 별도 내부 구현 금지 |
| B27 + B31 | Evidence Studio + Public Procedure Experience Data | `INTEGRATED_SUCCESSOR` + `EXTERNAL_SOURCE_PENDING_LINK` | **사실로** — PADIEM 사실·증거·절차 업무지원 제품 | 두 아이디어의 번호·계보 보존; 별도 내부 구현 금지 |
| B30 | Civic AI Navigator / 시민 AI 내비게이터 | `EXTERNAL_IMPLEMENTATION` | **400-ai-finder** — `skerishKang/400-ai-finder` | `NO_INTERNAL_IMPLEMENTATION`; 실제 구현은 외부 저장소에서 계속 |

### B30과 사실로의 경계

B30의 실제 시민·기관 홈페이지 탐색 구현은 `skerishKang/400-ai-finder`를 원본으로 본다. 사실로가 공식서식·절차 탐색 기능을 활용하거나 확장하더라도 B30 자체를 사실로에 흡수된 것으로 간주하여 400-ai-finder를 대체하지 않는다.

즉:

```text
B30 primary implementation = 400-ai-finder
사실로 = B30 계열의 공공 탐색 능력을 활용할 수 있는 별도 상위 제품
```

## B5 / 단지온 승계 결정

B5는 삭제하지 않는다.

```text
B5 Neighbor Market / 우리단지 이웃가게
→ 아이디어·사업번호·사업계보 유지
→ 단지온으로 확장·승계
→ 실제 제품 개발은 skerishKang/02-danji-on
→ AI Revenue Lab 내부 apps/neighbor-market 신규 구현 금지
→ reference/business-* placeholder 또는 별도 backend scaffold 생성 금지
```

`BUSINESS_REGISTRY.md`의 B5 번호 매핑은 계속 유효하다. 다만 구현 위치 판단에서는 이 승계 기록을 우선하여, 과거의 `planned, not yet created` 문구를 새 구현 지시로 해석하지 않는다.

## AI worker hard stop

아래 상태 중 하나가 붙은 Business를 발견하면 새 구현을 시작하지 않는다.

```text
EXPANDED_SUCCESSOR
INTEGRATED_SUCCESSOR
EXTERNAL_IMPLEMENTATION
NO_INTERNAL_IMPLEMENTATION
```

작업자는 다음만 수행할 수 있다.

1. 번호·계보·상태·외부 source 링크 갱신
2. 외부 source의 현재 상태 확인
3. 사용자가 해당 외부 프로젝트 작업을 요청한 경우 그 외부 source of truth에서 작업
4. 명시적인 source migration 결정이 있을 때만 AI Revenue Lab 내부 이전 제안

`apps/`, `reference/`, UI, UX, backend, Auth, DB, CI, 배포 placeholder를 만들어서는 안 된다.

## Number preservation rule

확장은 성공적인 사업 진화로 기록한다.

- 원래 Business 번호 삭제 금지
- 빈 번호로 재사용 금지
- successor product가 생겨도 원래 아이디어명 보존
- 하나의 successor에 여러 Business가 합쳐져도 각 번호의 계보 보존
- 외부 제품이 다시 이름을 바꾸면 이전 이름 → 현재 이름의 lineage를 추가 기록

이 방식으로 AI Revenue Lab은 아이디어의 역사와 실제 제품화 성과를 동시에 보존한다.
