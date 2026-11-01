# P01 COM2 identity/entitlement 연결 — CTO PR 본문용

## 문제와 변경 결과

컴2 Chat이 제품 내부 `usr_*`를 canonical subject로 바꾸지 않고 P01에 보내서, 원격 admission의 identity 역조회가 `engine_entitlement_identity_unavailable`로 실패했다. P01은 이를 `503 entitlement_unavailable`로 반환했고 B14에는 도달하지 않았다.

Cloudflare Chat은 `worker.py`에서 identity adapter와 canonical resolver를 orchestration에 연결한다. 컴2 `local_cpython.compose_host_orchestration`에는 그 resolver 전달이 없었다. 별도로 Cloudflare P01의 `worker_identity.py`는 `CONTROL_PLANE_IDENTITY.resolve_auth_session`으로 세션 범위를 조회하지만 컴2 `_local_bindings`에는 해당 바인딩이 없었다.

**P01 identity 바인딩만 추가해도 일반 orchestration의 entitlement 오류가 고쳐지는 것은 아니다.** 일반 admission은 `CONTROL_PLANE_ENGINE_ADMISSION`에 subject를 전달하며, entitlement producer가 쓰는 identity는 admission Worker 자신의 `CONTROL_PLANE_IDENTITY`다.

- Chat: 기존 `CloudflareControlPlaneIdentityAuthority`의 `resolve_current_auth_session(product_id, product_user_id)`로 활성 b62 USER 세션을 읽고 기존 canonical orchestration bridge에 subject를 전달한다. 이 RPC는 admission producer도 사용하는 기존 권위다. 제품 내 이력 소유자는 기존 `usr_*` 그대로다.
- 공유 로그인은 shadow 행을 만들지 않으므로 orchestration에서 shadow 행을 새 전제조건으로 요구하지 않는다. legacy 로그인에는 기존 typed authority와 `D1IdentityShadowStore`를 연결한다. 세션·subject·entitlement를 임의 생성하거나 만료를 연장하지 않는다.
- P01: 기존 `local_admission_binding.HttpsAdmissionBinding`의 HTTPS/v2 전송을 재사용하는 세션 읽기 adapter를 `CONTROL_PLANE_IDENTITY`에 연결한다. `POST /internal/rpc/resolve_auth_session`, 서명된 `x-padiem-service-id`를 사용한다. 새 인증 규약·키·저장소·권한 부여는 없다.
- 비어 있거나 잘못된 설정, 만료·취소·제품 불일치 세션, 잘못된 서명은 거부한다. 응답 원문·비밀·환경값을 로그에 추가하지 않는다.

## 통합 범위

최종 기준 main: `8ccfb672b5fdb807e288bd2cdd9c3a800db0aadd`.

`#6427`의 P01 admission HTTPS/v2 코드는 `#6423`으로 이미 main에 들어와 있다. 처음에는 아래 3개 고유 커밋을 재적용했고, 작업 중 `#6424`가 병합된 것을 확인해 그 두 커밋을 제거하고 최신 main 위로 옮겼다. 최종 diff에는 아직 열린 `#6427`의 Chat broker v2 변경과 이번 identity 연결 수정만 남는다. CTO는 이 통합 diff를 한 PR로 검토하고 `#6427`의 중복 처리를 결정한다.

| 원본 커밋 | 최종 처리 |
| --- | --- |
| `dc80ba775cc13d6c114e1e26d21365eea3c672f6` | COM2 identity relay v2 — #6424로 main 병합, 중복 제거 |
| `57f1848882007e920ce44f667d1612169cf56717` | broker replay guard — #6424로 main 병합, 중복 제거 |
| `ff0306e0e9e17bf94bd5be930d75da5b3c34a9fd` | Chat broker loopback v2 — 이 브랜치에 통합 |

main의 `#6441` DO replay claim과 `#6443` SELECT→INSERT 및 409/503 구분은 유지한다. 예전 PR 전체 tree를 덮어쓰지 않았다. 모델·공급자·route 선택은 변경하지 않는다.

## 설정 이름과 기존 권위

값은 COM2의 기존 승인된 비밀 경로에서만 배치한다. stdout·argv·Git·PR에는 넣지 않는다.

| 위치 | 이름 | 의미 |
| --- | --- | --- |
| P01, 추가 | `PADIEM_ENGINE_LOCAL_IDENTITY_ORIGIN` | 기존 identity Worker의 bare HTTPS workers.dev origin |
| P01, 추가 | `PADIEM_ENGINE_LOCAL_IDENTITY_SECRET` | 해당 Worker's `PADIEM_IDENTITY_RPC_INGRESS_SECRET`와 일치하는 기존 값 |
| P01, 기존 확인 | `PADIEM_ENGINE_LOCAL_ADMISSION_ORIGIN` | 기존 engine-admission Worker의 bare HTTPS origin |
| P01, 기존 확인 | `PADIEM_ENGINE_LOCAL_ADMISSION_SECRET` | 해당 Worker's `PADIEM_ENGINE_ADMISSION_RPC_INGRESS_SECRET`와 일치하는 기존 값 |
| Chat, 기존 재사용 | `PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN` | 동일 canonical identity authority의 기존 HTTPS origin |
| Chat, 기존 재사용 | `PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET` | 기존 identity ingress 서명 비밀 |

Chat→P01의 `PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN`, `PADIEM_CHAT_LOCAL_P01_CALLER_ID`, `PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL`, P01의 `PADIEM_ENGINE_CALLER_ID`, `PADIEM_ENGINE_CALLER_SECRET`, B14 origin/proof는 기존 설정을 유지한다. 새 Chat 설정 이름은 없다.

## 머지 후 COM2 실행 레인 반영 절차

이번 작업에서는 아래를 실행하지 않았다. PR 생성·머지는 CTO, 운영 반영은 지정된 COM2 레인 소관이다.

1. CTO가 승인한 병합 SHA와 현재 서비스가 읽는 checkout/release 경로를 확인한다. P01 `/opt/padiem/p01/app`의 이전 release 및 `/opt/padiem/p01/env/p01.env`, Chat `/opt/padiem/chat-com2`의 코드 링크와 `.env`를 기존 보호된 백업 절차로 보관한다. 환경값은 출력하지 않는다.
2. 기존 secret source에서 P01의 identity 설정 두 이름을 추가한다. admission 설정과 Chat identity 설정의 존재·대상 일치를 값 비노출 방식으로 확인한다. Worker ingress가 기존 v2 계약을 받는지 확인하며, 이 변경을 이유로 Worker·DNS·tunnel·인증 정책을 바꾸지 않는다.
3. identity authority에 현재 사용자의 기존 b62 product link와 ACTIVE canonical 세션이 필요하다. 없으면 기존 로그인/identity 연결 경로를 점검한다. 로컬에서 subject나 entitlement를 합성하거나 DB를 직접 수정해 통과시키지 않는다.
4. 기존 COM2 절차에 따라 P01을 중지하고 `deploy/host-com2/p01/install.sh --apply --source-root <병합 checkout>`으로 코드를 배치한다. Chat도 중지한 상태에서 기존 installer/checkout 링크 갱신 절차로 동일 SHA를 반영한다. P01 `check_config.py`, Chat 기존 설정 검사와 서비스 계정 import 검사를 수행한다. 설정 검사의 READY는 entitlement 성공 증거가 아니다.
5. 기존 unit으로 P01, Chat을 기동한다. 루프백 8811/8798 상태를 확인한 뒤 승인된 로그인 세션에서 질문 1회: `POST /api/orchestration` 200 + 답변, P01 admission 통과, B14 도달을 확인한다. 원문 사용자 ID·쿠키·토큰·질문·응답은 보고에 담지 않는다.
6. 실패하면 코드와 환경 백업을 함께 복원하는 기존 COM2 rollback 절차를 적용한다. 증거는 HTTP 상태와 안전한 오류 코드만 남긴다. 이 작업은 도메인 전환/rollback이나 Cloudflare 변경을 포함하지 않는다.

## 시험

- `apps/padiem-chat/tests/test_p01_identity_roundtrip_261031.py`: 실제 Chat 서명 쿠키·라우트 → 호스트 P01 ASGI → 실제 entitlement producer 및 v2 ingress 검증 → B14 fake. 200 + answer, product-local 이력 소유 유지.
- 핵심 canonical resolver 전달을 제거한 변이: 실제 producer가 `engine_entitlement_identity_unavailable`, 외부 응답 503, B14 호출 0. 서명 불일치·미로그인도 거부.
- 집중 시험 총 **181 passed**, 실패·건너뜀 0. P01 identity HTTPS/바인딩·admission·로컬 ASGI/B14·꾸러미 61건, Chat host·왕복·legacy/shared identity·broker/WebSocket 89건, broker·identity proxy·Control Plane replay 31건.
- 최신 main 이동으로 추가된 제품 코드는 이미 시험한 #6424와 동일함을 파일 diff로 확인했다. 나머지 변경은 별도 host answer 시험 추가여서 위 증거를 유지했다.
- 모든 외부 전송은 fake이며 실제 리허설·운영 요청·배포·워크플로 dispatch는 실행하지 않았다. 운영 성공은 머지 후 위 실행 레인의 검증 대상이다.
