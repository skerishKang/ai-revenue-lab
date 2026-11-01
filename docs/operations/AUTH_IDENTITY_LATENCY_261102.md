# 로그인·로그인 유지 갱신의 계정 확인(identity) 대기 구조 (#6612)

근거: 11-02 컴2 저널 2라운드 실측 — `/api/auth/password/login` 9,511ms 중 identity
6,721ms, `/auth/shared/refresh` 중앙 5,299ms 중 identity 1,965ms.

이 문서는 **대기 구조의 확정**과 **후보별 판정**만 담는다. 제품 코드는 바꾸지 않았다
(아래 3절의 각 후보가 기존 보안 불변식과 충돌한다). 측정 스크립트:
`scripts/dev/benchmark_auth_identity_261102.py`(의존 RPC 1회 120ms 합성).

## 1. 대기 구조 (파일:줄)

### `POST /api/auth/password/login` — identity RPC 6회, 전부 직렬
| # | 단계 | 위치 |
|---|---|---|
| 0 | 자격 조회(로컬 DB, identity 아님) | `apps/padiem-chat/app/auth_routes.py:869` |
| 0 | PBKDF2 비밀번호 검증(CPU, identity 아님) | `auth_routes.py:876` → `password_auth.verify_password_async` |
| 1 | B62 `resolve_or_create_product_link` | `auth_routes.py:924` → `app/control_plane_identity.py:167` |
| 2 | B62 `resolve_active_memberships` (+ 0건이면 `create_tenant`·`assign_tenant_membership`) | `control_plane_identity.py:205-226` |
| 3 | B62 `establish_auth_session` | `control_plane_identity.py:241` |
| 3' | D1 shadow 쓰기(로컬 DB) | `auth_routes.py:386` |
| 4 | B54 `resolve_or_create_product_link` | `auth_routes.py:939` → `packages/padiem-control-plane/padiem_control_plane/b54_identity_bridge.py:347` |
| 5 | B54 `resolve_active_memberships` (+ 0건이면 생성·배정) | `b54_identity_bridge.py:381` → `:446` |
| 6 | B54 `establish_auth_session` | `b54_identity_bridge.py:386` |
| 6' | LoveTree 핸드오프(로컬 DB) | `auth_routes.py:942` → `lovetree_auth_routes.py:261` |

PBKDF2 반복은 identity 구간에 섞여 있지 않다. identity 시간은 위 6개 RPC의 합이고,
6,721ms ÷ 6 ≈ 1.1초/RPC다.

### `POST /auth/shared/refresh` — identity RPC 0~1회
| 순서 | 단계 | 위치 |
|---|---|---|
| 1 | access 쿠키 서명 검증(ES256, 스레드) | `shared_login_flow.py:206` → `shared_auth_adapter.py:44` |
| 2 | authority 교환(외부 네트워크, identity 아님) | `shared_login_flow.py:218` |
| 3 | `resolve_account` → 세션 캐시 조회(세션키별) | `shared_auth_adapter.py:56` |
| 4 | 세션키 미스 → 계정 연결 캐시(#6573) 조회 | `auth_validation_cache.py:116` |
| 5 | 연결 행도 미스면 역조회 RPC 1회 | `shared_auth_adapter.py:60` |

**결론: refresh는 이미 #6573 계정 연결 캐시를 쓰고 있다**(`get_or_load_account_link`,
기본 600초 = `PADIEM_CHAT_SHARED_LINK_CACHE_SECONDS`, `local_cpython.py:294-298`).
남은 identity 비용은 (a) 연결 행이 만료된 계정의 다음 갱신 1회, (b) 세션키가 매번 새로
생겨 세션 캐시 행을 매번 INSERT 하는 쓰기다. 1,965ms 중앙값은 캐시가 아니라 **그 요청이
연결 행 만료 경계에 걸렸거나 역조회가 반복되는 경로**가 있다는 뜻이므로, 다음 조각은
운영 로그로 `account_link_cache` 적중률을 먼저 재야 한다(추측으로 코드를 더 고치지 않는다).

## 2. 같은 요청 안의 중복
- `resolve_active_memberships`가 **같은 canonical subject**로 두 번(B62 1회, B54 1회).
  단, B62는 0건일 때 개인 테넌트를 만들고 B54도 0건일 때 만든다 — 즉 같은 조회이면서
  **쓰기를 동반**한다.
- `resolve_or_create_product_link`는 제품이 달라(b62 / b54-padiem-claw) 중복이 아니다.
- 비밀번호 자격 조회·shadow 쓰기·LoveTree 바인딩은 로컬 DB라 identity가 아니다.

## 3. 후보별 판정 (안전하지 않아 이번에 하지 않음)
| 후보 | 기대 | 막힌 이유 |
|---|---|---|
| B62 ∥ B54 전체 병렬 | 6 RPC → 3 라운드 (737→380ms, 아래 4절) | 첫 로그인에서 양쪽이 membership 0을 보고 **각자 개인 테넌트 생성·배정** → subject가 다중 멤버십이 되어 다음 로그인부터 `ambiguous` 거부 |
| B62가 확인한 테넌트를 B54에 전달 | 1 RPC 절감 | **리뷰 불변식 위반**: `tests/test_identity_b54_canonical_session_bridge.py::test_bridge_takes_no_caller_tenant_product_subject_or_session_input`, `apps/padiem-chat/tests/test_b54_canonical_session_producer.py::test_callsite_signature_exposes_no_identity_lever`가 "호출자가 준 테넌트는 브리지에 들어오지 않는다"를 시그니처로 고정. 이 세션에서 시도했다가 두 시험 실패로 확인하고 되돌렸다(기대값 약화 금지) |
| 요청 범위 membership 메모 | 1 RPC 절감 + 병렬 가능 | 브리지가 `app.state.control_plane_identity_authority`를 직접 읽으므로 요청 프록시 주입이 필요하고, 테넌트 생성 시 메모 무효화 규칙을 함께 설계해야 한다 — **규격 변경이라 CTO 승인 필요** |

## 4. 벤치 (합성 의존 RPC 120ms, 실제 브리지 함수 사용, 5회 평균)
| 모양 | RPC | 평균 | p50 |
|---|---|---|---|
| 오늘(직렬) | 6 | 736.9ms | 740.1ms |
| 두 제품 병렬 | 6 | 380.2ms | 379.5ms |
| 병렬 + membership 메모 | 6(1회 무료) | 376.0ms | 379.4ms |

즉 **2.0배**가 이 구간의 상한이다. 6,721ms에 그대로 대입하면 약 3.5초가 남고, 나머지는
RPC 자체 지연이다.

## 5. 손대지 않은 보안 설정
PBKDF2 반복 횟수·해시 방식, 로그인 실패 한도/잠금(`_PASSWORD_FAILURE_LIMIT`,
`_password_lock_minutes`), abuse 게이트, 세션 발급·만료(`session_max_age_seconds`),
쿠키 속성, 계정 연결 캐시의 무효화 규칙(#6573) — 모두 그대로다.

## 6. 다음 조각(제안)
1. CTO가 위 3절의 "요청 범위 메모" 규격을 승인하면, B62·B54 병렬 + 메모로 identity를
   약 3.5초 줄인다. 첫 로그인 테넌트 생성은 B62 단계로 직렬 유지(레이스 제거).
2. refresh는 코드 변경 전에 컴2 로그로 연결 캐시 적중률부터 확인한다.
